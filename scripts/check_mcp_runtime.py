"""Exercise real CLI transports with two clients and a restarted reader.

Without --source-root, Python runs isolated from the checkout and must import an
installed wheel. Fixed test speeches validate transport/state, not model quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import anyio
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import ResourceUpdatedNotification, ServerNotification

from mcp import ClientSession, StdioServerParameters


async def exercise(connect):
    async def call(client, name, **arguments):
        result = await client.call_tool(name, arguments)
        assert not result.isError, result
        data = json.loads(result.content[0].text)
        assert "error" not in data, data
        return data

    async def updated(queue, expected):
        seen = set()
        with anyio.fail_after(5):
            while not expected.issubset(seen):
                uri = await queue.get()
                assert uri in expected, (uri, expected)
                seen.add(uri)

    def drain(queue):
        while not queue.empty():
            queue.get_nowait()

    async with connect() as writer:
        tools = {tool.name for tool in (await writer.list_tools()).tools}
        assert {"roundtable_speak", "roundtable_ack_inbox", "roundtable_update_context"} <= tools
        assert (await writer.list_resources()).resources
        assert (await writer.list_prompts()).prompts
        for agent in ["a", "b"]:
            await call(writer, "roundtable_register_agent", agent_id=agent, platform="runtime-smoke")
        created = await call(
            writer,
            "roundtable_create",
            topic="CLI transport fixture",
            participants=[{"profile": "a"}, {"profile": "b"}],
            max_rounds=1,
            web=False,
        )
        did = created["discussion_id"]
        base = f"roundtable://discussions/{did}"
        transcript = base + "/transcript"
        collection = "roundtable://discussions"
        queue = asyncio.Queue()
        async with connect(queue) as reader:
            for uri in [base, transcript, collection]:
                await reader.subscribe_resource(uri)
            # Let invalidations from setup writes drain before testing a new mutation.
            await asyncio.sleep(0.3)
            drain(queue)
            await call(writer, "roundtable_speak", discussion_id=did, participant="coordinator", content="Opening")
            await updated(queue, {base, transcript, collection})
            resource = await reader.read_resource(transcript)
            assert "Opening" in json.loads(resource.contents[0].text)["transcript"]
            await reader.unsubscribe_resource(base)
            await reader.unsubscribe_resource(collection)
            await asyncio.sleep(0.3)
            drain(queue)
            await call(writer, "roundtable_speak", discussion_id=did, participant="a", content="First test view")
            await updated(queue, {transcript})
            before_restart = await call(reader, "roundtable_read", discussion_id=did)

            inbox = await call(reader, "roundtable_inbox", agent_id="a", mark_read=False)
            ids = [m["id"] for m in inbox["messages"]]
            assert ids
            again = await call(reader, "roundtable_inbox", agent_id="a", mark_read=False)
            assert ids == [m["id"] for m in again["messages"]]
            ack = await call(reader, "roundtable_ack_inbox", agent_id="a", message_ids=ids)
            assert ack["acknowledged"] == len(ids)
            retry = await call(reader, "roundtable_ack_inbox", agent_id="a", message_ids=ids)
            assert retry["acknowledged"] == 0

        queue = asyncio.Queue()
        async with connect(queue) as restarted:
            assert await call(restarted, "roundtable_read", discussion_id=did) == before_restart
            await restarted.subscribe_resource(transcript)
            await asyncio.sleep(0.3)
            drain(queue)
            await call(writer, "roundtable_speak", discussion_id=did, participant="b", content="Second test view")
            await updated(queue, {transcript})
            await call(
                writer, "roundtable_end", discussion_id=did, conclusion="Transport verified; no model evaluation."
            )
            await updated(queue, {transcript})
            final = await call(restarted, "roundtable_summarize", discussion_id=did)
            assert final["conclusion"] == "Transport verified; no model evaluation."
            assert final["total_rounds"] == final["completed_rounds"] == 1
            assert final["speech_count"] == 3
    return {
        "tools": len(tools),
        "two_clients": True,
        "reader_restart": True,
        "exact_subscription_uris": True,
        "unsubscribe": True,
        "inbox_ack": True,
        "conclusion": True,
    }


async def run(args, root):
    log = root / "server.log"
    command = [args.python]
    env = os.environ.copy()
    if args.source_root:
        env["PYTHONPATH"] = str(args.source_root.resolve() / "src")
    else:
        command.append("-I")
        env.pop("PYTHONPATH", None)
    command += ["-m", "roundtable.mcp", "--db", str(root / "shared.db")]
    process = None
    with log.open("w+") as errlog:
        try:
            if args.transport == "sse":
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                process = subprocess.Popen(
                    [*command, "--http", "--host", "127.0.0.1", "--port", str(port)],
                    cwd=root,
                    env=env,
                    stdout=errlog,
                    stderr=errlog,
                )
                with anyio.fail_after(10):
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(f"Server exited with {process.returncode}")
                        try:
                            _, stream = await asyncio.open_connection("127.0.0.1", port)
                            stream.close()
                            await stream.wait_closed()
                            break
                        except OSError:
                            await asyncio.sleep(0.05)

            @asynccontextmanager
            async def connect(queue=None):
                async def receive(message):
                    if (
                        queue is not None
                        and isinstance(message, ServerNotification)
                        and isinstance(message.root, ResourceUpdatedNotification)
                    ):
                        queue.put_nowait(str(message.root.params.uri))

                transport = (
                    sse_client(f"http://127.0.0.1:{port}/sse")
                    if args.transport == "sse"
                    else stdio_client(
                        StdioServerParameters(command=command[0], args=command[1:], env=env, cwd=str(root)),
                        errlog=errlog,
                    )
                )
                async with (
                    transport as streams,
                    ClientSession(
                        *streams, message_handler=receive, read_timeout_seconds=timedelta(seconds=10)
                    ) as client,
                ):
                    info = await client.initialize()
                    assert info.capabilities.resources and info.capabilities.resources.subscribe is True
                    yield client

            result = await exercise(connect)
            return {"transport": args.transport, "isolated_install": args.source_root is None, **result}
        except BaseException:
            errlog.flush()
            print(log.read_text()[-6000:], file=sys.stderr)
            raise
        finally:
            if process is not None:
                process.terminate()
                try:
                    await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await asyncio.to_thread(process.wait)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="roundtable-mcp-smoke-") as directory:
        result = asyncio.run(run(args, Path(directory)))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
