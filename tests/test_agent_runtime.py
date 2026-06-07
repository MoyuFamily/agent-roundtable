"""Tests for the lightweight agent daemon runtime."""

from __future__ import annotations

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

    conn = db.connect()
    try:
        summons = db.get_summons(conn, discussion_id=summon["discussion_id"], agent_id="manual-agent")
        assert summons[0]["status"] == "pending"
    finally:
        conn.close()
