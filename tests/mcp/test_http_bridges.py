"""HTTP bridge behavior, shared by GenericBridge and the Codex preset."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from roundtable.codex import build_parser
from roundtable.mcp.bridges import CodexBridge, GenericBridge
from roundtable.mcp.tools import handle_tool_call


def _get(port, path):
    response = requests.get(f"http://127.0.0.1:{port}{path}", timeout=3)
    response.raise_for_status()
    return response.json()


def _post(port, path, body):
    return requests.post(f"http://127.0.0.1:{port}{path}", json=body, timeout=3).json()


def _tool(bridge, name, **arguments):
    result = handle_tool_call(bridge._core, bridge._db, name, arguments)
    assert "error" not in result, result
    return result


@pytest.fixture(params=[CodexBridge, GenericBridge], ids=["codex", "generic"])
def bridge_type(request):
    return request.param


@pytest.fixture
def bridge_factory(tmp_path):
    bridges = []

    def create(kind=GenericBridge, **options):
        config = {"agent_id": "review-host", "port": 0, "db_path": str(tmp_path / "review.db"), **options}
        if kind is GenericBridge:
            config["platform"] = "workbuddy"
        bridge = kind(**config)
        bridges.append(bridge)
        bridge.start()
        return bridge

    yield create
    for bridge in reversed(bridges):
        bridge.stop()


@pytest.fixture
def review_bridge(bridge_type, bridge_factory):
    return bridge_factory(bridge_type)


def test_http_review_updates_prompts_turn_notices_and_restart(review_bridge):
    bridge = review_bridge
    health = _get(bridge.port, "/health")
    agent = _get(bridge.port, "/agent")
    assert health == {"status": "ok", "agent_id": bridge.agent_id, "platform": bridge.platform}
    assert agent["endpoint"] == f"http://{bridge.host}:{bridge.port}"
    assert agent["platform"] == bridge.platform
    assert _get(bridge.port, "/inbox")["messages"] == []

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
    assert _get(bridge.port, f"/status/{did}")["next_speaker"] == "b"
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


def test_wait_for_turn_does_not_block_the_speech_it_is_waiting_for(review_bridge):
    bridge = review_bridge
    did = bridge._core.create_discussion(
        "Concurrent turn",
        [{"profile": "a"}, {"profile": "b"}],
        web=False,
    )["discussion_id"]
    bridge._core.speak(did, "coordinator", "Opening")
    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(
            _post,
            bridge.port,
            "/tool",
            {
                "name": "roundtable_wait_for_turn",
                "arguments": {"discussion_id": did, "agent_id": "b", "wait_seconds": 1.5, "poll_interval": 0.1},
            },
        )
        time.sleep(0.2)
        started = time.monotonic()
        speech = _post(bridge.port, "/speak", {"discussion_id": did, "participant": "a", "content": "Done"})
        assert speech["next_speaker"] == "b"
        assert time.monotonic() - started < 1.0
        assert waiting.result(timeout=2)["your_turn"] is True


def test_auth_covers_reads_and_writes_without_exposing_credentials(bridge_type, bridge_factory):
    bridge = bridge_factory(bridge_type, auth_token="private-token")
    base = f"http://127.0.0.1:{bridge.port}"
    did = _tool(
        bridge,
        "roundtable_create",
        topic="Private review",
        participants=[{"profile": "a"}, {"profile": "b"}],
        web=False,
    )["discussion_id"]
    cases = [("GET", "/agent"), ("GET", "/inbox"), ("GET", f"/status/{did}"), ("POST", "/tool")]
    for method, path in cases:
        body = {"name": "roundtable_list_agents", "arguments": {}} if method == "POST" else None
        for token in [None, "wrong-token"]:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = requests.request(method, base + path, json=body, headers=headers, timeout=3)
            assert response.status_code == 401
            assert response.json() == {"error": "unauthorized"}
        for headers in [{"Authorization": "Bearer private-token"}, {"X-Roundtable-Token": "private-token"}]:
            response = requests.request(method, base + path, json=body, headers=headers, timeout=3)
            assert response.status_code == 200, response.text
            assert "private-token" not in response.text
    headers = {"Authorization": "Bearer private-token"}
    for path, status in [("/status/missing", 404), ("/status/", 400), ("/missing", 404)]:
        response = requests.get(base + path, headers=headers, timeout=3)
        assert response.status_code == status
        assert "error" in response.json()
    assert _get(bridge.port, "/health")["status"] == "ok"


@pytest.mark.parametrize("policy", ["auto", "manual"])
def test_invite_and_summon_delivery_respect_policy_and_auth(bridge_type, bridge_factory, policy):
    bridge = bridge_factory(bridge_type, auth_token="delivery-secret", accept_policy=policy)
    did = _tool(
        bridge, "roundtable_create", topic="Invite review", participants=[{"profile": "a"}, {"profile": "b"}], web=False
    )["discussion_id"]
    invitation = _tool(bridge, "roundtable_invite", discussion_id=did, agent_id=bridge.agent_id, invited_by="a")
    assert invitation["delivery"]["ok"]
    assert json.loads(invitation["delivery"]["response"])["accepted"] is (policy == "auto")
    conn = bridge._db.connect()
    try:
        stored = bridge._db.get_invitations(conn, agent_id=bridge.agent_id, discussion_id=did)
        members = bridge._db.get_active_participant_names(conn, did)
    finally:
        conn.close()
    assert stored[0]["status"] == ("accepted" if policy == "auto" else "pending")
    assert (bridge.agent_id in members) is (policy == "auto")
    if policy == "manual":
        result = _tool(bridge, "roundtable_accept_invite", discussion_id=did, agent_id=bridge.agent_id)
        assert result["status"] == "accepted"
    summons = _tool(
        bridge,
        "roundtable_summon_agents",
        topic="Summon review",
        coordinator_agent_id="a",
        agent_ids=[bridge.agent_id],
        min_accepts=1,
        web=False,
    )
    assert summons["deliveries"][0]["ok"]
    assert json.loads(summons["deliveries"][0]["response"])["accepted"] is (policy == "auto")
    if policy == "manual":
        assert summons["created"]["status"] == "assembling"
        assert summons["summons"][0]["status"] == "delivered"
        _tool(bridge, "roundtable_accept_summon", discussion_id=summons["discussion_id"], agent_id=bridge.agent_id)
    else:
        assert summons["summons"][0]["status"] == "accepted"
    assert _tool(bridge, "roundtable_status", discussion_id=summons["discussion_id"])["status"] == "active"
    headers = {"Authorization": "Bearer delivery-secret"}
    messages = requests.get(f"http://127.0.0.1:{bridge.port}/inbox", headers=headers, timeout=3).json()["messages"]
    assert {m["type"] for m in messages} == {"invitation", "summon"}
    assert requests.get(f"http://127.0.0.1:{bridge.port}/inbox", headers=headers, timeout=3).json()["messages"] == []


def test_expired_summon_is_not_reported_as_accepted(review_bridge):
    bridge = review_bridge
    did = _tool(
        bridge, "roundtable_create", topic="Expired", participants=[{"profile": "a"}, {"profile": "b"}], web=False
    )["discussion_id"]
    conn = bridge._db.connect()
    try:
        bridge._db.create_summon(conn, did, bridge.agent_id, "a", expires_at=int(time.time()) - 1)
    finally:
        conn.close()
    response = _post(bridge.port, "/summon", {"discussion_id": did})
    assert response["accepted"] is False
    assert response["result"]["status"] == "timeout"
    conn = bridge._db.connect()
    try:
        assert bridge.agent_id not in bridge._db.get_active_participant_names(conn, did)
    finally:
        conn.close()


def test_start_failure_does_not_register_agent_and_restart_uses_bound_port(bridge_type, tmp_path):
    options = {"platform": "test"} if bridge_type is GenericBridge else {}
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        bridge = bridge_type(
            agent_id="startup", port=occupied.getsockname()[1], db_path=str(tmp_path / "startup.db"), **options
        )
        with pytest.raises(OSError):
            bridge.start()
        conn = bridge._db.connect()
        try:
            assert bridge._db.get_agent(conn, bridge.agent_id) is None
        finally:
            conn.close()
    bridge.start()
    try:
        port = bridge.port
        bridge.start()
        assert _get(port, "/agent")["endpoint"] == f"http://127.0.0.1:{port}"
        bridge.stop()
        bridge.start()
        assert _get(port, "/health")["status"] == "ok"
    finally:
        bridge.stop()


def test_registration_failure_releases_listener(tmp_path, monkeypatch):
    bridge = GenericBridge(agent_id="startup", platform="test", port=0, db_path=str(tmp_path / "failed.db"))
    bound = []
    from roundtable.mcp.bridges import generic

    original_server = generic.ThreadingHTTPServer

    def server(*args):
        result = original_server(*args)
        bound.append(result.server_port)
        return result

    def fail(*args, **kwargs):
        raise OSError("database unavailable")

    monkeypatch.setattr(generic, "ThreadingHTTPServer", server)
    monkeypatch.setattr(bridge._db, "connect", fail)
    with pytest.raises(OSError, match="database unavailable"):
        bridge.start()
    with socket.socket() as retry:
        retry.bind(("127.0.0.1", bound[0]))


def test_invalid_request_framing_and_json_return_errors_without_stalling(bridge_factory):
    bridge = bridge_factory()
    cases = [
        (b"Content-Length: nope", b"", 400),
        (b"Content-Length: -1", b"", 400),
        (b"Content-Length: 1048577", b"", 413),
        (b"Content-Length: 0\r\nContent-Length: 2", b"{}", 400),
        (b"Transfer-Encoding: chunked", b"0\r\n\r\n", 400),
        (b"Content-Length: 1", b"\xff", 400),
        (b"Content-Length: 1", b"{", 400),
        (b"Content-Length: 2", b"[]", 400),
        (b"Content-Length: 2", b"{}", 400),
    ]
    for headers, body, status in cases:
        with socket.create_connection(("127.0.0.1", bridge.port), timeout=3) as client:
            client.sendall(b"POST /tool HTTP/1.0\r\nHost: localhost\r\n" + headers + b"\r\n\r\n" + body)
            response = http.client.HTTPResponse(client)
            response.begin()
            assert response.status == status, (headers, response.status)
            assert "error" in json.loads(response.read())
    for body in [{"name": 1}, {"name": "roundtable_read", "arguments": []}]:
        response = requests.post(f"http://127.0.0.1:{bridge.port}/tool", json=body, timeout=3)
        assert response.status_code == 400
    assert _get(bridge.port, "/health")["status"] == "ok"


def test_webhook_receives_incoming_turn_and_local_core_event(bridge_factory):
    events = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            events.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    webhook = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=webhook.serve_forever, daemon=True)
    thread.start()
    try:
        bridge = bridge_factory(webhook_url=f"http://127.0.0.1:{webhook.server_port}")
        payload = {"discussion_id": "rt_test", "agent_id": bridge.agent_id, "round": 1}
        assert _post(bridge.port, "/turn", payload)["received"] is True
        assert events == [{"event": "turn", "payload": payload}]
        did = _tool(
            bridge,
            "roundtable_create",
            topic="Webhook review",
            participants=[{"profile": "a"}, {"profile": "b"}],
            web=False,
        )["discussion_id"]
        _post(bridge.port, "/speak", {"discussion_id": did, "participant": "coordinator", "content": "Opening"})
        assert any(event["payload"].get("discussion_id") == did for event in events)
    finally:
        webhook.shutdown()
        webhook.server_close()
        thread.join(timeout=2)


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
