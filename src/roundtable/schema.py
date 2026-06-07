from __future__ import annotations

import sqlite3
from collections.abc import Callable

VALID_DISCUSSION_STATUSES = {"assembling", "active", "concluded", "cancelled"}
VALID_SPEECH_ORDERS = {"fixed", "random", "priority", "free"}
VALID_FINDING_TYPES = {"consensus", "disagreement", "new_point"}
VALID_DISPATCH_MODES = {"managed", "federated"}
VALID_DISPATCH_STATUSES = {"pending", "active", "completed", "cancelled", "timeout"}
VALID_SUMMON_STATUSES = {"pending", "delivered", "accepted", "declined", "timeout", "failed"}

INITIATION_ROUND = 0

SCHEMA_SQL = """\
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS discussions (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    context TEXT,
    status TEXT DEFAULT 'active'
        CHECK(status IN ('assembling', 'active', 'concluded', 'cancelled')),
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

CREATE TABLE IF NOT EXISTS participants (
    discussion_id TEXT NOT NULL,
    participant TEXT NOT NULL,
    role TEXT,
    perspective TEXT,
    display_name TEXT,
    joined_at INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    PRIMARY KEY (discussion_id, participant),
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS speeches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    participant TEXT NOT NULL,
    content TEXT NOT NULL,
    reply_to INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE,
    FOREIGN KEY (reply_to) REFERENCES speeches(id)
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL,
    type TEXT NOT NULL
        CHECK(type IN ('consensus', 'disagreement', 'new_point')),
    content TEXT NOT NULL,
    round INTEGER NOT NULL,
    related_speeches TEXT,
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS convergence_history (
    discussion_id TEXT NOT NULL,
    round INTEGER NOT NULL,
    score REAL NOT NULL,
    consensus_count INTEGER,
    disagreement_count INTEGER,
    new_point_count INTEGER,
    PRIMARY KEY (discussion_id, round),
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_speeches_discussion
    ON speeches(discussion_id, round);
CREATE INDEX IF NOT EXISTS idx_speeches_participant
    ON speeches(discussion_id, participant);
CREATE INDEX IF NOT EXISTS idx_findings_discussion
    ON findings(discussion_id, type);

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    display_name TEXT,
    persona TEXT,
    capabilities TEXT,
    transport TEXT DEFAULT 'stdio',
    endpoint TEXT,
    last_seen INTEGER NOT NULL,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS agent_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    type TEXT NOT NULL,
    discussion_id TEXT,
    payload TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    read_at INTEGER,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_inbox_unread
    ON agent_inbox(agent_id, read_at);
CREATE INDEX IF NOT EXISTS idx_inbox_discussion
    ON agent_inbox(discussion_id, read_at);

CREATE TABLE IF NOT EXISTS invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    role TEXT,
    perspective TEXT,
    status TEXT DEFAULT 'pending',
    invited_by TEXT NOT NULL,
    invited_at INTEGER NOT NULL,
    responded_at INTEGER,
    UNIQUE(discussion_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_invitations_agent
    ON invitations(agent_id, status);

CREATE TABLE IF NOT EXISTS dispatches (
    id TEXT PRIMARY KEY,
    discussion_id TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'federated'
        CHECK(mode IN ('managed', 'federated')),
    coordinator_agent_id TEXT NOT NULL,
    start_policy TEXT DEFAULT 'quorum',
    min_accepts INTEGER DEFAULT 1,
    timeout_seconds INTEGER DEFAULT 60,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'active', 'completed', 'cancelled', 'timeout')),
    idempotency_key TEXT UNIQUE,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    metadata TEXT,
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dispatches_discussion
    ON dispatches(discussion_id, status);
CREATE INDEX IF NOT EXISTS idx_dispatches_coordinator
    ON dispatches(coordinator_agent_id);

CREATE TABLE IF NOT EXISTS summons (
    id TEXT PRIMARY KEY,
    dispatch_id TEXT,
    discussion_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    role TEXT,
    perspective TEXT,
    required_skill TEXT,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'delivered', 'accepted', 'declined', 'timeout', 'failed')),
    invited_by TEXT NOT NULL,
    transport TEXT,
    endpoint TEXT,
    delivery_result TEXT,
    idempotency_key TEXT UNIQUE,
    created_at INTEGER NOT NULL,
    delivered_at INTEGER,
    responded_at INTEGER,
    expires_at INTEGER,
    metadata TEXT,
    FOREIGN KEY (dispatch_id) REFERENCES dispatches(id) ON DELETE CASCADE,
    FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE,
    UNIQUE(discussion_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_summons_agent
    ON summons(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_summons_dispatch
    ON summons(dispatch_id, status);
CREATE INDEX IF NOT EXISTS idx_summons_timeout
    ON summons(status, expires_at);

CREATE TABLE IF NOT EXISTS summon_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summon_id TEXT,
    dispatch_id TEXT,
    agent_id TEXT,
    event TEXT NOT NULL,
    payload TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (summon_id) REFERENCES summons(id) ON DELETE CASCADE,
    FOREIGN KEY (dispatch_id) REFERENCES dispatches(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_summon_events_summon
    ON summon_events(summon_id, created_at);
"""


# Ordered list of migrations. Each entry upgrades the DB from version N to N+1.
# Index in this list == target version. To add a new migration, append a function.
def _migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    """Add notifications column to discussions if missing.

    Predates user_version tracking; uses defensive table_info check so that
    DBs created before user_version was wired in still upgrade cleanly.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(discussions)").fetchall()}
    if "notifications" not in cols:
        conn.execute("ALTER TABLE discussions ADD COLUMN notifications TEXT")


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add MCP multi-agent tables: agents, agent_inbox, invitations."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            display_name TEXT,
            persona TEXT,
            capabilities TEXT,
            transport TEXT DEFAULT 'stdio',
            endpoint TEXT,
            last_seen INTEGER NOT NULL,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_inbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            type TEXT NOT NULL,
            discussion_id TEXT,
            payload TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            read_at INTEGER,
            FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_inbox_unread
            ON agent_inbox(agent_id, read_at);
        CREATE INDEX IF NOT EXISTS idx_inbox_discussion
            ON agent_inbox(discussion_id, read_at);

        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            role TEXT,
            perspective TEXT,
            status TEXT DEFAULT 'pending',
            invited_by TEXT NOT NULL,
            invited_at INTEGER NOT NULL,
            responded_at INTEGER,
            UNIQUE(discussion_id, agent_id)
        );
        CREATE INDEX IF NOT EXISTS idx_invitations_agent
            ON invitations(agent_id, status);
    """)


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add dispatch/summon tables and allow discussions to assemble before start."""
    table_row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'discussions'").fetchone()
    needs_rebuild = table_row and "assembling" not in (table_row[0] or "")
    if needs_rebuild:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS discussions_new (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    context TEXT,
                    status TEXT DEFAULT 'active'
                        CHECK(status IN ('assembling', 'active', 'concluded', 'cancelled')),
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
                INSERT OR IGNORE INTO discussions_new
                    (id, topic, context, status, max_rounds, current_round,
                     speech_order, created_by, created_at, concluded_at,
                     conclusion, convergence_score, output_path, notifications)
                SELECT id, topic, context, status, max_rounds, current_round,
                       speech_order, created_by, created_at, concluded_at,
                       conclusion, convergence_score, output_path, notifications
                FROM discussions;
                DROP TABLE discussions;
                ALTER TABLE discussions_new RENAME TO discussions;
            """)
        finally:
            conn.execute(f"PRAGMA foreign_keys={'ON' if fk else 'OFF'}")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dispatches (
            id TEXT PRIMARY KEY,
            discussion_id TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'federated'
                CHECK(mode IN ('managed', 'federated')),
            coordinator_agent_id TEXT NOT NULL,
            start_policy TEXT DEFAULT 'quorum',
            min_accepts INTEGER DEFAULT 1,
            timeout_seconds INTEGER DEFAULT 60,
            status TEXT DEFAULT 'pending'
                CHECK(status IN ('pending', 'active', 'completed', 'cancelled', 'timeout')),
            idempotency_key TEXT UNIQUE,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            metadata TEXT,
            FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_dispatches_discussion
            ON dispatches(discussion_id, status);
        CREATE INDEX IF NOT EXISTS idx_dispatches_coordinator
            ON dispatches(coordinator_agent_id);

        CREATE TABLE IF NOT EXISTS summons (
            id TEXT PRIMARY KEY,
            dispatch_id TEXT,
            discussion_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            role TEXT,
            perspective TEXT,
            required_skill TEXT,
            status TEXT DEFAULT 'pending'
                CHECK(status IN ('pending', 'delivered', 'accepted', 'declined', 'timeout', 'failed')),
            invited_by TEXT NOT NULL,
            transport TEXT,
            endpoint TEXT,
            delivery_result TEXT,
            idempotency_key TEXT UNIQUE,
            created_at INTEGER NOT NULL,
            delivered_at INTEGER,
            responded_at INTEGER,
            expires_at INTEGER,
            metadata TEXT,
            FOREIGN KEY (dispatch_id) REFERENCES dispatches(id) ON DELETE CASCADE,
            FOREIGN KEY (discussion_id) REFERENCES discussions(id) ON DELETE CASCADE,
            UNIQUE(discussion_id, agent_id)
        );
        CREATE INDEX IF NOT EXISTS idx_summons_agent
            ON summons(agent_id, status);
        CREATE INDEX IF NOT EXISTS idx_summons_dispatch
            ON summons(dispatch_id, status);
        CREATE INDEX IF NOT EXISTS idx_summons_timeout
            ON summons(status, expires_at);

        CREATE TABLE IF NOT EXISTS summon_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summon_id TEXT,
            dispatch_id TEXT,
            agent_id TEXT,
            event TEXT NOT NULL,
            payload TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (summon_id) REFERENCES summons(id) ON DELETE CASCADE,
            FOREIGN KEY (dispatch_id) REFERENCES dispatches(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_summon_events_summon
            ON summon_events(summon_id, created_at);
    """)


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Add query indexes for dispatch filtering, summon expiry, and inbox sync."""
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_dispatches_coordinator
            ON dispatches(coordinator_agent_id);
        CREATE INDEX IF NOT EXISTS idx_summons_timeout
            ON summons(status, expires_at);
        CREATE INDEX IF NOT EXISTS idx_inbox_discussion
            ON agent_inbox(discussion_id, read_at);
    """)


_MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migrate_v0_to_v1,
    _migrate_v1_to_v2,
    _migrate_v2_to_v3,
    _migrate_v3_to_v4,
]

CURRENT_SCHEMA_VERSION = len(_MIGRATIONS)


def migrate_db(conn: sqlite3.Connection) -> None:
    """Apply ordered schema migrations using PRAGMA user_version."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for target_version in range(current, CURRENT_SCHEMA_VERSION):
        _MIGRATIONS[target_version](conn)
        conn.execute(f"PRAGMA user_version = {target_version + 1}")
