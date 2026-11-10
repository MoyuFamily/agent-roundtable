"""Tests for the Codex bridge and Codex CLI entry point."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

import pytest

from roundtable.codex import build_parser
from roundtable.mcp.bridges import CodexBridge, GenericBridge


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket binding not permitted (sandboxed environment)")
    port = s.getsockname()[1]
    s.close()
    return port


try:
    _probe = socket.socket()
    _probe.bind(("127.0.0.1", 0))
    _probe.close()
except PermissionError:
    pytest.skip(
        "Socket binding not permitted in this environment",
        allow_module_level=True,
    )


def _wait_ready(port: int, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5):
                return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.05)
    raise RuntimeError(f"bridge on port {port} never became ready")


def _get(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
        return json.loads(r.read())


def _post(port: int, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


@pytest.fixture
def bridge(tmp_path):
    port = _free_port()
    b = CodexBridge(
        agent_id="codex-test",
        port=port,
        display_name="Codex Test",
        db_path=str(tmp_path / "codex.db"),
    )
    b.start()
    _wait_ready(port)
    yield b
    b.stop()


def test_codex_bridge_health_and_agent(bridge):
    health = _get(bridge.port, "/health")
    assert health == {"status": "ok", "agent_id": "codex-test", "platform": "codex"}

    agent = _get(bridge.port, "/agent")
    assert agent["agent_id"] == "codex-test"
    assert agent["display_name"] == "Codex Test"
    assert agent["platform"] == "codex"


def test_codex_bridge_dispatches_roundtable_tools(bridge):
    listed = _post(
        bridge.port,
        "/tool",
        {
            "name": "roundtable_list_agents",
            "arguments": {},
        },
    )
    ids = {a["agent_id"] for a in listed["agents"]}
    assert "codex-test" in ids


def test_codex_parser_accepts_bridge_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "--agent-id",
            "codex-prod",
            "--port",
            "8301",
            "--host",
            "localhost",
            "--display-name",
            "Codex Product",
            "--db",
            "/tmp/roundtable.db",
            "--auth-token",
            "codex-secret",
        ]
    )

    assert args.agent_id == "codex-prod"
    assert args.port == 8301
    assert args.host == "localhost"
    assert args.display_name == "Codex Product"
    assert args.db == "/tmp/roundtable.db"
    assert args.auth_token == "codex-secret"


@pytest.fixture(params=[CodexBridge, GenericBridge])
def review_bridge(request, tmp_path):
    options = {"platform": "test"} if request.param is GenericBridge else {}
    bridge = request.param(
        agent_id="review-host", port=_free_port(), db_path=str(tmp_path / "review-http.db"), **options
    )
    bridge.start()
    _wait_ready(bridge.port)
    yield bridge
    bridge.stop()


def test_http_review_updates_prompts_turn_notices_and_restart(review_bridge):
    bridge = review_bridge

    def tool(name, **arguments):
        result = _post(bridge.port, "/tool", {"name": name, "arguments": arguments})
        assert "error" not in result, result
        return result

    for agent_id in ["a", "b"]:
        tool("roundtable_register_agent", agent_id=agent_id, platform="test")
    did = tool(
        "roundtable_create",
        topic="HTTP acceptance fixture",
        participants=[{"profile": "a"}, {"profile": "b"}],
        max_rounds=1,
        web=False,
        context="Old assumption",
    )["discussion_id"]
    tool("roundtable_speak", discussion_id=did, participant="coordinator", content="Opening")
    first = _post(bridge.port, "/speak", {"discussion_id": did, "participant": "a", "content": "FIRST_VIEW"})
    assert first["next_speaker"] == "b"
    assert first["turn_notice"]["inbox_message_id"]
    messages = tool("roundtable_inbox", agent_id="b", mark_read=False)["messages"]
    assert len([m for m in messages if m["type"] == "turn" and m["discussion_id"] == did]) == 1
    tool(
        "roundtable_update_context",
        discussion_id=did,
        context="User confirmed a new constraint",
        source="user",
        expected_revision=0,
    )
    prompt = _post(
        bridge.port,
        "/tool",
        {
            "name": "roundtable_get_prompt",
            "arguments": {"name": "participant_turn", "arguments": {"discussion_id": did, "phase": "independent"}},
        },
    )
    assert "new constraint" in prompt["text"]
    assert "Old assumption" not in prompt["text"]
    assert "FIRST_VIEW" not in prompt["text"]
    final = _post(bridge.port, "/speak", {"discussion_id": did, "participant": "b", "content": "SECOND_VIEW"})
    assert final["discussion_complete"]
    tool("roundtable_end", discussion_id=did, conclusion="Complete recommendation with limits")
    before = tool("roundtable_read", discussion_id=did)
    bridge.stop()
    bridge.start()
    _wait_ready(bridge.port)
    after = tool("roundtable_read", discussion_id=did)
    assert after == before
    assert after["conclusion"] == "Complete recommendation with limits"
    assert after["completed_rounds"] == after["total_rounds"] == 1
    assert "error" in _post(
        bridge.port,
        "/speak",
        {
            "discussion_id": did,
            "participant": "unknown",
            "content": "Invalid speech",
        },
    )
    assert "error" in _post(bridge.port, "/tool", {"name": "roundtable_read", "arguments": []})
    assert _get(bridge.port, "/health")["status"] == "ok"
