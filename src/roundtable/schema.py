from __future__ import annotations

import sqlite3
from collections.abc import Callable

VALID_DISCUSSION_STATUSES = {"active", "concluded", "cancelled"}
VALID_SPEECH_ORDERS = {"fixed", "random", "priority", "free"}
VALID_FINDING_TYPES = {"consensus", "disagreement", "new_point"}

INITIATION_ROUND = 0

SCHEMA_SQL = """\
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS discussions (
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


_MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migrate_v0_to_v1,
]

CURRENT_SCHEMA_VERSION = len(_MIGRATIONS)


def migrate_db(conn: sqlite3.Connection) -> None:
    """Apply ordered schema migrations using PRAGMA user_version."""
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for target_version in range(current, CURRENT_SCHEMA_VERSION):
        _MIGRATIONS[target_version](conn)
        conn.execute(f"PRAGMA user_version = {target_version + 1}")
