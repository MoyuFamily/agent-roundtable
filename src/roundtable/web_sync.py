"""Cross-process JSON sync for WebPublisher discussion state.

Used when the in-memory WebPublisher is not available (e.g. another
process is updating the discussion). Reads from RoundtableDB and
writes the merged result to discussion.json under flock.

Callers pass in the target web_dir so this module does not need to
know where SHARED_DATA_DIR lives — that lookup belongs to RoundtableCore.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from roundtable.db import RoundtableDB

logger = logging.getLogger(__name__)


class WebDiscussionSync:
    def __init__(self, db: RoundtableDB):
        self.db = db

    def _participants_snapshot(self, conn: sqlite3.Connection, discussion_id: str) -> list[dict[str, Any]]:
        return [
            {
                "profile": participant.participant,
                "participant": participant.participant,
                "display_name": participant.display_name or participant.participant,
                "role": participant.role or "",
                "perspective": participant.perspective or "",
                "is_active": participant.is_active,
            }
            for participant in self.db.get_participants(conn, discussion_id)
        ]

    def _dispatch_snapshot(
        self,
        conn: sqlite3.Connection,
        discussion_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        dispatch_items: list[dict[str, Any]] = []
        summary = {
            "count": 0,
            "total_summons": 0,
            "accepted": 0,
            "declined": 0,
            "pending": 0,
            "delivered": 0,
            "failed": 0,
            "timeout": 0,
            "ready": False,
            "active": 0,
            "waiting": 0,
        }
        for dispatch in self.db.list_dispatches(conn, discussion_id=discussion_id):
            readiness_result = self.db.apply_dispatch_readiness(conn, dispatch["id"])
            updated_dispatch = readiness_result.get("dispatch") or dispatch
            summons = self.db.get_summons(conn, dispatch_id=dispatch["id"])
            readiness = readiness_result.get("readiness") or {}
            counts = readiness.get("counts") or {}
            for key in ("accepted", "declined", "pending", "delivered", "failed", "timeout"):
                summary[key] += int(counts.get(key, 0) or 0)
            summary["count"] += 1
            summary["total_summons"] += len(summons)
            if readiness.get("ready"):
                summary["ready"] = True
            if updated_dispatch.get("status") == "active":
                summary["active"] += 1
            elif updated_dispatch.get("status") == "pending":
                summary["waiting"] += 1
            dispatch_items.append(
                {
                    "dispatch": updated_dispatch,
                    "readiness": readiness,
                    "summons": summons,
                }
            )
        return dispatch_items, summary

    def append_token_stream(self, web_dir: Path, event: dict[str, Any]) -> None:
        target = web_dir / "token_stream.jsonl"
        try:
            with open(target, "a") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception:
            logger.debug("Failed to append event to token_stream.jsonl at %s", target)

    def sync_state(self, web_dir: Path, discussion_id: str, conn: sqlite3.Connection) -> None:
        json_path = web_dir / "discussion.json"
        if not json_path.exists():
            return

        lock_path = json_path.with_suffix(".json.lock")
        try:
            with open(lock_path, "a") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    with open(json_path) as f:
                        data = json.load(f)

                    changed = False
                    now = time.time()

                    disc = self.db.get_discussion(conn, discussion_id)
                    if not disc:
                        return

                    dispatches, dispatch_summary = self._dispatch_snapshot(conn, discussion_id)
                    refreshed_disc = self.db.get_discussion(conn, discussion_id)
                    if refreshed_disc:
                        disc = refreshed_disc

                    old_status = data.get("status")
                    if old_status != disc.status:
                        data["status"] = disc.status
                        changed = True

                    participants = self._participants_snapshot(conn, discussion_id)
                    if data.get("participants") != participants:
                        data["participants"] = participants
                        changed = True

                    if data.get("dispatches") != dispatches:
                        data["dispatches"] = dispatches
                        changed = True

                    if data.get("dispatch_summary") != dispatch_summary:
                        data["dispatch_summary"] = dispatch_summary
                        changed = True

                    if disc.status == "concluded" and data.get("conclusion") != disc.conclusion:
                        data["conclusion"] = disc.conclusion
                        changed = True

                    findings = self.db.get_findings(conn, discussion_id)
                    conv_history = self.db.get_convergence_history(conn, discussion_id)
                    conv_map = {c.round: c.score for c in conv_history}

                    findings_by_round: dict[int, list[Any]] = {}
                    for finding in findings:
                        findings_by_round.setdefault(finding.round, []).append(finding)

                    existing_summaries = data.setdefault("round_summaries", [])
                    existing_rounds_map = {s.get("round"): s for s in existing_summaries if "round" in s}

                    max_round_to_sync = max(findings_by_round.keys()) if findings_by_round else 0
                    for r in range(1, max_round_to_sync + 1):
                        round_findings = findings_by_round.get(r, [])
                        consensus_pts = [
                            {"content": finding.content} for finding in round_findings if finding.type == "consensus"
                        ]
                        disagreement_pts = [
                            {"content": finding.content} for finding in round_findings if finding.type == "disagreement"
                        ]

                        if not round_findings and r not in existing_rounds_map:
                            continue

                        score = conv_map.get(r)
                        existing = existing_rounds_map.get(r)
                        needs_update = False
                        if not existing:
                            needs_update = True
                        else:
                            ex_consensus = existing.get("consensus", [])
                            ex_disagreement = existing.get("disagreement", [])
                            ex_score = existing.get("convergence_score")
                            if (
                                ex_consensus != consensus_pts
                                or ex_disagreement != disagreement_pts
                                or ex_score != score
                            ):
                                needs_update = True

                        if needs_update:
                            summary_event = {
                                "type": "round_summary",
                                "round": r,
                                "consensus": consensus_pts,
                                "disagreement": disagreement_pts,
                                "timestamp": now,
                            }
                            if score is not None:
                                summary_event["convergence_score"] = score

                            if existing:
                                existing.update(summary_event)
                            else:
                                existing_summaries.append(summary_event)

                            data.setdefault("events", []).append(summary_event)
                            changed = True
                            self.append_token_stream(web_dir, summary_event)

                    existing_summaries.sort(key=lambda s: s.get("round", 0))

                    if disc.status == "concluded":
                        final_summary = data.get("final_summary")
                        consensus_all = [
                            {"content": finding.content} for finding in findings if finding.type == "consensus"
                        ]
                        disagreement_all = [
                            {"content": finding.content} for finding in findings if finding.type == "disagreement"
                        ]

                        needs_final_summary = False
                        if not final_summary:
                            needs_final_summary = True
                        else:
                            ex_consensus = final_summary.get("consensus", [])
                            ex_disagreement = final_summary.get("disagreement", [])
                            if (
                                len(ex_consensus) != len(consensus_all)
                                or len(ex_disagreement) != len(disagreement_all)
                                or final_summary.get("verdict") != (disc.conclusion or "")
                            ):
                                needs_final_summary = True

                        if needs_final_summary:
                            final_summary_event = {
                                "type": "final_summary",
                                "consensus": consensus_all,
                                "disagreement": disagreement_all,
                                "verdict": disc.conclusion or "",
                                "timestamp": now,
                            }
                            data["final_summary"] = final_summary_event
                            data.setdefault("events", []).append(final_summary_event)
                            changed = True
                            self.append_token_stream(web_dir, final_summary_event)

                        if old_status != "concluded":
                            status_event = {
                                "type": "status_delta",
                                "status": "concluded",
                                "conclusion": disc.conclusion or "",
                                "timestamp": now,
                            }
                            data.setdefault("events", []).append(status_event)
                            changed = True
                            self.append_token_stream(web_dir, status_event)

                    if changed:
                        data["updated_at"] = now
                        tmp = json_path.with_suffix(".json.tmp")
                        with open(tmp, "w") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                            f.flush()
                            os.fsync(f.fileno())
                        os.rename(str(tmp), str(json_path))
                        logger.info("Synchronized web discussion.json for %s from database", discussion_id)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            logger.exception("Failed to sync web discussion state for %s", discussion_id)

    def update_speech(
        self,
        web_dir: Path,
        discussion_id: str,
        speech_data: dict[str, Any],
        topic: str,
        participants: list[Any],
    ) -> None:
        json_path = web_dir / "discussion.json"
        if not json_path.exists():
            return

        lock_path = json_path.with_suffix(".json.lock")
        try:
            with open(lock_path, "a") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    with open(json_path) as f:
                        data = json.load(f)

                    data.setdefault("speeches", []).append(speech_data)
                    now = time.time()
                    data.setdefault("events", []).append(
                        {
                            "type": "speech_delta",
                            "speech": speech_data,
                            "timestamp": now,
                        }
                    )
                    data["updated_at"] = now

                    self.append_token_stream(
                        web_dir,
                        {
                            "type": "speech_delta",
                            "speech": speech_data,
                            "timestamp": now,
                        },
                    )

                    tmp = json_path.with_suffix(".json.tmp")
                    with open(tmp, "w") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.rename(str(tmp), str(json_path))
                    logger.info("Updated web discussion.json for %s (cross-process)", discussion_id)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            logger.exception("Failed to update web discussion.json for %s", discussion_id)

    def conclude(self, web_dir: Path, discussion_id: str, conclusion: str) -> None:
        json_path = web_dir / "discussion.json"
        if not json_path.exists():
            return

        lock_path = json_path.with_suffix(".json.lock")
        try:
            with open(lock_path, "a") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    with open(json_path) as f:
                        data = json.load(f)

                    data["conclusion"] = conclusion
                    data["status"] = "concluded"
                    now = time.time()
                    data.setdefault("events", []).append(
                        {
                            "type": "status_delta",
                            "status": "concluded",
                            "conclusion": conclusion,
                            "timestamp": now,
                        }
                    )
                    data["updated_at"] = now

                    self.append_token_stream(
                        web_dir,
                        {
                            "type": "status_delta",
                            "status": "concluded",
                            "conclusion": conclusion,
                            "timestamp": now,
                        },
                    )

                    tmp = json_path.with_suffix(".json.tmp")
                    with open(tmp, "w") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.rename(str(tmp), str(json_path))
                    logger.info("Concluded web discussion.json for %s (cross-process)", discussion_id)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            logger.exception("Failed to conclude web discussion.json for %s", discussion_id)
