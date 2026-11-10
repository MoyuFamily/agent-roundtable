"""Tests for the lightweight agent daemon runtime."""

from __future__ import annotations

import roundtable.agent as agent_module
from roundtable.agent import AgentDaemon
from roundtable.db import RoundtableDB
from roundtable.mcp.tools import handle_tool_call


def test_agent_daemon_registers_heartbeats_and_accepts_summon(tmp_path):
    db = RoundtableDB(tmp_path / "daemon.db")
    daemon = AgentDaemon(agent_id="daemon-1", platform="codex", db=db, poll_interval=0.1)

    registration = daemon.register()
    assert registration["agent_id"] == "daemon-1"

    handle_tool_call(daemon.core, db, "roundtable_register_agent", {"agent_id": "coord", "platform": "claude-code"})
    summon = handle_tool_call(
        daemon.core,
        db,
        "roundtable_summon_agents",
        {
            "topic": "Daemon summon",
            "coordinator_agent_id": "coord",
            "agent_ids": ["daemon-1"],
            "required_skill": "agent-roundtable",
            "min_accepts": 1,
        },
    )
    assert summon["ok"] is True
    assert summon["readiness"]["ready"] is False

    tick = daemon.tick()
    assert tick["handled"][0]["type"] == "summon"
    assert tick["handled"][0]["result"]["status"] == "accepted"
    assert tick["handled"][0]["acknowledged"] is True

    conn = db.connect()
    try:
        discussion = db.get_discussion(conn, summon["discussion_id"])
        dispatch = db.get_dispatch(conn, summon["dispatch"]["id"])
        assert discussion.status == "active"
        assert dispatch["status"] == "active"
        assert "daemon-1" in db.get_active_participant_names(conn, summon["discussion_id"])
    finally:
        conn.close()


def test_agent_daemon_manual_policy_leaves_summon_pending(tmp_path):
    db = RoundtableDB(tmp_path / "manual.db")
    daemon = AgentDaemon(
        agent_id="manual-agent",
        platform="codex",
        db=db,
        accept_policy="manual",
        poll_interval=0.1,
    )
    daemon.register()
    handle_tool_call(daemon.core, db, "roundtable_register_agent", {"agent_id": "coord", "platform": "claude-code"})
    summon = handle_tool_call(
        daemon.core,
        db,
        "roundtable_summon_agents",
        {
            "topic": "Manual summon",
            "coordinator_agent_id": "coord",
            "agent_ids": ["manual-agent"],
            "required_skill": "agent-roundtable",
        },
    )

    tick = daemon.tick()
    assert tick["handled"][0]["status"] == "ignored"
    assert tick["handled"][0]["acknowledged"] is False
    assert daemon.tick()["messages"] == tick["messages"]

    conn = db.connect()
    try:
        summons = db.get_summons(conn, discussion_id=summon["discussion_id"], agent_id="manual-agent")
        assert summons[0]["status"] == "pending"
    finally:
        conn.close()


def create_summon(daemon):
    handle_tool_call(daemon.core, daemon.db, "roundtable_register_agent", {"agent_id": "coord", "platform": "test"})
    result = handle_tool_call(
        daemon.core,
        daemon.db,
        "roundtable_summon_agents",
        {
            "topic": "Reliable inbox",
            "coordinator_agent_id": "coord",
            "agent_ids": [daemon.agent_id],
            "required_skill": "agent-roundtable",
            "min_accepts": 1,
        },
    )
    assert result["ok"]
    return result


def test_daemon_does_not_consume_turns_or_starve_summons(tmp_path):
    daemon = AgentDaemon(agent_id="worker", platform="test", db=RoundtableDB(tmp_path / "queue.db"))
    daemon.register()
    conn = daemon.db.connect()
    try:
        # More than the default page of host-owned messages precedes the summon.
        turns = [daemon.db.push_inbox(conn, "worker", "turn", {"round": i}) for i in range(60)]
        unknown = daemon.db.push_inbox(conn, "worker", "future_message_type", {})
        create_summon(daemon)
        tick = daemon.tick()
        assert len(tick["handled"]) == 1
        assert tick["handled"][0]["acknowledged"] is True
        unread = daemon.db.read_inbox(conn, "worker", limit=100)
        assert [m["id"] for m in unread] == [*turns, unknown]
        assert daemon.tick()["handled"] == []
    finally:
        conn.close()


def test_failed_acceptance_remains_unread_until_success_after_restart(tmp_path, monkeypatch):
    db = RoundtableDB(tmp_path / "retry.db")
    daemon = AgentDaemon(agent_id="worker", platform="test", db=db)
    daemon.register()
    create_summon(daemon)
    real_call = agent_module.handle_tool_call

    def fail_accept(core, database, name, arguments):
        if name == "roundtable_accept_summon":
            return {"error": "Transient failure"}
        return real_call(core, database, name, arguments)

    monkeypatch.setattr(agent_module, "handle_tool_call", fail_accept)
    failed = daemon.tick()
    assert failed["handled"][0]["acknowledged"] is False
    monkeypatch.setattr(agent_module, "handle_tool_call", real_call)
    restarted = AgentDaemon(agent_id="worker", platform="test", db=RoundtableDB(db.db_path))
    restarted.register()
    retried = restarted.tick()
    assert retried["messages"][0]["id"] == failed["messages"][0]["id"]
    assert retried["handled"][0]["acknowledged"] is True
    assert restarted.tick()["messages"] == []


def test_one_handler_exception_does_not_ack_or_block_other_messages(tmp_path, monkeypatch):
    daemon = AgentDaemon(agent_id="worker", platform="test", db=RoundtableDB(tmp_path / "exceptions.db"))
    daemon.register()
    conn = daemon.db.connect()
    try:
        failed_id = daemon.db.push_inbox(conn, "worker", "invitation", {"discussion_id": "bad"})
        create_summon(daemon)
        real_handler = daemon._handle_message

        def handler(message):
            if message["id"] == failed_id:
                raise RuntimeError("Injected handler failure")
            return real_handler(message)

        monkeypatch.setattr(daemon, "_handle_message", handler)
        result = daemon.tick()
        assert result["handled"][0]["acknowledged"] is False
        assert result["handled"][1]["acknowledged"] is True
        assert [m["id"] for m in daemon.db.read_inbox(conn, "worker")] == [failed_id]
    finally:
        conn.close()


def test_accepted_invitation_can_be_retried_after_crash_before_ack(tmp_path):
    daemon = AgentDaemon(agent_id="worker", platform="test", db=RoundtableDB(tmp_path / "accepted.db"))
    daemon.register()
    did = daemon.core.create_discussion("Invitation retry", [{"profile": "a"}, {"profile": "b"}])["discussion_id"]
    handle_tool_call(
        daemon.core,
        daemon.db,
        "roundtable_invite",
        {
            "discussion_id": did,
            "agent_id": "worker",
            "invited_by": "coordinator",
        },
    )
    accepted = handle_tool_call(
        daemon.core,
        daemon.db,
        "roundtable_accept_invite",
        {
            "discussion_id": did,
            "agent_id": "worker",
        },
    )
    assert accepted["status"] == "accepted"
    # Acceptance committed, but the old process did not acknowledge the inbox row.
    restarted = AgentDaemon(agent_id="worker", platform="test", db=RoundtableDB(daemon.db.db_path))
    tick = restarted.tick()
    assert tick["handled"][0]["result"]["status"] == "accepted"
    assert tick["handled"][0]["acknowledged"] is True
    assert restarted.tick()["messages"] == []
