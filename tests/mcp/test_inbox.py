"""Tests for inbox and invitation mechanisms."""

import pytest

from roundtable.db import RoundtableDB


@pytest.fixture
def db(tmp_path):
    database = RoundtableDB(db_path=str(tmp_path / "test.db"))
    conn = database.connect()
    conn.close()
    return database


def test_upsert_agent_idempotent(db):
    conn = db.connect()
    try:
        r1 = db.upsert_agent(conn, "agent-1", "claude-code", display_name="First")
        r2 = db.upsert_agent(conn, "agent-1", "claude-code", display_name="Updated")
        assert r1["agent_id"] == r2["agent_id"]
        agent = db.get_agent(conn, "agent-1")
        assert agent["display_name"] == "Updated"
    finally:
        conn.close()


def test_push_and_read_inbox(db):
    conn = db.connect()
    try:
        db.upsert_agent(conn, "agent-1", "cursor")
        db.push_inbox(conn, "agent-1", "invitation", {"disc": "rt_123"}, discussion_id="rt_123")
        db.push_inbox(conn, "agent-1", "turn_notice", {"round": 1}, discussion_id="rt_123")

        messages = db.read_inbox(conn, "agent-1", unread_only=True)
        assert len(messages) == 2
        assert messages[0]["type"] == "invitation"
        assert messages[1]["type"] == "turn_notice"
    finally:
        conn.close()


def test_mark_inbox_read(db):
    conn = db.connect()
    try:
        db.upsert_agent(conn, "agent-1", "cursor")
        db.push_inbox(conn, "agent-1", "invitation", {"disc": "rt_1"})
        db.push_inbox(conn, "agent-1", "invitation", {"disc": "rt_2"})

        messages = db.read_inbox(conn, "agent-1")
        ids = [m["id"] for m in messages]
        count = db.mark_inbox_read(conn, ids)
        assert count == 2

        unread = db.read_inbox(conn, "agent-1", unread_only=True)
        assert len(unread) == 0
    finally:
        conn.close()


def test_mark_inbox_read_idempotent(db):
    conn = db.connect()
    try:
        db.upsert_agent(conn, "agent-1", "cursor")
        db.push_inbox(conn, "agent-1", "invitation", {"disc": "rt_1"})

        messages = db.read_inbox(conn, "agent-1")
        ids = [m["id"] for m in messages]
        db.mark_inbox_read(conn, ids)
        count = db.mark_inbox_read(conn, ids)
        assert count == 0
    finally:
        conn.close()


def test_invitation_lifecycle(db):
    conn = db.connect()
    try:
        db.upsert_agent(conn, "agent-1", "cursor")
        db.create_invitation(conn, "rt_abc", "agent-1", "coordinator", role="Dev")

        pending = db.get_invitations(conn, agent_id="agent-1", status="pending")
        assert len(pending) == 1
        assert pending[0]["role"] == "Dev"

        result = db.respond_invitation(conn, "rt_abc", "agent-1", accept=True)
        assert result["status"] == "accepted"

        pending_after = db.get_invitations(conn, agent_id="agent-1", status="pending")
        assert len(pending_after) == 0
    finally:
        conn.close()


def test_invitation_double_respond(db):
    conn = db.connect()
    try:
        db.upsert_agent(conn, "agent-1", "cursor")
        db.create_invitation(conn, "rt_abc", "agent-1", "coordinator")
        db.respond_invitation(conn, "rt_abc", "agent-1", accept=True)

        result = db.respond_invitation(conn, "rt_abc", "agent-1", accept=False)
        assert "error" in result
    finally:
        conn.close()


def test_list_agents_online_filter(db):
    import time
    conn = db.connect()
    try:
        db.upsert_agent(conn, "online-agent", "claude-code")
        conn.execute("UPDATE agents SET last_seen = ? WHERE agent_id = ?", (int(time.time()) - 200, "offline-agent"))
        db.upsert_agent(conn, "offline-agent", "cursor")
        conn.execute("UPDATE agents SET last_seen = ? WHERE agent_id = ?", (int(time.time()) - 200, "offline-agent"))

        all_agents = db.list_agents(conn, online_only=False)
        assert len(all_agents) == 2

        online = db.list_agents(conn, online_only=True)
        assert len(online) == 1
        assert online[0]["agent_id"] == "online-agent"
    finally:
        conn.close()
