"""Tests for the Codex bridge and Codex CLI entry point."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

import pytest

from roundtable.codex import build_parser
from roundtable.mcp.bridges import CodexBridge


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
        ]
    )

    assert args.agent_id == "codex-prod"
    assert args.port == 8301
    assert args.host == "localhost"
    assert args.display_name == "Codex Product"
    assert args.db == "/tmp/roundtable.db"
