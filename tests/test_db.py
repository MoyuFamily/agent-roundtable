"""Tests for the Roundtable DB layer (roundtable.db.RoundtableDB).

Replaces tests/hermes_cli/test_roundtable_db.py — same 27 test cases,
now testing the independent library.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from roundtable.db import RoundtableDB
from roundtable.schema import CURRENT_SCHEMA_VERSION, migrate_db


@pytest.fixture
def rt_db(tmp_path):
    """Isolated RoundtableDB with a fresh database."""
    db_path = tmp_path / "roundtable.db"
    return RoundtableDB(db_path)


@pytest.fixture
def db_conn(rt_db):
    """A connected roundtable DB."""
    conn = rt_db.connect()
    yield conn
    conn.close()


PARTICIPANTS = [
    {"profile": "alice", "role": "Engineer", "perspective": "Technical", "display_name": "Alice"},
    {"profile": "bob", "role": "Designer", "perspective": "UX", "display_name": "Bob"},
    {"profile": "carol", "role": "PM", "perspective": "Business", "display_name": "Carol"},
]


# ---------------------------------------------------------------------------
# Schema / init
# ---------------------------------------------------------------------------


def test_connect_creates_tables(db_conn):
    rows = db_conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    names = {r["name"] for r in rows}
    assert {
        "discussions",
        "participants",
        "speeches",
        "findings",
        "convergence_history",
        "agents",
        "agent_inbox",
        "invitations",
        "dispatches",
        "summons",
        "summon_events",
    } <= names


def test_connect_creates_v4_indexes_and_sets_user_version(db_conn):
    rows = db_conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    indexes = {r["name"] for r in rows}
    assert {
        "idx_dispatches_coordinator",
        "idx_summons_timeout",
        "idx_inbox_discussion",
    } <= indexes
    assert db_conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_v2_migration_allows_assembling_discussions_and_creates_summon_tables(tmp_path):
    db_path = tmp_path / "v2.db"
    raw = sqlite3.connect(db_path)
    try:
        raw.executescript("""
            CREATE TABLE discussions (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                context TEXT,
                status TEXT DEFAULT 'active'
                    CHECK(status IN ('active', 'concluded', 'cancelled')),
                max_rounds INTEGER DEFAULT 5,
                current_round INTEGER DEFAULT 0,
                speech_order TEXT DEFAULT 'fixed'
                    CHECK(speech_order IN ('fixed', 'random', 'priority', 'free')),
                created_by TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                concluded_at INTEGER,
                conclusion TEXT,
                convergence_score REAL,
                output_path TEXT,
                notifications TEXT
            );
            INSERT INTO discussions
                (id, topic, status, max_rounds, current_round, speech_order, created_by, created_at)
            VALUES ('rt_old', 'Old discussion', 'active', 3, 0, 'fixed', 'coord', 1);
            PRAGMA user_version = 2;
        """)
    finally:
        raw.close()

    migrated = RoundtableDB(db_path)
    conn = migrated.connect()
    try:
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'discussions'"
        ).fetchone()[0]
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        assert "assembling" in table_sql
        assert {"dispatches", "summons", "summon_events"} <= names
        assert migrated.get_discussion(conn, "rt_old").topic == "Old discussion"

        disc = migrated.create_discussion(conn, topic="Assembling", participants=[], status="assembling")
        assert disc.status == "assembling"
    finally:
        conn.close()


def test_v3_to_v4_migration_adds_query_indexes(tmp_path):
    db_path = tmp_path / "v3.db"
    raw = sqlite3.connect(db_path)
    try:
        raw.executescript("""
            CREATE TABLE dispatches (
                id TEXT PRIMARY KEY,
                coordinator_agent_id TEXT
            );
            CREATE TABLE summons (
                id TEXT PRIMARY KEY,
                status TEXT,
                expires_at INTEGER
            );
            CREATE TABLE agent_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discussion_id TEXT,
                read_at INTEGER
            );
            PRAGMA user_version = 3;
        """)

        migrate_db(raw)

        indexes = {
            row[0]
            for row in raw.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        assert {
            "idx_dispatches_coordinator",
            "idx_summons_timeout",
            "idx_inbox_discussion",
        } <= indexes
        assert raw.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
    finally:
        raw.close()


def test_connect_is_idempotent(rt_db, db_conn):
    rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    # Reconnect (new connection, same DB file)
    conn2 = rt_db.connect()
    try:
        discs = rt_db.list_discussions(conn2)
        assert len(discs) == 1
    finally:
        conn2.close()


# ---------------------------------------------------------------------------
# Discussion CRUD
# ---------------------------------------------------------------------------


def test_create_discussion(rt_db, db_conn):
    disc = rt_db.create_discussion(
        db_conn,
        topic="Database selection",
        participants=PARTICIPANTS,
        context="We need a new DB",
        max_rounds=3,
        created_by="coordinator",
    )
    assert disc.id.startswith("rt_")
    assert len(disc.id) == 11  # rt_ + 8 hex
    assert disc.topic == "Database selection"
    assert disc.context == "We need a new DB"
    assert disc.status == "active"
    assert disc.max_rounds == 3
    assert disc.current_round == 0
    assert disc.speech_order == "fixed"


def test_create_discussion_registers_participants(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    parts = rt_db.get_participants(db_conn, disc.id)
    assert len(parts) == 3
    assert parts[0].participant == "alice"
    assert parts[0].role == "Engineer"
    assert parts[0].display_name == "Alice"
    assert parts[0].is_active is True


def test_create_discussion_validates_speech_order(rt_db, db_conn):
    with pytest.raises(ValueError, match="Invalid speech_order"):
        rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS, speech_order="invalid")


def test_create_discussion_requires_participants(rt_db, db_conn):
    with pytest.raises(ValueError, match="At least one participant"):
        rt_db.create_discussion(db_conn, topic="test", participants=[])


def test_create_discussion_rejects_duplicate_participants(rt_db, db_conn):
    participants = [
        {"profile": "alice", "role": "Engineer"},
        {"profile": "alice", "role": "Designer"},
    ]
    with pytest.raises(ValueError, match="Duplicate participant"):
        rt_db.create_discussion(db_conn, topic="test", participants=participants)


def test_create_discussion_validates_max_rounds(rt_db, db_conn):
    with pytest.raises(ValueError, match="max_rounds"):
        rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS, max_rounds=0)


def test_get_discussion(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched is not None
    assert fetched.id == disc.id
    assert fetched.topic == "test"


def test_get_discussion_not_found(rt_db, db_conn):
    assert rt_db.get_discussion(db_conn, "rt_nonexistent") is None


def test_list_discussions(rt_db, db_conn):
    for i in range(3):
        rt_db.create_discussion(db_conn, topic=f"topic {i}", participants=PARTICIPANTS)
    discs = rt_db.list_discussions(db_conn)
    assert len(discs) == 3


def test_list_discussions_filter_status(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.create_discussion(db_conn, topic="test2", participants=PARTICIPANTS)
    rt_db.conclude_discussion(db_conn, disc.id)

    active = rt_db.list_discussions(db_conn, status="active")
    concluded = rt_db.list_discussions(db_conn, status="concluded")
    assert len(active) == 1
    assert len(concluded) == 1


def test_conclude_discussion(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    ok = rt_db.conclude_discussion(db_conn, disc.id, conclusion="We chose PostgreSQL", convergence_score=0.9)
    assert ok is True
    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched.status == "concluded"
    assert fetched.conclusion == "We chose PostgreSQL"
    assert fetched.convergence_score == 0.9
    assert fetched.concluded_at is not None


def test_conclude_already_concluded(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.conclude_discussion(db_conn, disc.id)
    ok = rt_db.conclude_discussion(db_conn, disc.id)
    assert ok is False


def test_cancel_discussion(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    ok = rt_db.cancel_discussion(db_conn, disc.id)
    assert ok is True
    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched.status == "cancelled"


def test_assembling_discussion_can_start_without_participants(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="assembling", participants=[], status="assembling")
    assert disc.status == "assembling"
    assert rt_db.get_participants(db_conn, disc.id) == []

    assert rt_db.activate_discussion(db_conn, disc.id) is True
    assert rt_db.get_discussion(db_conn, disc.id).status == "active"


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


def test_get_active_participant_names(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    names = rt_db.get_active_participant_names(db_conn, disc.id)
    assert names == ["alice", "bob", "carol"]


def test_add_participant_idempotent(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    assert rt_db.add_participant(db_conn, disc.id, "dave", role="Observer") is True
    assert rt_db.add_participant(db_conn, disc.id, "dave", role="Observer") is False
    assert "dave" in rt_db.get_active_participant_names(db_conn, disc.id)


# ---------------------------------------------------------------------------
# Agent registry / dispatch / summons
# ---------------------------------------------------------------------------


def test_agent_metadata_heartbeat_and_filters(rt_db, db_conn):
    rt_db.upsert_agent(
        db_conn,
        "agent-1",
        "codex",
        metadata={
            "skills": ["agent-roundtable"],
            "availability": "idle",
            "accept_policy": "auto",
            "_bridge_auth_token": "secret-token",
        },
    )
    rt_db.upsert_agent(db_conn, "agent-2", "cursor", metadata={"skills": ["other"], "availability": "busy"})

    filtered = rt_db.list_agents(
        db_conn,
        required_skill="agent-roundtable",
        availability="idle",
        online_only=True,
    )
    assert [agent["agent_id"] for agent in filtered] == ["agent-1"]

    heartbeat = rt_db.heartbeat_agent(db_conn, "agent-1", availability="busy")
    assert heartbeat["metadata"]["availability"] == "busy"
    assert "_bridge_auth_token" not in heartbeat["metadata"]
    assert rt_db.get_agent(db_conn, "agent-1")["availability"] == "busy"
    assert "_bridge_auth_token" not in rt_db.get_agent(db_conn, "agent-1")["metadata"]
    assert rt_db.get_agent(db_conn, "agent-1", include_private=True)["metadata"]["_bridge_auth_token"] == "secret-token"


def test_summon_acceptance_activates_dispatch(rt_db, db_conn):
    rt_db.upsert_agent(db_conn, "coord", "claude-code")
    rt_db.upsert_agent(
        db_conn,
        "agent-1",
        "codex",
        metadata={"skills": ["agent-roundtable"], "availability": "idle"},
    )
    disc = rt_db.create_discussion(db_conn, topic="summon", participants=[], status="assembling")
    dispatch = rt_db.create_dispatch(
        db_conn,
        disc.id,
        "coord",
        start_policy="quorum",
        min_accepts=1,
        timeout_seconds=60,
    )
    summon = rt_db.create_summon(
        db_conn,
        disc.id,
        "agent-1",
        "coord",
        dispatch_id=dispatch["id"],
        required_skill="agent-roundtable",
    )

    delivered = rt_db.mark_summon_delivered(db_conn, summon["id"], {"ok": True})
    assert delivered["status"] == "delivered"

    accepted = rt_db.respond_summon(db_conn, disc.id, "agent-1", accept=True)
    assert accepted["status"] == "accepted"
    assert "agent-1" in rt_db.get_active_participant_names(db_conn, disc.id)

    readiness = rt_db.apply_dispatch_readiness(db_conn, dispatch["id"])
    assert readiness["dispatch"]["status"] == "active"
    assert readiness["readiness"]["ready"] is True
    assert rt_db.get_discussion(db_conn, disc.id).status == "active"
    events = [event["event"] for event in rt_db.list_summon_events(db_conn, dispatch_id=dispatch["id"])]
    assert "summon.accepted" in events
    assert "dispatch.active" in events


def test_dispatch_times_out_when_quorum_missing(rt_db, db_conn):
    rt_db.upsert_agent(db_conn, "coord", "claude-code")
    rt_db.upsert_agent(db_conn, "agent-1", "codex", metadata={"skills": ["agent-roundtable"]})
    disc = rt_db.create_discussion(db_conn, topic="timeout", participants=[], status="assembling")
    dispatch = rt_db.create_dispatch(
        db_conn,
        disc.id,
        "coord",
        start_policy="quorum",
        min_accepts=1,
        timeout_seconds=0,
    )
    rt_db.create_summon(
        db_conn,
        disc.id,
        "agent-1",
        "coord",
        dispatch_id=dispatch["id"],
        expires_at=int(time.time()) - 1,
    )

    readiness = rt_db.apply_dispatch_readiness(db_conn, dispatch["id"])
    assert readiness["dispatch"]["status"] == "timeout"
    assert readiness["readiness"]["terminal_timeout"] is True
    assert rt_db.get_summons(db_conn, dispatch_id=dispatch["id"])[0]["status"] == "timeout"


def test_dispatch_idempotency_allows_explicit_terminal_retry(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="retry dispatch", participants=[], status="assembling")

    first = rt_db.create_dispatch(
        db_conn,
        disc.id,
        "coord",
        idempotency_key="retry-key",
    )
    duplicate = rt_db.create_dispatch(
        db_conn,
        disc.id,
        "coord",
        idempotency_key="retry-key",
    )
    assert duplicate["id"] == first["id"]

    rt_db.update_dispatch_status(db_conn, first["id"], "cancelled")
    terminal_duplicate = rt_db.create_dispatch(
        db_conn,
        disc.id,
        "coord",
        idempotency_key="retry-key",
    )
    assert terminal_duplicate["id"] == first["id"]

    retried = rt_db.create_dispatch(
        db_conn,
        disc.id,
        "coord",
        idempotency_key="retry-key",
        allow_terminal_retry=True,
    )

    assert retried["id"] != first["id"]
    assert retried["idempotency_key"] == "retry-key"
    released = rt_db.get_dispatch(db_conn, first["id"])
    assert released["idempotency_key"] == f"retry-key#released:{first['id']}"
    events = rt_db.list_summon_events(db_conn, dispatch_id=first["id"])
    assert "dispatch.idempotency_key.released" in [event["event"] for event in events]


def test_terminal_retry_reuses_declined_summon_without_duplicate_row(rt_db, db_conn):
    rt_db.upsert_agent(db_conn, "agent-1", "codex", metadata={"skills": ["agent-roundtable"]})
    disc = rt_db.create_discussion(db_conn, topic="retry summon", participants=[], status="assembling")
    first_dispatch = rt_db.create_dispatch(db_conn, disc.id, "coord")
    first = rt_db.create_summon(
        db_conn,
        disc.id,
        "agent-1",
        "coord",
        dispatch_id=first_dispatch["id"],
        required_skill="agent-roundtable",
        idempotency_key="summon-key",
    )
    declined = rt_db.respond_summon(db_conn, disc.id, "agent-1", accept=False)
    assert declined["status"] == "declined"

    retry_dispatch = rt_db.create_dispatch(db_conn, disc.id, "coord")
    retried = rt_db.create_summon(
        db_conn,
        disc.id,
        "agent-1",
        "coord",
        dispatch_id=retry_dispatch["id"],
        required_skill="agent-roundtable",
        idempotency_key="summon-key",
        allow_terminal_retry=True,
    )

    assert retried["id"] == first["id"]
    assert retried["status"] == "pending"
    assert retried["dispatch_id"] == retry_dispatch["id"]
    assert retried["idempotency_key"] == "summon-key"
    assert retried["responded_at"] is None
    assert len(rt_db.get_summons(db_conn, discussion_id=disc.id, agent_id="agent-1")) == 1
    events = rt_db.list_summon_events(db_conn, summon_id=first["id"])
    assert "summon.reused_for_retry" in [event["event"] for event in events]


def test_terminal_retry_does_not_reset_accepted_summon(rt_db, db_conn):
    rt_db.upsert_agent(db_conn, "agent-1", "codex", metadata={"skills": ["agent-roundtable"]})
    disc = rt_db.create_discussion(db_conn, topic="accepted summon", participants=[], status="assembling")
    first_dispatch = rt_db.create_dispatch(db_conn, disc.id, "coord")
    first = rt_db.create_summon(
        db_conn,
        disc.id,
        "agent-1",
        "coord",
        dispatch_id=first_dispatch["id"],
        required_skill="agent-roundtable",
    )
    accepted = rt_db.respond_summon(db_conn, disc.id, "agent-1", accept=True)
    assert accepted["status"] == "accepted"
    rt_db.update_dispatch_status(db_conn, first_dispatch["id"], "completed")

    retry_dispatch = rt_db.create_dispatch(db_conn, disc.id, "coord")
    retried = rt_db.create_summon(
        db_conn,
        disc.id,
        "agent-1",
        "coord",
        dispatch_id=retry_dispatch["id"],
        required_skill="agent-roundtable",
        allow_terminal_retry=True,
    )

    assert retried["id"] == first["id"]
    assert retried["status"] == "accepted"
    assert retried["dispatch_id"] == first_dispatch["id"]


# ---------------------------------------------------------------------------
# Speeches
# ---------------------------------------------------------------------------


def test_add_coordinator_speech_in_round_0(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    result = rt_db.add_speech(db_conn, disc.id, "coordinator", "Hello everyone!")
    speech = result["speech"]
    assert speech.id > 0
    assert speech.round == 0
    assert speech.participant == "coordinator"
    assert speech.content == "Hello everyone!"


def test_participant_cannot_speak_in_round_0(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    with pytest.raises(ValueError, match="Round 0"):
        rt_db.add_speech(db_conn, disc.id, "alice", "Hello everyone!")


def test_speech_round_advances_when_all_spoke(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)

    # Round 0: coordinator opening only
    rt_db.add_speech(db_conn, disc.id, "coordinator", "Opening")

    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched.current_round == 1

    # Round 1
    rt_db.add_speech(db_conn, disc.id, "alice", "Round 1 from Alice")
    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched.current_round == 1  # Still round 1

    rt_db.add_speech(db_conn, disc.id, "bob", "Round 1 from Bob")
    rt_db.add_speech(db_conn, disc.id, "carol", "Round 1 from Carol")
    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched.current_round == 2


def test_speech_auto_conclude_on_max_rounds(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS, max_rounds=1)

    # Round 0
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")

    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched.current_round == 1

    # Round 1 (max_rounds=1)
    rt_db.add_speech(db_conn, disc.id, "alice", "r1s1")
    rt_db.add_speech(db_conn, disc.id, "bob", "r1s2")
    rt_db.add_speech(db_conn, disc.id, "carol", "r1s3")

    fetched = rt_db.get_discussion(db_conn, disc.id)
    assert fetched.status == "concluded"


def test_speech_with_reply_to(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")
    r1 = rt_db.add_speech(db_conn, disc.id, "alice", "Original point")
    s1 = r1["speech"]
    r2 = rt_db.add_speech(db_conn, disc.id, "bob", "Responding", reply_to=s1.id)
    s2 = r2["speech"]
    assert s2.reply_to == s1.id


def test_fixed_order_rejects_out_of_turn_speech(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")

    with pytest.raises(ValueError, match="Next speaker: alice"):
        rt_db.add_speech(db_conn, disc.id, "bob", "jumping the queue")


def test_participant_cannot_speak_twice_in_same_round(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")
    rt_db.add_speech(db_conn, disc.id, "alice", "first point")

    with pytest.raises(ValueError, match="already spoken"):
        rt_db.add_speech(db_conn, disc.id, "alice", "second point")


def test_free_order_allows_any_unspoken_participant(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS, speech_order="free")
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")

    result = rt_db.add_speech(db_conn, disc.id, "carol", "free order")

    assert result["speech"].participant == "carol"


def test_speech_reply_to_invalid(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")
    with pytest.raises(ValueError, match="reply_to speech"):
        rt_db.add_speech(db_conn, disc.id, "alice", "test", reply_to=999)


def test_speech_on_concluded_discussion(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.conclude_discussion(db_conn, disc.id)
    with pytest.raises(ValueError, match="concluded"):
        rt_db.add_speech(db_conn, disc.id, "alice", "Too late")


def test_get_speeches(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")
    rt_db.add_speech(db_conn, disc.id, "alice", "s1")
    rt_db.add_speech(db_conn, disc.id, "bob", "s2")
    rt_db.add_speech(db_conn, disc.id, "carol", "s3")  # completes round 1
    rt_db.add_speech(db_conn, disc.id, "alice", "r2s1")

    all_speeches = rt_db.get_speeches(db_conn, disc.id)
    assert len(all_speeches) == 5

    round0 = rt_db.get_speeches(db_conn, disc.id, since_round=0)
    assert len(round0) == 5

    round1 = rt_db.get_speeches(db_conn, disc.id, since_round=1)
    assert len(round1) == 4

    alice_only = rt_db.get_speeches(db_conn, disc.id, participant="alice")
    assert len(alice_only) == 2


def test_get_speech_count(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.add_speech(db_conn, disc.id, "coordinator", "opening")
    rt_db.add_speech(db_conn, disc.id, "alice", "s1")
    rt_db.add_speech(db_conn, disc.id, "bob", "s2")
    assert rt_db.get_speech_count(db_conn, disc.id) == 3


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_add_finding(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    fid = rt_db.add_finding(db_conn, disc.id, "consensus", "We all agree on X", 1, [1, 2])
    assert fid > 0

    findings = rt_db.get_findings(db_conn, disc.id)
    assert len(findings) == 1
    assert findings[0].type == "consensus"
    assert findings[0].content == "We all agree on X"
    assert findings[0].related_speeches == [1, 2]


def test_add_finding_invalid_type(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    with pytest.raises(ValueError, match="Invalid finding type"):
        rt_db.add_finding(db_conn, disc.id, "invalid", "test", 1)


def test_get_findings_filter_type(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.add_finding(db_conn, disc.id, "consensus", "agree", 1)
    rt_db.add_finding(db_conn, disc.id, "disagreement", "disagree", 1)
    rt_db.add_finding(db_conn, disc.id, "new_point", "new idea", 1)

    consensus = rt_db.get_findings(db_conn, disc.id, finding_type="consensus")
    assert len(consensus) == 1
    all_findings = rt_db.get_findings(db_conn, disc.id)
    assert len(all_findings) == 3


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------


def test_record_and_get_convergence(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.record_convergence(db_conn, disc.id, 1, 0.67, 2, 1, 1)
    rt_db.record_convergence(db_conn, disc.id, 2, 0.85, 3, 0, 0)

    history = rt_db.get_convergence_history(db_conn, disc.id)
    assert len(history) == 2
    assert history[0].round == 1
    assert history[0].score == 0.67
    assert history[1].round == 2
    assert history[1].score == 0.85


def test_convergence_upsert(rt_db, db_conn):
    disc = rt_db.create_discussion(db_conn, topic="test", participants=PARTICIPANTS)
    rt_db.record_convergence(db_conn, disc.id, 1, 0.5, 1, 1, 0)
    rt_db.record_convergence(db_conn, disc.id, 1, 0.8, 2, 0, 0)  # replace

    history = rt_db.get_convergence_history(db_conn, disc.id)
    assert len(history) == 1
    assert history[0].score == 0.8
