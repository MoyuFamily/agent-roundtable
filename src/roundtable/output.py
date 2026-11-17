"""Markdown output and summary generation for Roundtable discussions."""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from roundtable.db import RoundtableDB
from roundtable.file_io import file_lock
from roundtable.formatter import build_structured_summary, format_history
from roundtable.models import ConvergenceRecord, Discussion, Participant, Speech
from roundtable.notify import Notifier

logger = logging.getLogger(__name__)


class OutputBuilder:
    def __init__(self, db: RoundtableDB):
        self.db = db

    def write_markdown(self, output_path: str, content: str) -> dict[str, Any]:
        temporary: Path | None = None
        try:
            path = Path(output_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content.rstrip() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return {"output_written": True, "output_path": str(path)}
        except OSError as exc:
            logger.exception("Failed to write roundtable output_path: %s", output_path)
            return {"output_written": False, "output_path": output_path, "output_error": str(exc)}
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def publish(self, discussion_id: str) -> dict[str, Any]:
        """Read and export under one file lock, so a late writer cannot restore old content."""
        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if disc is None or disc.output_path is None:
                return {}
            path = Path(disc.output_path).expanduser()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with file_lock(path.with_suffix(path.suffix + ".lock")):
                    # Start the snapshot after taking the export lock, never from the caller's stale read.
                    conn.execute("BEGIN")
                    current = self.db.get_discussion(conn, discussion_id)
                    if current is None:
                        return {}
                    return self.write_markdown(str(path), self.build_summary_markdown(conn, current))
            except OSError as exc:
                return {"output_written": False, "output_path": str(path), "output_error": str(exc)}
        finally:
            conn.close()

    def build_summary_markdown(self, conn: sqlite3.Connection, disc: Discussion) -> str:
        participants = self.db.get_participants(conn, disc.id)
        speeches = self.db.get_speeches(conn, disc.id)
        findings = self.db.get_findings(conn, disc.id)
        conv_history = self.db.get_convergence_history(conn, disc.id)

        p_map = {
            p.participant: {
                "role": p.role,
                "display_name": p.display_name,
                "perspective": p.perspective,
            }
            for p in participants
        }
        consensus_pts = [f.content for f in findings if f.type == "consensus"]
        disagreement_pts = [f.content for f in findings if f.type == "disagreement"]
        new_points = [f.content for f in findings if f.type == "new_point"]
        final_score = disc.convergence_score
        if final_score is None and conv_history:
            final_score = conv_history[-1].score

        return build_structured_summary(
            disc,
            participants,
            speeches,
            p_map,
            consensus_pts,
            disagreement_pts,
            new_points,
            final_score,
            conv_history,
            context_history=self.db.get_context_history(conn, disc.id),
            findings=findings,
            materials=self.db.get_material_summaries(conn, disc.id),
        )

    def notify_concluded(self, conn: sqlite3.Connection, disc: Discussion, notifier: Notifier) -> None:
        findings = self.db.get_findings(conn, disc.id)
        consensus = [f.content for f in findings if f.type == "consensus"]
        disagreements = [f.content for f in findings if f.type == "disagreement"]
        notifier.notify(
            "concluded",
            discussion_id=disc.id,
            topic=disc.topic,
            conclusion=disc.conclusion or "",
            convergence=disc.convergence_score,
            consensus_points=consensus,
            disagreement_points=disagreements,
        )

    @staticmethod
    def format_history(speeches: list[Speech], participants_map: dict[str, Any]) -> str:
        return format_history(speeches, participants_map)

    @staticmethod
    def build_structured_summary(
        disc: Discussion,
        participants: list[Participant],
        speeches: list[Speech],
        p_map: dict[str, Any],
        consensus_pts: list[str],
        disagreement_pts: list[str],
        new_points: list[str],
        final_score: float | None,
        conv_history: list[ConvergenceRecord],
    ) -> str:
        return build_structured_summary(
            disc,
            participants,
            speeches,
            p_map,
            consensus_pts,
            disagreement_pts,
            new_points,
            final_score,
            conv_history,
        )
