"""SQLite database layer for Roundtable.

Framework-agnostic: uses only stdlib sqlite3 + dataclasses from models.
DB path resolution: ROUNDTABLE_DB env var > ~/.roundtable/roundtable.db
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from roundtable.exceptions import (
    DiscussionNotActiveError,
    DiscussionNotFoundError,
    InvalidFindingTypeError,
    InvalidParticipantError,
    InvalidReplyToError,
    InvalidSpeechOrderError,
)
from roundtable.models import (
    ConvergenceRecord,
    Discussion,
    Finding,
    Participant,
    Speech,
)
from roundtable.schema import (
    SCHEMA_SQL,
    VALID_DISCUSSION_STATUSES,
    VALID_DISPATCH_MODES,
    VALID_DISPATCH_STATUSES,
    VALID_FINDING_TYPES,
    VALID_SPEECH_ORDERS,
    VALID_SUMMON_STATUSES,
    migrate_db,
)

DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 90


# ---------------------------------------------------------------------------
# RoundtableDB — the database access layer
# ---------------------------------------------------------------------------


class RoundtableDB:
    """SQLite-backed storage for roundtable discussions.

    Args:
        db_path: Explicit path to the SQLite file.
            Falls back to ``ROUNDTABLE_DB`` env var,
            then ``~/.roundtable/roundtable.db``.
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path:
            self._path = Path(db_path)
        else:
            env = os.environ.get("ROUNDTABLE_DB")
            if env:
                self._path = Path(env)
            else:
                self._path = Path.home() / ".roundtable" / "roundtable.db"

    @property
    def db_path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        """Open (and initialize if needed) the roundtable DB.

        WAL mode + foreign keys on every connection. Schema DDL is idempotent
        (CREATE TABLE IF NOT EXISTS) so it's safe to run on every connect;
        migrations are version-gated via PRAGMA user_version.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path), isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_SQL)
        self._migrate(conn)
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Apply schema migrations for existing databases."""
        migrate_db(conn)

    # ------------------------------------------------------------------
    # Discussion CRUD
    # ------------------------------------------------------------------

    def create_discussion(
        self,
        conn: sqlite3.Connection,
        topic: str,
        participants: list[dict[str, Any]],
        *,
        context: str | None = None,
        max_rounds: int = 5,
        speech_order: str = "fixed",
        created_by: str = "unknown",
        output_path: str | None = None,
        notifications: dict[str, Any] | None = None,
        status: str = "active",
    ) -> Discussion:
        if status not in VALID_DISCUSSION_STATUSES:
            raise ValueError(f"Invalid discussion status: {status}")
        if speech_order not in VALID_SPEECH_ORDERS:
            raise InvalidSpeechOrderError(f"Invalid speech_order: {speech_order}")
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        if not participants and status != "assembling":
            raise ValueError("At least one participant is required")
        seen_profiles: set[str] = set()
        for p in participants:
            profile = p.get("profile", "").strip()
            if not profile:
                raise ValueError("Each participant must have a 'profile' field")
            if profile in seen_profiles:
                raise ValueError(f"Duplicate participant profile: {profile}")
            seen_profiles.add(profile)

        disc_id = f"rt_{secrets.token_hex(4)}"
        now = int(time.time())
        notif_json = json.dumps(notifications) if notifications else None

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """INSERT INTO discussions
                   (id, topic, context, status, max_rounds, current_round,
                    speech_order, created_by, created_at, output_path, notifications)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)""",
                (disc_id, topic, context, status, max_rounds, speech_order, created_by, now, output_path, notif_json),
            )
            for p in participants:
                profile = p.get("profile", "").strip()
                conn.execute(
                    """INSERT INTO participants
                       (discussion_id, participant, role, perspective,
                        display_name, joined_at, is_active)
                       VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (disc_id, profile, p.get("role"), p.get("perspective"), p.get("display_name"), now),
                )
            conn.execute("COMMIT")
        except Exception:  # rollback any failure (sqlite or pre-execute) and re-raise
            conn.execute("ROLLBACK")
            raise

        return Discussion(
            id=disc_id,
            topic=topic,
            context=context,
            status=status,
            max_rounds=max_rounds,
            current_round=0,
            speech_order=speech_order,
            created_by=created_by,
            created_at=now,
            concluded_at=None,
            conclusion=None,
            convergence_score=None,
            output_path=output_path,
            notifications=notifications,
        )

    def get_discussion(self, conn: sqlite3.Connection, discussion_id: str) -> Discussion | None:
        row = conn.execute("SELECT * FROM discussions WHERE id = ?", (discussion_id,)).fetchone()
        if not row:
            return None
        return self._row_to_discussion(row)

    def activate_discussion(self, conn: sqlite3.Connection, discussion_id: str) -> bool:
        """Move an assembling discussion into the active speaking lifecycle."""
        cur = conn.execute(
            "UPDATE discussions SET status = 'active' WHERE id = ? AND status = 'assembling'",
            (discussion_id,),
        )
        return cur.rowcount > 0

    def list_discussions(
        self,
        conn: sqlite3.Connection,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Discussion]:
        if status:
            rows = conn.execute(
                "SELECT * FROM discussions WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM discussions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_discussion(r) for r in rows]

    def conclude_discussion(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        *,
        conclusion: str | None = None,
        convergence_score: float | None = None,
    ) -> bool:
        now = int(time.time())
        cur = conn.execute(
            """UPDATE discussions
               SET status = 'concluded', concluded_at = ?,
                   conclusion = COALESCE(?, conclusion),
                   convergence_score = COALESCE(?, convergence_score)
               WHERE id = ? AND status = 'active'""",
            (now, conclusion, convergence_score, discussion_id),
        )
        return cur.rowcount > 0

    def cancel_discussion(self, conn: sqlite3.Connection, discussion_id: str) -> bool:
        now = int(time.time())
        cur = conn.execute(
            """UPDATE discussions
               SET status = 'cancelled', concluded_at = ?
               WHERE id = ? AND status IN ('assembling', 'active')""",
            (now, discussion_id),
        )
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------

    def add_participant(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        participant: str,
        *,
        role: str | None = None,
        perspective: str | None = None,
        display_name: str | None = None,
    ) -> bool:
        now = int(time.time())
        cur = conn.execute(
            """INSERT OR IGNORE INTO participants
               (discussion_id, participant, role, perspective, display_name, joined_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (discussion_id, participant, role, perspective, display_name or participant, now),
        )
        return cur.rowcount > 0

    def get_participants(self, conn: sqlite3.Connection, discussion_id: str) -> list[Participant]:
        rows = conn.execute(
            "SELECT * FROM participants WHERE discussion_id = ? ORDER BY joined_at",
            (discussion_id,),
        ).fetchall()
        return [
            Participant(
                discussion_id=r["discussion_id"],
                participant=r["participant"],
                role=r["role"],
                perspective=r["perspective"],
                display_name=r["display_name"],
                joined_at=r["joined_at"],
                is_active=bool(r["is_active"]),
            )
            for r in rows
        ]

    def get_active_participant_names(self, conn: sqlite3.Connection, discussion_id: str) -> list[str]:
        rows = conn.execute(
            """SELECT participant FROM participants
               WHERE discussion_id = ? AND is_active = 1
               ORDER BY joined_at""",
            (discussion_id,),
        ).fetchall()
        return [r["participant"] for r in rows]

    # ------------------------------------------------------------------
    # Speeches
    # ------------------------------------------------------------------

    def add_speech(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        participant: str,
        content: str,
        *,
        reply_to: int | None = None,
    ) -> dict[str, Any]:
        """Add a speech and return result with speech + round metadata.

        Round 0 is reserved for the coordinator opening statement. Once that
        opening is recorded, participant discussion starts at round 1.

        Returns dict with: speech (Speech), round_complete (bool),
        discussion_complete (bool), next_speaker (str|None).
        """
        now = int(time.time())
        speech_round = 0

        conn.execute("BEGIN IMMEDIATE")
        try:
            disc = self.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")
            if disc.status != "active":
                raise DiscussionNotActiveError(f"Discussion {discussion_id} is {disc.status}")

            current_round = disc.current_round
            speech_round = current_round

            active_names = self.get_active_participant_names(conn, discussion_id)
            is_coordinator = participant == "coordinator"
            if not is_coordinator and participant not in active_names:
                raise InvalidParticipantError(
                    f"Participant '{participant}' is not an active member of this discussion. "
                    f"Active: {', '.join(active_names)}"
                )

            if current_round == 0 and participant != "coordinator":
                raise InvalidParticipantError("Round 0 is reserved for the coordinator opening statement")

            if is_coordinator and current_round == 0:
                existing_opening = conn.execute(
                    """SELECT id FROM speeches
                       WHERE discussion_id = ? AND round = 0 AND participant = 'coordinator'
                       LIMIT 1""",
                    (discussion_id,),
                ).fetchone()
                if existing_opening:
                    raise InvalidParticipantError("Coordinator opening statement already exists for this discussion")

            if current_round > 0 and participant in active_names:
                speakers_this_round = conn.execute(
                    """SELECT DISTINCT participant FROM speeches
                       WHERE discussion_id = ? AND round = ?""",
                    (discussion_id, current_round),
                ).fetchall()
                spoke_names = {r["participant"] for r in speakers_this_round}
                if participant in spoke_names:
                    raise InvalidParticipantError(
                        f"Participant '{participant}' has already spoken in round {current_round}"
                    )
                if disc.speech_order == "fixed":
                    next_speaker = next((name for name in active_names if name not in spoke_names), None)
                    if next_speaker is not None and participant != next_speaker:
                        raise InvalidParticipantError(
                            f"It is not '{participant}' turn to speak. Next speaker: {next_speaker}"
                        )

            if reply_to is not None:
                ref = conn.execute(
                    "SELECT id FROM speeches WHERE id = ? AND discussion_id = ?",
                    (reply_to, discussion_id),
                ).fetchone()
                if not ref:
                    raise InvalidReplyToError(f"reply_to speech {reply_to} not found in discussion {discussion_id}")

            cur = conn.execute(
                """INSERT INTO speeches
                   (discussion_id, round, participant, content, reply_to, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (discussion_id, speech_round, participant, content, reply_to, now),
            )
            speech_id = cur.lastrowid

            round_complete = False
            discussion_complete = False

            if participant == "coordinator" and current_round == 0:
                round_complete = True
            else:
                # Check if all active participants have spoken in this round.
                speakers_this_round = conn.execute(
                    """SELECT DISTINCT participant FROM speeches
                       WHERE discussion_id = ? AND round = ?""",
                    (discussion_id, current_round),
                ).fetchall()
                spoke_names = {r["participant"] for r in speakers_this_round}
                round_complete = all(name in spoke_names for name in active_names)

            if round_complete:
                new_round = current_round + 1
                conn.execute(
                    "UPDATE discussions SET current_round = ? WHERE id = ?",
                    (new_round, discussion_id),
                )
                if new_round > disc.max_rounds:
                    conn.execute(
                        """UPDATE discussions
                           SET status = 'concluded', concluded_at = ?
                           WHERE id = ? AND status = 'active'""",
                        (now, discussion_id),
                    )
                    discussion_complete = True

            # Determine next speaker based on the CURRENT round (post-advance)
            disc_after = self.get_discussion(conn, discussion_id)
            target_round = disc_after.current_round if disc_after else current_round
            next_speaker = None
            if not discussion_complete and active_names and disc.speech_order == "fixed":
                speakers_next = conn.execute(
                    """SELECT DISTINCT participant FROM speeches
                       WHERE discussion_id = ? AND round = ?""",
                    (discussion_id, target_round),
                ).fetchall()
                spoke_next = {r["participant"] for r in speakers_next}
                for name in active_names:
                    if name not in spoke_next:
                        next_speaker = name
                        break

            conn.execute("COMMIT")
        except Exception:  # rollback any failure (sqlite or pre-execute) and re-raise
            conn.execute("ROLLBACK")
            raise

        speech = Speech(
            id=speech_id or 0,
            discussion_id=discussion_id,
            round=speech_round,
            participant=participant,
            content=content,
            reply_to=reply_to,
            created_at=now,
        )
        return {
            "speech": speech,
            "round_complete": round_complete,
            "discussion_complete": discussion_complete,
            "next_speaker": next_speaker,
        }

    def get_speeches(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        *,
        since_round: int | None = None,
        participant: str | None = None,
    ) -> list[Speech]:
        query = "SELECT * FROM speeches WHERE discussion_id = ?"
        params: list[Any] = [discussion_id]
        if since_round is not None:
            query += " AND round >= ?"
            params.append(since_round)
        if participant:
            query += " AND participant = ?"
            params.append(participant)
        query += " ORDER BY id ASC"
        rows = conn.execute(query, params).fetchall()
        return [
            Speech(
                id=r["id"],
                discussion_id=r["discussion_id"],
                round=r["round"],
                participant=r["participant"],
                content=r["content"],
                reply_to=r["reply_to"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def get_speech_count(self, conn: sqlite3.Connection, discussion_id: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM speeches WHERE discussion_id = ?",
            (discussion_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    def add_finding(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        finding_type: str,
        content: str,
        round_num: int,
        related_speeches: list[int] | None = None,
    ) -> int:
        if finding_type not in VALID_FINDING_TYPES:
            raise InvalidFindingTypeError(f"Invalid finding type: {finding_type}")
        rs_json = json.dumps(related_speeches) if related_speeches else None
        cur = conn.execute(
            """INSERT INTO findings
               (discussion_id, type, content, round, related_speeches)
               VALUES (?, ?, ?, ?, ?)""",
            (discussion_id, finding_type, content, round_num, rs_json),
        )
        return cur.lastrowid or 0

    def get_findings(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        *,
        finding_type: str | None = None,
    ) -> list[Finding]:
        if finding_type:
            rows = conn.execute(
                """SELECT * FROM findings
                   WHERE discussion_id = ? AND type = ?
                   ORDER BY id ASC""",
                (discussion_id, finding_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM findings WHERE discussion_id = ? ORDER BY id ASC",
                (discussion_id,),
            ).fetchall()
        return [
            Finding(
                id=r["id"],
                discussion_id=r["discussion_id"],
                type=r["type"],
                content=r["content"],
                round=r["round"],
                related_speeches=json.loads(r["related_speeches"]) if r["related_speeches"] else None,
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Convergence
    # ------------------------------------------------------------------

    def record_convergence(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        round_num: int,
        score: float,
        consensus_count: int,
        disagreement_count: int,
        new_point_count: int,
    ) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO convergence_history
               (discussion_id, round, score, consensus_count,
                disagreement_count, new_point_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (discussion_id, round_num, score, consensus_count, disagreement_count, new_point_count),
        )

    def get_convergence_history(self, conn: sqlite3.Connection, discussion_id: str) -> list[ConvergenceRecord]:
        rows = conn.execute(
            """SELECT * FROM convergence_history
               WHERE discussion_id = ? ORDER BY round ASC""",
            (discussion_id,),
        ).fetchall()
        return [
            ConvergenceRecord(
                discussion_id=r["discussion_id"],
                round=r["round"],
                score=r["score"],
                consensus_count=r["consensus_count"],
                disagreement_count=r["disagreement_count"],
                new_point_count=r["new_point_count"],
            )
            for r in rows
        ]

    def advance_round(self, conn: sqlite3.Connection, discussion_id: str) -> dict[str, Any]:
        """Explicitly advance to the next round.

        Returns dict with new_round, discussion_complete, max_rounds.
        Raises DiscussionNotFoundError / DiscussionNotActiveError.
        """
        disc = self.get_discussion(conn, discussion_id)
        if not disc:
            raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")
        if disc.status != "active":
            raise DiscussionNotActiveError(f"Discussion {discussion_id} is {disc.status}")

        now = int(time.time())
        new_round = disc.current_round + 1
        discussion_complete = False

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE discussions SET current_round = ? WHERE id = ?",
                (new_round, discussion_id),
            )
            if new_round > disc.max_rounds:
                conn.execute(
                    """UPDATE discussions
                       SET status = 'concluded', concluded_at = ?
                       WHERE id = ? AND status = 'active'""",
                    (now, discussion_id),
                )
                discussion_complete = True
            conn.execute("COMMIT")
        except Exception:  # rollback any failure (sqlite or pre-execute) and re-raise
            conn.execute("ROLLBACK")
            raise

        return {
            "new_round": new_round,
            "max_rounds": disc.max_rounds,
            "discussion_complete": discussion_complete,
        }

    def calculate_convergence(self, conn: sqlite3.Connection, discussion_id: str, round_num: int) -> float | None:
        """Calculate convergence score for a given round from its findings.

        Score = consensus_count / (consensus_count + disagreement_count).
        Returns None if no findings exist for the round.
        """
        rows = conn.execute(
            """SELECT type, COUNT(*) as cnt FROM findings
               WHERE discussion_id = ? AND round = ?
               GROUP BY type""",
            (discussion_id, round_num),
        ).fetchall()
        counts = {r["type"]: r["cnt"] for r in rows}
        consensus = int(counts.get("consensus", 0))
        disagreement = int(counts.get("disagreement", 0))
        new_points = counts.get("new_point", 0)

        total = consensus + disagreement
        if total == 0:
            return None

        score = consensus / total

        # Record in convergence_history
        self.record_convergence(
            conn,
            discussion_id,
            round_num,
            score,
            consensus,
            disagreement,
            new_points,
        )

        # Update the discussion's overall convergence_score (latest round)
        conn.execute(
            "UPDATE discussions SET convergence_score = ? WHERE id = ?",
            (score, discussion_id),
        )

        return score

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _loads_json(raw: Any, default: Any = None) -> Any:
        if raw is None or raw == "":
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return default

    @classmethod
    def _normalize_agent_metadata(cls, metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not metadata:
            return {}
        normalized = dict(metadata)
        skills = normalized.get("skills")
        if skills is None:
            normalized["skills"] = []
        elif isinstance(skills, str):
            normalized["skills"] = [skills]
        else:
            normalized["skills"] = [str(skill) for skill in skills if skill]
        skill_versions = normalized.get("skill_versions")
        if not isinstance(skill_versions, dict):
            normalized["skill_versions"] = {}
        roles = normalized.get("roles")
        if roles is None:
            normalized["roles"] = []
        elif isinstance(roles, str):
            normalized["roles"] = [roles]
        else:
            normalized["roles"] = [str(role) for role in roles if role]
        if "availability" in normalized and normalized["availability"] is not None:
            normalized["availability"] = str(normalized["availability"])
        if "accept_policy" in normalized and normalized["accept_policy"] is not None:
            normalized["accept_policy"] = str(normalized["accept_policy"])
        return normalized

    @classmethod
    def _merge_agent_metadata(
        cls,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = cls._normalize_agent_metadata(existing)
        if not incoming:
            return merged
        normalized_incoming = cls._normalize_agent_metadata(incoming)
        for key, value in normalized_incoming.items():
            if key == "skills":
                merged[key] = sorted(set(cls._agent_skills(merged)) | set(cls._agent_skills(normalized_incoming)))
            elif key == "skill_versions":
                versions = dict(merged.get("skill_versions") or {})
                versions.update(value or {})
                merged[key] = versions
            elif key == "roles":
                roles = set(merged.get("roles") or [])
                roles.update(value or [])
                merged[key] = sorted(roles)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _agent_skills(metadata: dict[str, Any] | None) -> list[str]:
        if not metadata:
            return []
        skills = metadata.get("skills", [])
        if isinstance(skills, str):
            return [skills]
        return [str(skill) for skill in skills if skill]

    @staticmethod
    def _public_agent_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        public = dict(metadata or {})
        for key in ("auth_token", "bridge_auth_token", "_bridge_auth_token", "roundtable_auth_token"):
            public.pop(key, None)
        return public

    @staticmethod
    def _row_to_discussion(row: sqlite3.Row) -> Discussion:
        notif_raw = row["notifications"]
        try:
            notif = json.loads(notif_raw) if notif_raw else None
        except json.JSONDecodeError:
            notif = None
        return Discussion(
            id=row["id"],
            topic=row["topic"],
            context=row["context"],
            status=row["status"],
            max_rounds=row["max_rounds"],
            current_round=row["current_round"],
            speech_order=row["speech_order"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            concluded_at=row["concluded_at"],
            conclusion=row["conclusion"],
            convergence_score=row["convergence_score"],
            output_path=row["output_path"],
            notifications=notif,
        )

    @classmethod
    def _row_to_dispatch(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "discussion_id": row["discussion_id"],
            "mode": row["mode"],
            "coordinator_agent_id": row["coordinator_agent_id"],
            "start_policy": row["start_policy"],
            "min_accepts": row["min_accepts"],
            "timeout_seconds": row["timeout_seconds"],
            "status": row["status"],
            "idempotency_key": row["idempotency_key"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "metadata": cls._loads_json(row["metadata"], default={}),
        }

    @classmethod
    def _row_to_summon(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "dispatch_id": row["dispatch_id"],
            "discussion_id": row["discussion_id"],
            "agent_id": row["agent_id"],
            "role": row["role"],
            "perspective": row["perspective"],
            "required_skill": row["required_skill"],
            "status": row["status"],
            "invited_by": row["invited_by"],
            "transport": row["transport"],
            "endpoint": row["endpoint"],
            "delivery_result": cls._loads_json(row["delivery_result"], default={}),
            "idempotency_key": row["idempotency_key"],
            "created_at": row["created_at"],
            "delivered_at": row["delivered_at"],
            "responded_at": row["responded_at"],
            "expires_at": row["expires_at"],
            "metadata": cls._loads_json(row["metadata"], default={}),
        }

    # ------------------------------------------------------------------
    # Agents (MCP multi-agent support)
    # ------------------------------------------------------------------

    def upsert_agent(
        self,
        conn: sqlite3.Connection,
        agent_id: str,
        platform: str,
        *,
        display_name: str | None = None,
        persona: dict[str, Any] | None = None,
        capabilities: list[str] | None = None,
        transport: str = "stdio",
        endpoint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = int(time.time())
        existing_agent = self.get_agent(conn, agent_id, include_private=True)
        if existing_agent:
            normalized_metadata = self._merge_agent_metadata(existing_agent.get("metadata"), metadata)
        else:
            normalized_metadata = self._normalize_agent_metadata(metadata)
        conn.execute(
            """INSERT INTO agents (agent_id, platform, display_name, persona,
                   capabilities, transport, endpoint, last_seen, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                   platform=excluded.platform,
                   display_name=COALESCE(excluded.display_name, agents.display_name),
                   persona=COALESCE(excluded.persona, agents.persona),
                   capabilities=COALESCE(excluded.capabilities, agents.capabilities),
                   transport=excluded.transport,
                   endpoint=COALESCE(excluded.endpoint, agents.endpoint),
                   last_seen=excluded.last_seen,
                   metadata=COALESCE(excluded.metadata, agents.metadata)""",
            (
                agent_id,
                platform,
                display_name,
                json.dumps(persona) if persona else None,
                json.dumps(capabilities) if capabilities else None,
                transport,
                endpoint,
                now,
                json.dumps(normalized_metadata) if normalized_metadata else None,
            ),
        )
        return {"agent_id": agent_id, "last_seen": now}

    def touch_agent(
        self,
        conn: sqlite3.Connection,
        agent_id: str,
        *,
        availability: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = int(time.time())
        agent = self.get_agent(conn, agent_id, include_private=True)
        if not agent:
            return
        merged_metadata = self._merge_agent_metadata(agent.get("metadata"), metadata)
        if availability:
            merged_metadata["availability"] = availability
        merged_metadata["last_heartbeat"] = now
        conn.execute(
            "UPDATE agents SET last_seen = ?, metadata = ? WHERE agent_id = ?",
            (now, json.dumps(merged_metadata), agent_id),
        )

    def heartbeat_agent(
        self,
        conn: sqlite3.Connection,
        agent_id: str,
        *,
        availability: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.touch_agent(conn, agent_id, availability=availability, metadata=metadata)
        agent = self.get_agent(conn, agent_id)
        if not agent:
            return {"error": f"Agent {agent_id} is not registered"}
        return {
            "agent_id": agent_id,
            "last_seen": agent["last_seen"],
            "online": agent["online"],
            "metadata": agent.get("metadata"),
        }

    def list_agents(
        self,
        conn: sqlite3.Connection,
        *,
        online_only: bool = False,
        timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
        required_skill: str | None = None,
        availability: str | None = None,
    ) -> list[dict[str, Any]]:
        if online_only:
            cutoff = int(time.time()) - timeout_seconds
            rows = conn.execute(
                "SELECT * FROM agents WHERE last_seen > ? ORDER BY last_seen DESC",
                (cutoff,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agents ORDER BY last_seen DESC").fetchall()
        results = []
        now = int(time.time())
        for r in rows:
            metadata = self._loads_json(r["metadata"], default={})
            public_metadata = self._public_agent_metadata(metadata)
            skills = self._agent_skills(metadata)
            if required_skill and required_skill not in skills:
                continue
            if availability and metadata.get("availability") != availability:
                continue
            results.append(
                {
                    "agent_id": r["agent_id"],
                    "platform": r["platform"],
                    "display_name": r["display_name"],
                    "persona": self._loads_json(r["persona"]),
                    "capabilities": self._loads_json(r["capabilities"]),
                    "transport": r["transport"],
                    "endpoint": r["endpoint"],
                    "last_seen": r["last_seen"],
                    "online": (now - r["last_seen"]) < timeout_seconds,
                    "metadata": public_metadata,
                    "skills": skills,
                    "availability": metadata.get("availability"),
                    "accept_policy": metadata.get("accept_policy"),
                }
            )
        return results

    def get_agent(
        self,
        conn: sqlite3.Connection,
        agent_id: str,
        *,
        include_private: bool = False,
        timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
    ) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        if not row:
            return None
        now = int(time.time())
        metadata = self._loads_json(row["metadata"], default={})
        result_metadata = metadata if include_private else self._public_agent_metadata(metadata)
        return {
            "agent_id": row["agent_id"],
            "platform": row["platform"],
            "display_name": row["display_name"],
            "persona": self._loads_json(row["persona"]),
            "capabilities": self._loads_json(row["capabilities"]),
            "transport": row["transport"],
            "endpoint": row["endpoint"],
            "last_seen": row["last_seen"],
            "online": (now - row["last_seen"]) < timeout_seconds,
            "metadata": result_metadata,
            "skills": self._agent_skills(metadata),
            "availability": metadata.get("availability"),
            "accept_policy": metadata.get("accept_policy"),
        }

    # ------------------------------------------------------------------
    # Agent Inbox
    # ------------------------------------------------------------------

    def push_inbox(
        self,
        conn: sqlite3.Connection,
        agent_id: str,
        msg_type: str,
        payload: dict[str, Any],
        *,
        discussion_id: str | None = None,
    ) -> int:
        now = int(time.time())
        cur = conn.execute(
            """INSERT INTO agent_inbox (agent_id, type, discussion_id, payload, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (agent_id, msg_type, discussion_id, json.dumps(payload), now),
        )
        return cur.lastrowid or 0

    def read_inbox(
        self,
        conn: sqlite3.Connection,
        agent_id: str,
        *,
        unread_only: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if unread_only:
            rows = conn.execute(
                """SELECT * FROM agent_inbox
                   WHERE agent_id = ? AND read_at IS NULL
                   ORDER BY created_at ASC LIMIT ?""",
                (agent_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM agent_inbox
                   WHERE agent_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (agent_id, limit),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "type": r["type"],
                "discussion_id": r["discussion_id"],
                "payload": json.loads(r["payload"]),
                "created_at": r["created_at"],
                "read_at": r["read_at"],
            }
            for r in rows
        ]

    def mark_inbox_read(self, conn: sqlite3.Connection, message_ids: list[int]) -> int:
        if not message_ids:
            return 0
        placeholders = ",".join("?" for _ in message_ids)
        now = int(time.time())
        cur = conn.execute(
            f"UPDATE agent_inbox SET read_at = ? WHERE id IN ({placeholders}) AND read_at IS NULL",
            [now, *message_ids],
        )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Invitations
    # ------------------------------------------------------------------

    def create_invitation(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        agent_id: str,
        invited_by: str,
        *,
        role: str | None = None,
        perspective: str | None = None,
    ) -> dict[str, Any]:
        now = int(time.time())
        conn.execute(
            """INSERT OR IGNORE INTO invitations
               (discussion_id, agent_id, role, perspective, status, invited_by, invited_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (discussion_id, agent_id, role, perspective, invited_by, now),
        )
        return {
            "discussion_id": discussion_id,
            "agent_id": agent_id,
            "status": "pending",
            "invited_at": now,
        }

    def respond_invitation(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        agent_id: str,
        accept: bool,
    ) -> dict[str, Any]:
        now = int(time.time())
        new_status = "accepted" if accept else "declined"
        cur = conn.execute(
            """UPDATE invitations SET status = ?, responded_at = ?
               WHERE discussion_id = ? AND agent_id = ? AND status = 'pending'""",
            (new_status, now, discussion_id, agent_id),
        )
        if cur.rowcount == 0:
            return {"error": "No pending invitation found"}
        return {"discussion_id": discussion_id, "agent_id": agent_id, "status": new_status}

    def get_invitations(
        self,
        conn: sqlite3.Connection,
        *,
        agent_id: str | None = None,
        discussion_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM invitations WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if discussion_id:
            query += " AND discussion_id = ?"
            params.append(discussion_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY invited_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "discussion_id": r["discussion_id"],
                "agent_id": r["agent_id"],
                "role": r["role"],
                "perspective": r["perspective"],
                "status": r["status"],
                "invited_by": r["invited_by"],
                "invited_at": r["invited_at"],
                "responded_at": r["responded_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Dispatches / Summons
    # ------------------------------------------------------------------

    def create_dispatch(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        coordinator_agent_id: str,
        *,
        mode: str = "federated",
        start_policy: str = "quorum",
        min_accepts: int = 1,
        timeout_seconds: int = 60,
        idempotency_key: str | None = None,
        allow_terminal_retry: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mode not in VALID_DISPATCH_MODES:
            raise ValueError(f"Invalid dispatch mode: {mode}")
        if start_policy not in {"immediate", "quorum", "all", "timeout"}:
            raise ValueError(f"Invalid start_policy: {start_policy}")
        if not self.get_discussion(conn, discussion_id):
            raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")
        if idempotency_key:
            existing = self.get_dispatch(conn, idempotency_key=idempotency_key)
            if existing:
                if allow_terminal_retry and existing["status"] in {"completed", "cancelled", "timeout"}:
                    released_key = f"{idempotency_key}#released:{existing['id']}"
                    conn.execute(
                        "UPDATE dispatches SET idempotency_key = ? WHERE id = ? AND idempotency_key = ?",
                        (released_key, existing["id"], idempotency_key),
                    )
                    self.record_summon_event(
                        conn,
                        summon_id=None,
                        dispatch_id=existing["id"],
                        agent_id=existing.get("coordinator_agent_id"),
                        event="dispatch.idempotency_key.released",
                        payload={
                            "idempotency_key": idempotency_key,
                            "released_key": released_key,
                            "previous_status": existing["status"],
                        },
                    )
                else:
                    return existing

        now = int(time.time())
        dispatch_id = f"dp_{secrets.token_hex(6)}"
        conn.execute(
            """INSERT INTO dispatches
               (id, discussion_id, mode, coordinator_agent_id, start_policy,
                min_accepts, timeout_seconds, status, idempotency_key,
                created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
            (
                dispatch_id,
                discussion_id,
                mode,
                coordinator_agent_id,
                start_policy,
                max(0, int(min_accepts)),
                max(0, int(timeout_seconds)),
                idempotency_key,
                now,
                now,
                json.dumps(metadata) if metadata else None,
            ),
        )
        self.record_summon_event(
            conn,
            summon_id=None,
            dispatch_id=dispatch_id,
            agent_id=coordinator_agent_id,
            event="dispatch.created",
            payload={"mode": mode, "start_policy": start_policy, "min_accepts": min_accepts},
        )
        dispatch = self.get_dispatch(conn, dispatch_id)
        if not dispatch:
            raise RuntimeError("Failed to create dispatch")
        return dispatch

    def get_dispatch(
        self,
        conn: sqlite3.Connection,
        dispatch_id: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        if dispatch_id:
            row = conn.execute("SELECT * FROM dispatches WHERE id = ?", (dispatch_id,)).fetchone()
        elif idempotency_key:
            row = conn.execute(
                "SELECT * FROM dispatches WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        else:
            raise ValueError("dispatch_id or idempotency_key is required")
        return self._row_to_dispatch(row) if row else None

    def list_dispatches(
        self,
        conn: sqlite3.Connection,
        *,
        discussion_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM dispatches WHERE 1=1"
        params: list[Any] = []
        if discussion_id:
            query += " AND discussion_id = ?"
            params.append(discussion_id)
        if status:
            if status not in VALID_DISPATCH_STATUSES:
                raise ValueError(f"Invalid dispatch status: {status}")
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [self._row_to_dispatch(row) for row in rows]

    def update_dispatch_status(
        self,
        conn: sqlite3.Connection,
        dispatch_id: str,
        status: str,
        *,
        started_at: int | None = None,
        completed_at: int | None = None,
    ) -> dict[str, Any] | None:
        if status not in VALID_DISPATCH_STATUSES:
            raise ValueError(f"Invalid dispatch status: {status}")
        now = int(time.time())
        conn.execute(
            """UPDATE dispatches
               SET status = ?,
                   updated_at = ?,
                   started_at = COALESCE(?, started_at),
                   completed_at = COALESCE(?, completed_at)
               WHERE id = ?""",
            (status, now, started_at, completed_at, dispatch_id),
        )
        return self.get_dispatch(conn, dispatch_id)

    def reopen_dispatch_for_retry(
        self,
        conn: sqlite3.Connection,
        dispatch_id: str,
        *,
        retry_timeout_seconds: int = 60,
    ) -> dict[str, Any] | None:
        dispatch = self.get_dispatch(conn, dispatch_id)
        if not dispatch:
            return None
        if dispatch["status"] in {"completed", "cancelled"}:
            return dispatch

        now = int(time.time())
        retry_timeout_seconds = max(0, int(retry_timeout_seconds))
        elapsed = max(0, now - int(dispatch["created_at"]))
        timeout_seconds = max(int(dispatch.get("timeout_seconds") or 0), elapsed + retry_timeout_seconds)
        conn.execute(
            """UPDATE dispatches
               SET status = CASE WHEN status = 'timeout' THEN 'pending' ELSE status END,
                   timeout_seconds = ?,
                   updated_at = ?,
                   completed_at = CASE WHEN status = 'timeout' THEN NULL ELSE completed_at END
               WHERE id = ?""",
            (timeout_seconds, now, dispatch_id),
        )
        self.record_summon_event(
            conn,
            summon_id=None,
            dispatch_id=dispatch_id,
            agent_id=dispatch.get("coordinator_agent_id"),
            event="dispatch.retry",
            payload={"retry_timeout_seconds": retry_timeout_seconds},
        )
        return self.get_dispatch(conn, dispatch_id)

    def create_summon(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        agent_id: str,
        invited_by: str,
        *,
        dispatch_id: str | None = None,
        role: str | None = None,
        perspective: str | None = None,
        required_skill: str | None = None,
        transport: str | None = None,
        endpoint: str | None = None,
        expires_at: int | None = None,
        idempotency_key: str | None = None,
        allow_terminal_retry: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.get_discussion(conn, discussion_id):
            raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")
        agent = self.get_agent(conn, agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} is not registered")
        if required_skill and required_skill not in agent.get("skills", []):
            raise ValueError(f"Agent {agent_id} does not provide required skill: {required_skill}")
        if dispatch_id and not self.get_dispatch(conn, dispatch_id):
            raise ValueError(f"Dispatch {dispatch_id} not found")
        if idempotency_key:
            existing = self.get_summon(conn, idempotency_key=idempotency_key)
            if existing:
                reused = self._maybe_reuse_summon_for_retry(
                    conn,
                    existing,
                    dispatch_id=dispatch_id,
                    invited_by=invited_by,
                    role=role,
                    perspective=perspective,
                    required_skill=required_skill,
                    transport=transport or agent.get("transport"),
                    endpoint=endpoint or agent.get("endpoint"),
                    expires_at=expires_at,
                    idempotency_key=idempotency_key,
                    metadata=metadata,
                    allow_terminal_retry=allow_terminal_retry,
                )
                if reused:
                    return reused
                return existing
        existing = self.get_summon(conn, discussion_id=discussion_id, agent_id=agent_id)
        if existing:
            reused = self._maybe_reuse_summon_for_retry(
                conn,
                existing,
                dispatch_id=dispatch_id,
                invited_by=invited_by,
                role=role,
                perspective=perspective,
                required_skill=required_skill,
                transport=transport or agent.get("transport"),
                endpoint=endpoint or agent.get("endpoint"),
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                metadata=metadata,
                allow_terminal_retry=allow_terminal_retry,
            )
            if reused:
                return reused
            return existing

        now = int(time.time())
        if expires_at is None and dispatch_id:
            dispatch = self.get_dispatch(conn, dispatch_id)
            if dispatch:
                expires_at = dispatch["created_at"] + int(dispatch["timeout_seconds"])
        summon_id = f"sm_{secrets.token_hex(6)}"
        conn.execute(
            """INSERT INTO summons
               (id, dispatch_id, discussion_id, agent_id, role, perspective,
                required_skill, status, invited_by, transport, endpoint,
                idempotency_key, created_at, expires_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)""",
            (
                summon_id,
                dispatch_id,
                discussion_id,
                agent_id,
                role,
                perspective,
                required_skill,
                invited_by,
                transport or agent.get("transport"),
                endpoint or agent.get("endpoint"),
                idempotency_key,
                now,
                expires_at,
                json.dumps(metadata) if metadata else None,
            ),
        )
        self.record_summon_event(
            conn,
            summon_id=summon_id,
            dispatch_id=dispatch_id,
            agent_id=agent_id,
            event="summon.created",
            payload={"discussion_id": discussion_id, "required_skill": required_skill},
        )
        summon = self.get_summon(conn, summon_id)
        if not summon:
            raise RuntimeError("Failed to create summon")
        return summon

    def _maybe_reuse_summon_for_retry(
        self,
        conn: sqlite3.Connection,
        existing: dict[str, Any],
        *,
        dispatch_id: str | None,
        invited_by: str,
        role: str | None,
        perspective: str | None,
        required_skill: str | None,
        transport: str | None,
        endpoint: str | None,
        expires_at: int | None,
        idempotency_key: str | None,
        metadata: dict[str, Any] | None,
        allow_terminal_retry: bool,
    ) -> dict[str, Any] | None:
        if not allow_terminal_retry or existing["status"] == "accepted":
            return None

        previous_dispatch = self.get_dispatch(conn, existing["dispatch_id"]) if existing.get("dispatch_id") else None
        previous_dispatch_terminal = bool(
            previous_dispatch and previous_dispatch["status"] in {"completed", "cancelled", "timeout"}
        )
        summon_retryable = existing["status"] in {"declined", "timeout", "failed"}
        if not summon_retryable and not previous_dispatch_terminal:
            return None

        now = int(time.time())
        conn.execute(
            """UPDATE summons
               SET dispatch_id = ?,
                   status = 'pending',
                   invited_by = ?,
                   role = ?,
                   perspective = ?,
                   required_skill = ?,
                   transport = ?,
                   endpoint = ?,
                   delivery_result = NULL,
                   delivered_at = NULL,
                   responded_at = NULL,
                   expires_at = COALESCE(?, expires_at),
                   idempotency_key = COALESCE(?, idempotency_key),
                   metadata = COALESCE(?, metadata)
               WHERE id = ?""",
            (
                dispatch_id,
                invited_by,
                role,
                perspective,
                required_skill,
                transport,
                endpoint,
                expires_at,
                idempotency_key,
                json.dumps(metadata) if metadata else None,
                existing["id"],
            ),
        )
        self.record_summon_event(
            conn,
            summon_id=existing["id"],
            dispatch_id=dispatch_id,
            agent_id=existing.get("agent_id"),
            event="summon.reused_for_retry",
            payload={
                "previous_dispatch_id": existing.get("dispatch_id"),
                "previous_status": existing.get("status"),
                "retry_at": now,
            },
        )
        return self.get_summon(conn, existing["id"])

    def get_summon(
        self,
        conn: sqlite3.Connection,
        summon_id: str | None = None,
        *,
        discussion_id: str | None = None,
        agent_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        if summon_id:
            row = conn.execute("SELECT * FROM summons WHERE id = ?", (summon_id,)).fetchone()
        elif idempotency_key:
            row = conn.execute(
                "SELECT * FROM summons WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        elif discussion_id and agent_id:
            row = conn.execute(
                "SELECT * FROM summons WHERE discussion_id = ? AND agent_id = ?",
                (discussion_id, agent_id),
            ).fetchone()
        else:
            raise ValueError("summon_id, idempotency_key, or discussion_id+agent_id is required")
        return self._row_to_summon(row) if row else None

    def get_summons(
        self,
        conn: sqlite3.Connection,
        *,
        agent_id: str | None = None,
        discussion_id: str | None = None,
        dispatch_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM summons WHERE 1=1"
        params: list[Any] = []
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if discussion_id:
            query += " AND discussion_id = ?"
            params.append(discussion_id)
        if dispatch_id:
            query += " AND dispatch_id = ?"
            params.append(dispatch_id)
        if status:
            if status not in VALID_SUMMON_STATUSES:
                raise ValueError(f"Invalid summon status: {status}")
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [self._row_to_summon(row) for row in rows]

    def mark_summon_delivered(
        self,
        conn: sqlite3.Connection,
        summon_id: str,
        delivery_result: dict[str, Any],
        *,
        transport: str | None = None,
        endpoint: str | None = None,
    ) -> dict[str, Any] | None:
        now = int(time.time())
        current = self.get_summon(conn, summon_id)
        if not current:
            return None
        ok = delivery_result.get("ok", True) is not False
        new_status = "delivered" if ok else "failed"
        conn.execute(
            """UPDATE summons
               SET status = ?,
                   delivered_at = ?,
                   delivery_result = ?,
                   transport = COALESCE(?, transport),
                   endpoint = COALESCE(?, endpoint)
               WHERE id = ? AND status IN ('pending', 'delivered', 'failed')""",
            (new_status, now, json.dumps(delivery_result), transport, endpoint, summon_id),
        )
        self.record_summon_event(
            conn,
            summon_id=summon_id,
            dispatch_id=current.get("dispatch_id"),
            agent_id=current.get("agent_id"),
            event="summon.delivered" if ok else "summon.failed",
            payload=delivery_result,
        )
        return self.get_summon(conn, summon_id)

    def reset_summon_for_retry(
        self,
        conn: sqlite3.Connection,
        summon_id: str,
        *,
        expires_at: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        current = self.get_summon(conn, summon_id)
        if not current:
            return None
        if current["status"] in {"accepted", "declined"}:
            return current

        conn.execute(
            """UPDATE summons
               SET status = 'pending',
                   delivered_at = NULL,
                   responded_at = NULL,
                   delivery_result = NULL,
                   expires_at = COALESCE(?, expires_at)
               WHERE id = ?
                 AND status IN ('pending', 'delivered', 'failed', 'timeout')""",
            (expires_at, summon_id),
        )
        self.record_summon_event(
            conn,
            summon_id=summon_id,
            dispatch_id=current.get("dispatch_id"),
            agent_id=current.get("agent_id"),
            event="summon.retry",
            payload=payload,
        )
        return self.get_summon(conn, summon_id)

    def respond_summon(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
        agent_id: str,
        accept: bool,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summon = self.get_summon(conn, discussion_id=discussion_id, agent_id=agent_id)
        if not summon:
            return {"error": "No summon found"}
        if summon["status"] in {"accepted", "declined", "timeout"}:
            return summon

        now = int(time.time())
        new_status = "accepted" if accept else "declined"
        conn.execute(
            """UPDATE summons
               SET status = ?, responded_at = ?,
                   metadata = COALESCE(?, metadata)
               WHERE id = ? AND status IN ('pending', 'delivered', 'failed')""",
            (new_status, now, json.dumps(metadata) if metadata else None, summon["id"]),
        )
        if accept:
            self.add_participant(
                conn,
                discussion_id,
                agent_id,
                role=summon.get("role"),
                perspective=summon.get("perspective"),
                display_name=agent_id,
            )
        self.record_summon_event(
            conn,
            summon_id=summon["id"],
            dispatch_id=summon.get("dispatch_id"),
            agent_id=agent_id,
            event="summon.accepted" if accept else "summon.declined",
            payload=metadata,
        )
        updated = self.get_summon(conn, summon["id"])
        return updated or {"error": "Summon response could not be persisted"}

    def expire_summons(self, conn: sqlite3.Connection, now: int | None = None) -> int:
        now = int(time.time()) if now is None else int(now)
        rows = conn.execute(
            """SELECT * FROM summons
               WHERE expires_at IS NOT NULL
                 AND expires_at <= ?
                 AND status IN ('pending', 'delivered')""",
            (now,),
        ).fetchall()
        for row in rows:
            summon = self._row_to_summon(row)
            conn.execute(
                "UPDATE summons SET status = 'timeout', responded_at = ? WHERE id = ?",
                (now, summon["id"]),
            )
            self.record_summon_event(
                conn,
                summon_id=summon["id"],
                dispatch_id=summon.get("dispatch_id"),
                agent_id=summon.get("agent_id"),
                event="summon.timeout",
                payload={"expires_at": summon.get("expires_at"), "now": now},
            )
        return len(rows)

    def record_summon_event(
        self,
        conn: sqlite3.Connection,
        summon_id: str | None,
        dispatch_id: str | None,
        agent_id: str | None,
        event: str,
        payload: dict[str, Any] | None = None,
    ) -> int:
        now = int(time.time())
        cur = conn.execute(
            """INSERT INTO summon_events
               (summon_id, dispatch_id, agent_id, event, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (summon_id, dispatch_id, agent_id, event, json.dumps(payload) if payload else None, now),
        )
        return cur.lastrowid or 0

    def list_summon_events(
        self,
        conn: sqlite3.Connection,
        *,
        summon_id: str | None = None,
        dispatch_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM summon_events WHERE 1=1"
        params: list[Any] = []
        if summon_id:
            query += " AND summon_id = ?"
            params.append(summon_id)
        if dispatch_id:
            query += " AND dispatch_id = ?"
            params.append(dispatch_id)
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY created_at ASC, id ASC"
        rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": row["id"],
                "summon_id": row["summon_id"],
                "dispatch_id": row["dispatch_id"],
                "agent_id": row["agent_id"],
                "event": row["event"],
                "payload": self._loads_json(row["payload"], default={}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def dispatch_readiness(self, conn: sqlite3.Connection, dispatch_id: str) -> dict[str, Any]:
        self.expire_summons(conn)
        dispatch = self.get_dispatch(conn, dispatch_id)
        if not dispatch:
            raise ValueError(f"Dispatch {dispatch_id} not found")
        summons = self.get_summons(conn, dispatch_id=dispatch_id)
        total = len(summons)
        counts = {status: 0 for status in VALID_SUMMON_STATUSES}
        for summon in summons:
            counts[summon["status"]] = counts.get(summon["status"], 0) + 1
        accepted = counts.get("accepted", 0)
        min_accepts = int(dispatch.get("min_accepts") or 0)
        policy = dispatch.get("start_policy") or "quorum"
        now = int(time.time())
        timed_out = (now - int(dispatch["created_at"])) >= int(dispatch.get("timeout_seconds") or 0)

        ready = False
        reason = "waiting"
        terminal_timeout = False
        if dispatch["status"] == "active":
            ready = True
            reason = "already_active"
        elif policy == "immediate":
            ready = True
            reason = "immediate"
        elif policy == "quorum":
            ready = accepted >= min_accepts
            reason = "quorum_met" if ready else "quorum_waiting"
            terminal_timeout = timed_out and not ready
        elif policy == "all":
            ready = total > 0 and accepted == total
            reason = "all_accepted" if ready else "all_waiting"
            terminal_timeout = timed_out and not ready
        elif policy == "timeout":
            ready = timed_out and accepted >= min_accepts
            reason = "timeout_ready" if ready else "timeout_waiting"
            terminal_timeout = timed_out and not ready

        return {
            "dispatch_id": dispatch_id,
            "discussion_id": dispatch["discussion_id"],
            "ready": ready,
            "reason": reason,
            "timed_out": timed_out,
            "terminal_timeout": terminal_timeout,
            "policy": policy,
            "accepted": accepted,
            "total": total,
            "counts": counts,
            "min_accepts": min_accepts,
            "dispatch_status": dispatch["status"],
        }

    def apply_dispatch_readiness(self, conn: sqlite3.Connection, dispatch_id: str) -> dict[str, Any]:
        readiness = self.dispatch_readiness(conn, dispatch_id)
        dispatch = self.get_dispatch(conn, dispatch_id)
        if not dispatch:
            raise ValueError(f"Dispatch {dispatch_id} not found")
        now = int(time.time())

        if readiness["ready"] and dispatch["status"] == "pending":
            updated = self.update_dispatch_status(conn, dispatch_id, "active", started_at=now)
            self.activate_discussion(conn, dispatch["discussion_id"])
            self.record_summon_event(
                conn,
                summon_id=None,
                dispatch_id=dispatch_id,
                agent_id=dispatch.get("coordinator_agent_id"),
                event="dispatch.active",
                payload=readiness,
            )
            return {"dispatch": updated, "readiness": readiness, "discussion_activated": True}

        if readiness["terminal_timeout"] and dispatch["status"] == "pending":
            updated = self.update_dispatch_status(conn, dispatch_id, "timeout", completed_at=now)
            self.record_summon_event(
                conn,
                summon_id=None,
                dispatch_id=dispatch_id,
                agent_id=dispatch.get("coordinator_agent_id"),
                event="dispatch.timeout",
                payload=readiness,
            )
            return {"dispatch": updated, "readiness": readiness, "discussion_activated": False}

        return {"dispatch": dispatch, "readiness": readiness, "discussion_activated": False}
