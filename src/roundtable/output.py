"""Markdown output and summary generation for Roundtable discussions."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from roundtable.db import RoundtableDB
from roundtable.formatter import build_structured_summary, format_history
from roundtable.models import ConvergenceRecord, Discussion, Participant, Speech
from roundtable.notify import Notifier

logger = logging.getLogger(__name__)


class OutputBuilder:
    def __init__(self, db: RoundtableDB):
        self.db = db

    def write_markdown(self, output_path: str, content: str) -> dict[str, Any]:
        try:
            path = Path(output_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content.rstrip() + "\n", encoding="utf-8")
            return {"output_written": True, "output_path": str(path)}
        except OSError as exc:
            logger.exception("Failed to write roundtable output_path: %s", output_path)
            return {"output_written": False, "output_path": output_path, "output_error": str(exc)}

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
        if not final_score and conv_history:
            final_score = conv_history[-1].score

        return self.build_structured_summary(
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

    def build_output_markdown(
        self,
        conn: sqlite3.Connection,
        disc: Discussion,
        *,
        conclusion_override: str | None = None,
    ) -> str:
        conclusion = conclusion_override if conclusion_override is not None else disc.conclusion
        summary = self.build_summary_markdown(conn, disc)
        if not conclusion:
            return summary
        return f"{summary}\n\n## 最终结论\n\n{conclusion.strip()}"

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
