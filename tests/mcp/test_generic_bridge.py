"""Tests for GenericBridge HTTP endpoints."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.bridges.generic import GenericBridge
from roundtable.mcp.tools import handle_tool_call


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
    except PermissionError:
        pytest.skip("Socket binding not permitted (sandboxed environment)")
    port = s.getsockname()[1]
    s.close()
    return port


# Skip the whole module if even a single ephemeral bind isn't allowed.
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


def _start_webhook_server(port: int, events: list[dict]) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            events.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format: str, *args) -> None:
            return

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def bridge(tmp_path):
    port = _free_port()
    b = GenericBridge(
        agent_id="wb-agent-1",
        platform="workbuddy",
        port=port,
        display_name="WorkBuddy Test",
        db_path=str(tmp_path / "test.db"),
    )
    b.start()
    _wait_ready(port)
    yield b
    b.stop()


def test_health_endpoint(bridge):
    data = _get(bridge.port, "/health")
    assert data["status"] == "ok"
    assert data["agent_id"] == "wb-agent-1"
    assert data["platform"] == "workbuddy"


def test_agent_endpoint_returns_registered_agent(bridge):
    data = _get(bridge.port, "/agent")
    assert data["agent_id"] == "wb-agent-1"
    assert data["platform"] == "workbuddy"
    assert data["display_name"] == "WorkBuddy Test"


def test_inbox_starts_empty(bridge):
    data = _get(bridge.port, "/inbox")
    assert data["messages"] == []


def test_tool_dispatch_register_and_list(bridge):
    # Register a second agent via the tool endpoint.
    _post(
        bridge.port,
        "/tool",
        {
            "name": "roundtable_register_agent",
            "arguments": {
                "agent_id": "peer",
                "platform": "claude-code",
            },
        },
    )

    listed = _post(
        bridge.port,
        "/tool",
        {
            "name": "roundtable_list_agents",
            "arguments": {},
        },
    )
    ids = {a["agent_id"] for a in listed["agents"]}
    assert "wb-agent-1" in ids
    assert "peer" in ids


def test_http_invite_delivery_accepts_and_adds_participant(tmp_path):
    port = _free_port()
    db_path = tmp_path / "shared.db"
    invited = GenericBridge(
        agent_id="wb-invited",
        platform="workbuddy",
        port=port,
        display_name="Invited WorkBuddy",
        db_path=str(db_path),
    )
    invited.start()
    _wait_ready(port)
    try:
        db = RoundtableDB(db_path)
        core = RoundtableCore(db=db)
        handle_tool_call(
            core,
            db,
            "roundtable_register_agent",
            {
                "agent_id": "coord",
                "platform": "claude-code",
            },
        )

        result = handle_tool_call(
            core,
            db,
            "roundtable_create",
            {
                "topic": "HTTP invite",
                "participants": [
                    {"profile": "coord", "role": "Coordinator"},
                    {"profile": "wb-invited", "role": "Engineer"},
                ],
                "created_by": "coord",
                "invite_agents": ["wb-invited"],
            },
        )

        assert result["invites"][0]["delivery"]["ok"] is True
        conn = db.connect()
        try:
            invitations = db.get_invitations(
                conn,
                agent_id="wb-invited",
                discussion_id=result["discussion_id"],
            )
            active = db.get_active_participant_names(conn, result["discussion_id"])
        finally:
            conn.close()
        assert invitations[0]["status"] == "accepted"
        assert "wb-invited" in active
    finally:
        invited.stop()


def test_bridge_forwards_turn_to_webhook(tmp_path):
    webhook_events: list[dict] = []
    webhook_port = _free_port()
    webhook = _start_webhook_server(webhook_port, webhook_events)
    bridge_port = _free_port()
    bridge = GenericBridge(
        agent_id="wb-webhook",
        platform="workbuddy",
        port=bridge_port,
        display_name="Webhook WorkBuddy",
        webhook_url=f"http://127.0.0.1:{webhook_port}",
        db_path=str(tmp_path / "webhook.db"),
    )
    bridge.start()
    _wait_ready(bridge_port)
    try:
        response = _post(
            bridge_port,
            "/turn",
            {
                "type": "turn",
                "discussion_id": "rt_test",
                "agent_id": "wb-webhook",
                "round": 1,
            },
        )
        deadline = time.time() + 2
        while not webhook_events and time.time() < deadline:
            time.sleep(0.05)

        assert response["received"] is True
        assert webhook_events[0]["event"] == "turn"
        assert webhook_events[0]["payload"]["discussion_id"] == "rt_test"
    finally:
        bridge.stop()
        webhook.shutdown()


def test_speak_shorthand(bridge):
    create = _post(
        bridge.port,
        "/tool",
        {
            "name": "roundtable_create",
            "arguments": {
                "topic": "GenericBridge integration",
                "participants": [
                    {"profile": "wb-agent-1", "role": "Engineer"},
                    {"profile": "peer", "role": "Coordinator"},
                ],
                "created_by": "wb-agent-1",
            },
        },
    )
    disc_id = create["discussion_id"]

    result = _post(
        bridge.port,
        "/speak",
        {
            "discussion_id": disc_id,
            "participant": "coordinator",
            "content": "Opening the discussion.",
        },
    )
    assert result.get("ok")


def test_status_endpoint(bridge):
    create = _post(
        bridge.port,
        "/tool",
        {
            "name": "roundtable_create",
            "arguments": {
                "topic": "Status test",
                "participants": [
                    {"profile": "wb-agent-1", "role": "Engineer"},
                    {"profile": "peer", "role": "Coordinator"},
                ],
                "created_by": "wb-agent-1",
            },
        },
    )
    disc_id = create["discussion_id"]

    status = _get(bridge.port, f"/status/{disc_id}")
    assert status.get("ok")


def test_unknown_path_returns_404(bridge):
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{bridge.port}/does-not-exist",
            timeout=2,
        )
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_tool_endpoint_rejects_missing_name(bridge):
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{bridge.port}/tool",
                data=json.dumps({"arguments": {}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout=2,
        )
        raise AssertionError("expected 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400
        body = json.loads(e.read())
        assert "name" in body["error"]
