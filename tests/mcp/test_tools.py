"""Tests for MCP tool handlers."""

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
