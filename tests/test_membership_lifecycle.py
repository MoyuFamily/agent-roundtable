"""Late replies and failed joins must not mutate closed or partially joined meetings."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.tools import handle_tool_call


@pytest.fixture
def pending(tmp_path):
    db = RoundtableDB(tmp_path / "membership.db")
    core = RoundtableCore(db=db)
    for name in ["host", "worker"]:
        handle_tool_call(core, db, "roundtable_register_agent", {"agent_id": name, "platform": "test"})
    meeting = handle_tool_call(
        core,
        db,
        "roundtable_summon_agents",
        {
            "topic": "Membership fixture",
            "coordinator_agent_id": "host",
            "agent_ids": ["worker"],
            "min_accepts": 1,
            "dispatch_timeout_seconds": 120,
        },
    )
    assert meeting["ok"]
    return core, db, meeting


@pytest.mark.parametrize("status", ["pending", "delivered", "failed"])
def test_expired_summon_cannot_be_accepted_before_expiry_poll(pending, status):
    core, db, meeting = pending
    did = meeting["discussion_id"]
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE summons SET expires_at = ?, status = ? WHERE discussion_id = ?", (int(time.time()) - 1, status, did)
        )
        result = handle_tool_call(
            core,
            db,
            "roundtable_accept_summon",
            {
                "discussion_id": did,
                "agent_id": "worker",
            },
        )
        assert result["status"] == "timeout"
        assert "worker" not in db.get_active_participant_names(conn, did)
        assert db.get_discussion(conn, did).status == "assembling"
    finally:
        conn.close()


def test_cancelled_meeting_rejects_late_summon(pending):
    core, db, meeting = pending
    did = meeting["discussion_id"]
    core.end(did, force=True)
    result = handle_tool_call(core, db, "roundtable_accept_summon", {"discussion_id": did, "agent_id": "worker"})
    assert "error" in result
    conn = db.connect()
    try:
        assert db.get_discussion(conn, did).status == "cancelled"
        assert "worker" not in db.get_active_participant_names(conn, did)
    finally:
        conn.close()


def test_summon_acceptance_rolls_back_if_join_fails(pending, monkeypatch):
    core, db, meeting = pending
    did = meeting["discussion_id"]

    def fail_join(*args, **kwargs):
        raise RuntimeError("Injected participant-write failure")

    monkeypatch.setattr(db, "add_participant", fail_join)
    result = handle_tool_call(core, db, "roundtable_accept_summon", {"discussion_id": did, "agent_id": "worker"})
    assert "error" in result
    conn = db.connect()
    try:
        assert db.get_summon(conn, discussion_id=did, agent_id="worker")["status"] == "pending"
        assert not [
            event
            for event in db.list_summon_events(conn, dispatch_id=meeting["dispatch"]["id"])
            if event["event"] == "summon.accepted"
        ]
    finally:
        conn.close()


@pytest.mark.parametrize("closed", [False, True])
def test_invitation_join_is_atomic_and_rejects_closed_review(tmp_path, monkeypatch, closed):
    db = RoundtableDB(tmp_path / "invitation.db")
    core = RoundtableCore(db=db)
    handle_tool_call(core, db, "roundtable_register_agent", {"agent_id": "worker", "platform": "test"})
    did = core.create_discussion("Invite fixture", [{"profile": "a"}, {"profile": "b"}], web=False)["discussion_id"]
    handle_tool_call(
        core,
        db,
        "roundtable_invite",
        {
            "discussion_id": did,
            "agent_id": "worker",
            "invited_by": "host",
        },
    )
    if closed:
        core.end(did, conclusion="Finished")
    else:

        def fail_join(*args, **kwargs):
            raise RuntimeError("Injected join failure")

        monkeypatch.setattr(db, "add_participant", fail_join)
    result = handle_tool_call(core, db, "roundtable_accept_invite", {"discussion_id": did, "agent_id": "worker"})
    assert "error" in result
    conn = db.connect()
    try:
        assert db.get_invitations(conn, discussion_id=did, agent_id="worker")[0]["status"] == "pending"
        assert "worker" not in db.get_active_participant_names(conn, did)
    finally:
        conn.close()


def test_concurrent_accept_decline_has_one_terminal_state_and_one_membership(pending):
    _, db, meeting = pending
    did = meeting["discussion_id"]
    barrier = Barrier(2)

    def respond(accept):
        conn = db.connect()
        try:
            barrier.wait(timeout=3)
            return db.respond_summon(conn, did, "worker", accept=accept)["status"]
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(respond, [True, False]))
    assert results[0] == results[1]
    conn = db.connect()
    try:
        assert ("worker" in db.get_active_participant_names(conn, did)) == (results[0] == "accepted")
        events = db.list_summon_events(conn, dispatch_id=meeting["dispatch"]["id"])
        assert len([e for e in events if e["event"] in {"summon.accepted", "summon.declined"}]) == 1
    finally:
        conn.close()


@pytest.mark.parametrize("duration", [float("inf"), float("nan"), -1, 31])
def test_turn_wait_rejects_unbounded_values(pending, duration):
    core, db, meeting = pending
    result = handle_tool_call(
        core,
        db,
        "roundtable_wait_for_turn",
        {
            "discussion_id": meeting["discussion_id"],
            "agent_id": "worker",
            "wait_seconds": duration,
        },
    )
    assert "error" in result
