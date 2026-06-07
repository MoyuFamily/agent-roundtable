"""Tests for MCP tool handlers."""

import threading
import time

import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.tools import handle_tool_call


@pytest.fixture
def setup(tmp_path):
    db = RoundtableDB(db_path=str(tmp_path / "test.db"))
    core = RoundtableCore(db=db)
    conn = db.connect()
    conn.close()
    return core, db


def test_register_agent(setup):
    core, db = setup
    result = handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "claude-test-1",
            "platform": "claude-code",
            "display_name": "Test Claude",
        },
    )
    assert result["agent_id"] == "claude-test-1"
    assert "last_seen" in result


def test_list_agents(setup):
    core, db = setup
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "agent-a",
            "platform": "claude-code",
        },
    )
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "agent-b",
            "platform": "cursor",
        },
    )
    result = handle_tool_call(core, db, "roundtable_list_agents", {})
    assert len(result["agents"]) == 2


def test_register_agent_metadata_filters_and_heartbeat(setup):
    core, db = setup
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "codex-agent",
            "platform": "codex",
            "skills": ["agent-roundtable"],
            "availability": "idle",
            "accept_policy": "auto",
        },
    )
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "plain-agent",
            "platform": "cursor",
            "skills": ["other"],
            "availability": "idle",
        },
    )

    filtered = handle_tool_call(
        core,
        db,
        "roundtable_list_agents",
        {"required_skill": "agent-roundtable", "availability": "idle"},
    )
    assert [agent["agent_id"] for agent in filtered["agents"]] == ["codex-agent"]

    heartbeat = handle_tool_call(
        core,
        db,
        "roundtable_heartbeat",
        {"agent_id": "codex-agent", "availability": "busy"},
    )
    assert heartbeat["metadata"]["availability"] == "busy"


def test_create_discussion_and_invite(setup):
    core, db = setup
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "coordinator-1",
            "platform": "claude-code",
        },
    )
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "participant-1",
            "platform": "cursor",
        },
    )

    result = handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "Test discussion",
            "participants": [
                {"profile": "coordinator-1", "role": "Coordinator"},
                {"profile": "participant-1", "role": "Engineer"},
            ],
            "created_by": "coordinator-1",
            "invite_agents": ["participant-1"],
        },
    )
    assert result.get("discussion_id")

    inbox = handle_tool_call(core, db, "roundtable_inbox", {"agent_id": "participant-1"})
    assert len(inbox["messages"]) == 1
    assert inbox["messages"][0]["type"] == "invitation"


def test_summon_agents_creates_assembling_discussion_and_activates_on_accept(setup):
    core, db = setup
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "coord",
            "platform": "claude-code",
            "skills": ["agent-roundtable"],
            "availability": "idle",
        },
    )
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "agent-1",
            "platform": "codex",
            "skills": ["agent-roundtable"],
            "availability": "idle",
        },
    )

    summon = handle_tool_call(
        core,
        db,
        "roundtable_summon_agents",
        {
            "topic": "Summon flow",
            "coordinator_agent_id": "coord",
            "required_skill": "agent-roundtable",
            "availability": "idle",
            "agent_ids": ["agent-1"],
            "min_accepts": 1,
        },
    )

    assert summon["ok"] is True
    assert summon["created"]["status"] == "assembling"
    assert summon["summons"][0]["agent_id"] == "agent-1"
    assert summon["readiness"]["ready"] is False

    inbox = handle_tool_call(core, db, "roundtable_inbox", {"agent_id": "agent-1", "mark_read": False})
    assert inbox["messages"][0]["type"] == "summon"

    accepted = handle_tool_call(
        core,
        db,
        "roundtable_accept_summon",
        {"discussion_id": summon["discussion_id"], "agent_id": "agent-1"},
    )
    assert accepted["status"] == "accepted"
    assert accepted["dispatch"]["dispatch"]["status"] == "active"

    status = handle_tool_call(core, db, "roundtable_status", {"discussion_id": summon["discussion_id"]})
    assert status["status"] == "active"
    assert status["participant_count"] == 1


def test_dispatch_status_by_discussion(setup):
    core, db = setup
    handle_tool_call(core, db, "roundtable_register_agent", {"agent_id": "coord", "platform": "claude-code"})
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "agent-1",
            "platform": "codex",
            "skills": ["agent-roundtable"],
            "availability": "idle",
        },
    )
    summon = handle_tool_call(
        core,
        db,
        "roundtable_summon_agents",
        {
            "topic": "Dispatch status",
            "coordinator_agent_id": "coord",
            "agent_ids": ["agent-1"],
            "required_skill": "agent-roundtable",
        },
    )

    status = handle_tool_call(core, db, "roundtable_dispatch_status", {"discussion_id": summon["discussion_id"]})
    assert status["ok"] is True
    assert status["count"] == 1
    assert status["dispatches"][0]["dispatch"]["id"] == summon["dispatch"]["id"]


def test_retry_summon_requeues_without_duplicate_rows(setup):
    core, db = setup
    handle_tool_call(core, db, "roundtable_register_agent", {"agent_id": "coord", "platform": "claude-code"})
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "agent-1",
            "platform": "codex",
            "skills": ["agent-roundtable"],
            "availability": "idle",
        },
    )
    summon = handle_tool_call(
        core,
        db,
        "roundtable_summon_agents",
        {
            "topic": "Retry summon",
            "coordinator_agent_id": "coord",
            "agent_ids": ["agent-1"],
            "required_skill": "agent-roundtable",
            "dispatch_timeout_seconds": 1,
        },
    )
    summon_id = summon["summons"][0]["id"]

    conn = db.connect()
    try:
        db.mark_summon_delivered(conn, summon_id, {"ok": False, "error": "network"})
    finally:
        conn.close()

    retry = handle_tool_call(
        core,
        db,
        "roundtable_retry_summon",
        {
            "dispatch_id": summon["dispatch"]["id"],
            "retry_timeout_seconds": 30,
            "redeliver_http": False,
        },
    )

    assert retry["ok"] is True
    assert retry["count"] == 1
    assert retry["retried"][0]["id"] == summon_id
    assert retry["retried"][0]["status"] == "pending"

    conn = db.connect()
    try:
        summons = db.get_summons(conn, dispatch_id=summon["dispatch"]["id"])
        inbox = db.read_inbox(conn, "agent-1", unread_only=False)
        events = db.list_summon_events(conn, summon_id=summon_id)
    finally:
        conn.close()
    assert len(summons) == 1
    assert len([msg for msg in inbox if msg["type"] == "summon"]) == 2
    assert "summon.retry" in [event["event"] for event in events]


def test_summon_agents_allows_terminal_dispatch_retry_with_same_key(setup):
    core, db = setup
    handle_tool_call(core, db, "roundtable_register_agent", {"agent_id": "coord", "platform": "claude-code"})
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "agent-1",
            "platform": "codex",
            "skills": ["agent-roundtable"],
            "availability": "idle",
        },
    )
    first = handle_tool_call(
        core,
        db,
        "roundtable_summon_agents",
        {
            "topic": "Retry dispatch key",
            "coordinator_agent_id": "coord",
            "agent_ids": ["agent-1"],
            "required_skill": "agent-roundtable",
            "idempotency_key": "mcp-retry-key",
        },
    )

    conn = db.connect()
    try:
        db.update_dispatch_status(conn, first["dispatch"]["id"], "cancelled")
    finally:
        conn.close()

    second = handle_tool_call(
        core,
        db,
        "roundtable_summon_agents",
        {
            "discussion_id": first["discussion_id"],
            "coordinator_agent_id": "coord",
            "agent_ids": ["agent-1"],
            "required_skill": "agent-roundtable",
            "idempotency_key": "mcp-retry-key",
            "allow_terminal_retry": True,
        },
    )

    assert second["ok"] is True
    assert second["dispatch"]["id"] != first["dispatch"]["id"]
    assert second["summons"][0]["id"] == first["summons"][0]["id"]
    assert second["summons"][0]["dispatch_id"] == second["dispatch"]["id"]
    assert second["summons"][0]["status"] == "pending"

    conn = db.connect()
    try:
        summons = db.get_summons(conn, discussion_id=first["discussion_id"], agent_id="agent-1")
        old_dispatch = db.get_dispatch(conn, first["dispatch"]["id"])
        old_events = db.list_summon_events(conn, dispatch_id=first["dispatch"]["id"])
        summon_events = db.list_summon_events(conn, summon_id=first["summons"][0]["id"])
    finally:
        conn.close()

    assert len(summons) == 1
    assert old_dispatch["idempotency_key"] == f"mcp-retry-key#released:{first['dispatch']['id']}"
    assert "dispatch.idempotency_key.released" in [event["event"] for event in old_events]
    assert "summon.reused_for_retry" in [event["event"] for event in summon_events]


def test_create_discussion_disables_web_by_default(setup, monkeypatch):
    core, db = setup
    calls = []

    def fake_create_discussion(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "discussion_id": "rt_fake", "web_url": "should-not-start"}

    monkeypatch.setattr(core, "create_discussion", fake_create_discussion)

    result = handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "No web by default",
            "participants": [
                {"profile": "alice", "role": "Dev"},
                {"profile": "bob", "role": "PM"},
            ],
        },
    )

    assert result["discussion_id"] == "rt_fake"
    assert calls[0]["web"] is False


def test_accept_invite_and_speak(setup):
    core, db = setup
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "coord",
            "platform": "claude-code",
        },
    )
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "dev",
            "platform": "cursor",
        },
    )

    create_result = handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "Architecture review",
            "participants": [
                {"profile": "coord", "role": "Coordinator"},
                {"profile": "dev", "role": "Developer"},
            ],
            "created_by": "coord",
            "invite_agents": ["dev"],
        },
    )
    disc_id = create_result["discussion_id"]

    accept = handle_tool_call(
        core,
        db,
        "roundtable_accept_invite",
        {
            "discussion_id": disc_id,
            "agent_id": "dev",
        },
    )
    assert accept["status"] == "accepted"

    speak_result = handle_tool_call(
        core,
        db,
        "roundtable_speak",
        {
            "discussion_id": disc_id,
            "participant": "coordinator",
            "content": "Let's discuss the architecture.",
        },
    )
    assert speak_result.get("ok")


def test_decline_invite(setup):
    core, db = setup
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "coord",
            "platform": "claude-code",
        },
    )
    handle_tool_call(
        core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "busy-agent",
            "platform": "windsurf",
        },
    )

    create_result = handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "Quick sync",
            "participants": [
                {"profile": "coord", "role": "Lead"},
                {"profile": "busy-agent", "role": "Dev"},
            ],
            "invite_agents": ["busy-agent"],
            "created_by": "coord",
        },
    )
    disc_id = create_result["discussion_id"]

    decline = handle_tool_call(
        core,
        db,
        "roundtable_decline_invite",
        {
            "discussion_id": disc_id,
            "agent_id": "busy-agent",
        },
    )
    assert decline["status"] == "declined"


def test_wait_for_turn(setup):
    core, db = setup
    create_result = handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "Turn test",
            "participants": [
                {"profile": "alice", "role": "Dev"},
                {"profile": "bob", "role": "PM"},
            ],
            "created_by": "coord",
        },
    )
    disc_id = create_result["discussion_id"]

    handle_tool_call(
        core,
        db,
        "roundtable_speak",
        {
            "discussion_id": disc_id,
            "participant": "coordinator",
            "content": "Opening.",
        },
    )

    turn = handle_tool_call(
        core,
        db,
        "roundtable_wait_for_turn",
        {
            "discussion_id": disc_id,
            "agent_id": "alice",
        },
    )
    assert turn["your_turn"] is True
    assert turn["next_speaker"] == "alice"

    turn_bob = handle_tool_call(
        core,
        db,
        "roundtable_wait_for_turn",
        {
            "discussion_id": disc_id,
            "agent_id": "bob",
        },
    )
    assert turn_bob["your_turn"] is False


def test_wait_for_turn_can_poll_until_turn_arrives(setup):
    core, db = setup
    create_result = handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "Wait test",
            "participants": [
                {"profile": "alice", "role": "Dev"},
                {"profile": "bob", "role": "PM"},
            ],
            "created_by": "coord",
        },
    )
    disc_id = create_result["discussion_id"]
    handle_tool_call(
        core,
        db,
        "roundtable_speak",
        {
            "discussion_id": disc_id,
            "participant": "coordinator",
            "content": "Opening.",
        },
    )

    def delayed_alice_speech():
        time.sleep(0.2)
        handle_tool_call(
            core,
            db,
            "roundtable_speak",
            {
                "discussion_id": disc_id,
                "participant": "alice",
                "content": "Alice spoke.",
            },
        )

    thread = threading.Thread(target=delayed_alice_speech)
    thread.start()
    try:
        turn = handle_tool_call(
            core,
            db,
            "roundtable_wait_for_turn",
            {
                "discussion_id": disc_id,
                "agent_id": "bob",
                "wait_seconds": 2,
                "poll_interval": 0.05,
            },
        )
    finally:
        thread.join(timeout=2)

    assert turn["your_turn"] is True
    assert turn["next_speaker"] == "bob"


def test_full_discussion_flow(setup):
    core, db = setup
    create_result = handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "Full flow test",
            "participants": [
                {"profile": "alice", "role": "Dev"},
                {"profile": "bob", "role": "PM"},
            ],
            "max_rounds": 1,
            "created_by": "coord",
        },
    )
    disc_id = create_result["discussion_id"]

    handle_tool_call(
        core,
        db,
        "roundtable_speak",
        {
            "discussion_id": disc_id,
            "participant": "coordinator",
            "content": "Opening statement.",
        },
    )

    handle_tool_call(
        core,
        db,
        "roundtable_speak",
        {
            "discussion_id": disc_id,
            "participant": "alice",
            "content": "I think we should use PostgreSQL.",
        },
    )

    result = handle_tool_call(
        core,
        db,
        "roundtable_speak",
        {
            "discussion_id": disc_id,
            "participant": "bob",
            "content": "I agree with Alice.",
        },
    )
    assert result["round_complete"] is True

    status = handle_tool_call(core, db, "roundtable_status", {"discussion_id": disc_id})
    assert status.get("ok")

    end = handle_tool_call(
        core,
        db,
        "roundtable_end",
        {
            "discussion_id": disc_id,
            "conclusion": "We chose PostgreSQL.",
        },
    )
    assert end.get("ok")


def test_list_discussions(setup):
    core, db = setup
    handle_tool_call(
        core,
        db,
        "roundtable_create",
        {
            "topic": "Discussion 1",
            "participants": [
                {"profile": "a", "role": "Dev"},
                {"profile": "b", "role": "PM"},
            ],
        },
    )
    result = handle_tool_call(core, db, "roundtable_list", {})
    assert result.get("ok")
    assert len(result["discussions"]) >= 1
