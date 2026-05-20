"""Tests for RoundtableCore — the business logic layer.

Replaces tests/tools/test_roundtable_tools.py — same 17 test cases,
now testing via RoundtableCore instead of raw handler functions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB


@pytest.fixture
def core(tmp_path):
    """Isolated RoundtableCore with a fresh database."""
    db = RoundtableDB(tmp_path / "roundtable.db")
    return RoundtableCore(db)


def _make_participants():
    return [
        {"profile": "alice", "role": "Engineer", "perspective": "Technical", "display_name": "Alice"},
        {"profile": "bob", "role": "Designer", "perspective": "UX", "display_name": "Bob"},
    ]


# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------


def test_core_module_imports():
    """Verify the roundtable core module imports cleanly."""
    from roundtable import core
    assert core is not None


def test_schema_constants_available():
    """Verify all 9 tool schemas are accessible from the Hermes adapter."""
    from roundtable.adapters.hermes import (
        ROUNDTABLE_INIT_SCHEMA,
        ROUNDTABLE_SPEAK_SCHEMA,
        ROUNDTABLE_READ_SCHEMA,
        ROUNDTABLE_STATUS_SCHEMA,
        ROUNDTABLE_SUMMARIZE_SCHEMA,
        ROUNDTABLE_END_SCHEMA,
        ROUNDTABLE_LIST_SCHEMA,
        ROUNDTABLE_ADVANCE_SCHEMA,
        ROUNDTABLE_NOTIFY_SCHEMA,
    )
    schemas = [
        ROUNDTABLE_INIT_SCHEMA, ROUNDTABLE_SPEAK_SCHEMA,
        ROUNDTABLE_READ_SCHEMA, ROUNDTABLE_STATUS_SCHEMA,
        ROUNDTABLE_SUMMARIZE_SCHEMA, ROUNDTABLE_END_SCHEMA,
        ROUNDTABLE_LIST_SCHEMA, ROUNDTABLE_ADVANCE_SCHEMA,
        ROUNDTABLE_NOTIFY_SCHEMA,
    ]
    for s in schemas:
        assert "name" in s
        assert "description" in s
        assert "parameters" in s
        assert s["parameters"]["type"] == "object"


# ---------------------------------------------------------------------------
# create_discussion
# ---------------------------------------------------------------------------


def test_create_discussion_success(core):
    result = core.create_discussion(
        topic="Test topic",
        participants=_make_participants(),
        context="Some context",
        max_rounds=3,
    )
    assert result["ok"] is True
    assert result["discussion_id"].startswith("rt_")
    assert result["topic"] == "Test topic"
    assert result["participants"] == ["alice", "bob"]
    assert result["max_rounds"] == 3


def test_create_discussion_missing_topic(core):
    with pytest.raises(ValueError, match="topic"):
        core.create_discussion(topic="", participants=_make_participants())


def test_create_discussion_too_few_participants(core):
    with pytest.raises(ValueError, match="2 participants"):
        core.create_discussion(topic="Test", participants=[{"profile": "alice"}])


# ---------------------------------------------------------------------------
# speak
# ---------------------------------------------------------------------------


def test_speak_success(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    result = core.speak(disc_id, "alice", "Hello!")
    assert result["ok"] is True
    assert result["speech_id"] > 0
    assert result["round"] == 0
    assert result["participant"] == "alice"


def test_speak_unknown_participant(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    with pytest.raises(Exception, match="not an active member"):
        core.speak(disc_id, "eve", "Sneaky!")


def test_speak_missing_content(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    with pytest.raises(ValueError, match="content"):
        core.speak(disc_id, "alice", "")


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_success(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    core.speak(disc_id, "alice", "Hi")
    core.speak(disc_id, "bob", "Hello")

    result = core.read(disc_id)
    assert result["ok"] is True
    assert result["speech_count"] == 2
    assert len(result["speeches"]) == 2
    assert "formatted_history" in result


def test_read_with_since_round(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    # Round 0
    core.speak(disc_id, "alice", "r0s1")
    core.speak(disc_id, "bob", "r0s2")
    # Round 1
    core.speak(disc_id, "alice", "r1s1")

    result = core.read(disc_id, since_round=1)
    assert result["speech_count"] == 1
    assert result["speeches"][0]["content"] == "r1s1"


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    result = core.status(disc_id)
    assert result["ok"] is True
    assert result["status"] == "active"
    assert result["current_round"] == 0
    assert result["speech_count"] == 0


# ---------------------------------------------------------------------------
# end_discussion
# ---------------------------------------------------------------------------


def test_end_conclude(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    result = core.end_discussion(disc_id)
    assert result["ok"] is True
    assert result["action"] == "concluded"


def test_end_force_cancel(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    result = core.end_discussion(disc_id, force=True)
    assert result["ok"] is True
    assert result["action"] == "cancelled"


# ---------------------------------------------------------------------------
# list_discussions
# ---------------------------------------------------------------------------


def test_list(core):
    for i in range(3):
        core.create_discussion(topic=f"Topic {i}", participants=_make_participants())

    result = core.list_discussions()
    assert result["ok"] is True
    assert result["count"] == 3


def test_list_filter_status(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]
    core.end_discussion(disc_id)
    core.create_discussion(topic="Test2", participants=_make_participants())

    result = core.list_discussions(status="active")
    assert result["count"] == 1

    result = core.list_discussions(status="concluded")
    assert result["count"] == 1


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------


def test_summarize(core):
    disc = core.create_discussion(
        topic="DB Selection",
        participants=_make_participants(),
        context="We need a new database",
    )
    disc_id = disc["discussion_id"]

    core.speak(disc_id, "alice", "PostgreSQL")
    core.speak(disc_id, "bob", "MySQL")

    result = core.summarize(disc_id)
    assert result["ok"] is True
    assert result["topic"] == "DB Selection"
    assert result["speech_count"] == 2
    assert "rounds" in result
    assert "participants" in result
    assert "consensus_points" in result
    assert "formatted_history" in result
    assert "structured_summary" in result
    assert isinstance(result["structured_summary"], str)
    assert len(result["structured_summary"]) > 0


# ---------------------------------------------------------------------------
# advance
# ---------------------------------------------------------------------------


def test_advance_round(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    # Round 0: speak
    core.speak(disc_id, "alice", "r0s1")
    core.speak(disc_id, "bob", "r0s2")

    # Explicitly advance to round 2 (skip round 1)
    result = core.advance(disc_id)
    assert result["ok"] is True
    assert result["new_round"] == 2
    assert result["discussion_complete"] is False

    # Verify status shows round 2
    status = core.status(disc_id)
    assert status["current_round"] == 2


def test_advance_exceeds_max_rounds(core):
    disc = core.create_discussion(
        topic="Test", participants=_make_participants(), max_rounds=2
    )
    disc_id = disc["discussion_id"]

    # Advance past max
    core.advance(disc_id)  # round 1
    core.advance(disc_id)  # round 2
    result = core.advance(disc_id)  # round 3 > max_rounds=2
    assert result["ok"] is True
    assert result["discussion_complete"] is True

    # Discussion should be concluded
    status = core.status(disc_id)
    assert status["status"] == "concluded"


def test_round_tracking_multi_round(core):
    """Verify that speeches are correctly assigned to rounds across multiple rounds."""
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    # Round 0
    r1 = core.speak(disc_id, "alice", "r0 alice")
    assert r1["round"] == 0
    r2 = core.speak(disc_id, "bob", "r0 bob")
    assert r2["round"] == 0
    assert r2["round_complete"] is True

    # Round 1 (auto-advanced)
    r3 = core.speak(disc_id, "alice", "r1 alice")
    assert r3["round"] == 1
    r4 = core.speak(disc_id, "bob", "r1 bob")
    assert r4["round"] == 1
    assert r4["round_complete"] is True

    # Verify via read
    result = core.read(disc_id, since_round=1)
    assert result["speech_count"] == 2
    assert all(s["round"] == 1 for s in result["speeches"])


# ---------------------------------------------------------------------------
# convergence
# ---------------------------------------------------------------------------


def test_calculate_convergence(core):
    disc = core.create_discussion(topic="Test", participants=_make_participants())
    disc_id = disc["discussion_id"]

    result = core.calculate_convergence(disc_id, 0)
    assert result["ok"] is True
    assert result["convergence_score"] is None  # no findings yet


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------


def test_create_discussion_with_notifications(core):
    """Creating a discussion with notifications config stores it."""
    sent = []
    core.set_send_fn(lambda p, c, m: sent.append((p, c, m)))

    notif_config = {
        "enabled": True,
        "channels": [{"platform": "feishu", "chat_id": "oc_test123"}],
        "events": ["speech", "round_end", "concluded"],
    }
    result = core.create_discussion(
        topic="Notif Test",
        participants=_make_participants(),
        notifications=notif_config,
    )
    assert result["ok"] is True
    disc_id = result["discussion_id"]

    # Verify notifications persisted
    status = core.status(disc_id)
    assert status["ok"] is True

    # Speak and verify notification sent
    core.speak(disc_id, "alice", "Hello from Alice")
    assert len(sent) == 1
    assert sent[0][0] == "feishu"
    assert sent[0][1] == "oc_test123"
    assert "Alice" in sent[0][2]


def test_create_discussion_without_notifications(core):
    """Without notifications config, no notifications are sent."""
    sent = []
    core.set_send_fn(lambda p, c, m: sent.append((p, c, m)))

    result = core.create_discussion(
        topic="No Notif",
        participants=_make_participants(),
    )
    disc_id = result["discussion_id"]
    core.speak(disc_id, "alice", "Hello")
    assert len(sent) == 0


def test_notification_failure_does_not_block(core):
    """Notification send failures must not raise or block the discussion."""
    def bad_send(p, c, m):
        raise RuntimeError("Network error")

    core.set_send_fn(bad_send)
    notif_config = {
        "enabled": True,
        "channels": [{"platform": "feishu", "chat_id": "oc_test"}],
    }
    result = core.create_discussion(
        topic="Fail Test",
        participants=_make_participants(),
        notifications=notif_config,
    )
    disc_id = result["discussion_id"]

    # Should not raise despite bad send_fn
    r = core.speak(disc_id, "alice", "Still works")
    assert r["ok"] is True


def test_notification_events_filter(core):
    """Only subscribed events should trigger notifications."""
    sent = []
    core.set_send_fn(lambda p, c, m: sent.append(m))

    notif_config = {
        "enabled": True,
        "channels": [{"platform": "feishu", "chat_id": "oc_test"}],
        "events": ["round_end"],  # Only round_end
    }
    result = core.create_discussion(
        topic="Filter Test",
        participants=_make_participants(),
        notifications=notif_config,
    )
    disc_id = result["discussion_id"]

    # Round 0 — speech should NOT trigger (not subscribed)
    core.speak(disc_id, "alice", "Hello")
    assert len(sent) == 0

    # Complete round 0 — round_end should NOT trigger for round 0 (coordinator round)
    core.speak(disc_id, "bob", "World")
    assert len(sent) == 0  # round 0 doesn't fire round_end

    # Round 1 — speech should NOT trigger
    core.speak(disc_id, "alice", "R1 Alice")
    assert len(sent) == 0

    # Complete round 1 — round_end SHOULD trigger
    core.speak(disc_id, "bob", "R1 Bob")
    assert len(sent) == 1
    assert "第1轮讨论结束" in sent[0]


def test_manual_notify(core):
    """roundtable_notify should send a manual notification."""
    sent = []
    core.set_send_fn(lambda p, c, m: sent.append(m))

    notif_config = {
        "enabled": True,
        "channels": [{"platform": "feishu", "chat_id": "oc_test"}],
    }
    result = core.create_discussion(
        topic="Manual Notif",
        participants=_make_participants(),
        notifications=notif_config,
    )
    disc_id = result["discussion_id"]

    # Manual notify
    r = core.notify(disc_id, "round_start", round_num=1)
    assert r["ok"] is True
    assert len(sent) == 1
    assert "第1轮讨论开始" in sent[0]
