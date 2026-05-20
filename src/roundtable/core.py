"""Core business logic for Roundtable discussions.

Framework-agnostic: uses only RoundtableDB + models. No agent-framework
imports. All handlers return plain dicts (JSON-serializable).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from roundtable.db import RoundtableDB
from roundtable.exceptions import (
    DiscussionNotFoundError,
    DiscussionNotActiveError,
    InvalidParticipantError,
    RoundtableError,
)
from roundtable.notify import Notifier

logger = logging.getLogger(__name__)


class RoundtableCore:
    """High-level discussion operations.

    Wraps RoundtableDB with validation, round progression logic,
    and result formatting. Each method returns a JSON-serializable dict.

    Args:
        db: A RoundtableDB instance (uses default if None).
        send_fn: Optional callback(platform, chat_id, message) for notifications.
    """

    def __init__(self, db: Optional[RoundtableDB] = None, send_fn=None):
        self.db = db or RoundtableDB()
        self._send_fn = send_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_discussion(
        self,
        topic: str,
        participants: List[Dict[str, Any]],
        *,
        context: Optional[str] = None,
        max_rounds: int = 5,
        speech_order: str = "fixed",
        created_by: str = "coordinator",
        output_path: Optional[str] = None,
        notifications: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new roundtable discussion.

        Returns dict with discussion_id, topic, participants, etc.
        Raises ValueError / RoundtableError on validation failure.
        """
        if not topic or not topic.strip():
            raise ValueError("topic is required")
        if not participants or not isinstance(participants, list):
            raise ValueError("participants must be a non-empty array of objects")
        if len(participants) < 2:
            raise ValueError("At least 2 participants are required for a discussion")

        try:
            max_rounds = int(max_rounds)
        except (TypeError, ValueError):
            raise ValueError("max_rounds must be an integer")

        conn = self.db.connect()
        try:
            disc = self.db.create_discussion(
                conn,
                topic=topic.strip(),
                participants=participants,
                context=context,
                max_rounds=max_rounds,
                speech_order=speech_order,
                created_by=created_by,
                output_path=output_path,
                notifications=notifications,
            )
            return {
                "ok": True,
                "discussion_id": disc.id,
                "topic": disc.topic,
                "participants": [p.get("profile") for p in participants],
                "max_rounds": disc.max_rounds,
                "speech_order": disc.speech_order,
                "status": disc.status,
            }
        finally:
            conn.close()

    def speak(
        self,
        discussion_id: str,
        participant: str,
        content: str,
        *,
        reply_to: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Record a participant's speech.

        Returns dict with speech_id, round, next_speaker, etc.
        """
        if not discussion_id:
            raise ValueError("discussion_id is required")
        if not participant:
            raise ValueError("participant is required")
        if not content or not content.strip():
            raise ValueError("content is required")

        if reply_to is not None:
            try:
                reply_to = int(reply_to)
            except (TypeError, ValueError):
                raise ValueError("reply_to must be an integer")

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")
            if disc.status != "active":
                raise DiscussionNotActiveError(f"Discussion {discussion_id} is {disc.status}")

            active_names = self.db.get_active_participant_names(conn, discussion_id)
            is_coordinator = participant == "coordinator"
            if not is_coordinator and participant not in active_names:
                raise InvalidParticipantError(
                    f"Participant '{participant}' is not an active member of this discussion. "
                    f"Active: {', '.join(active_names)}"
                )

            result = self.db.add_speech(
                conn,
                discussion_id=discussion_id,
                participant=participant,
                content=content.strip(),
                reply_to=reply_to,
                round_override=0 if is_coordinator else None,
            )
            speech = result["speech"]
            round_complete = result["round_complete"]
            discussion_complete = result["discussion_complete"]
            next_speaker = result["next_speaker"]

            # Auto-calculate convergence when a round completes
            convergence_score = None
            if round_complete and speech.round > 0:
                convergence_score = self.db.calculate_convergence(
                    conn, discussion_id, speech.round
                )

            # --- Notifications ---
            notifier = self._make_notifier(disc.notifications)
            participants = self.db.get_participants(conn, discussion_id)
            p_map = {p.participant: p for p in participants}

            # Speech notification
            p_info = p_map.get(speech.participant)
            notifier.notify(
                "speech",
                discussion_id=discussion_id,
                topic=disc.topic,
                participant=speech.participant,
                display_name=p_info.display_name if p_info else speech.participant,
                role=p_info.role if p_info else "",
                round_num=speech.round,
                content=speech.content,
            )

            # Check if this is the first speech in a new round (round_start)
            if speech.round > 0 and not round_complete:
                speeches_this_round = self.db.get_speeches(
                    conn, discussion_id, since_round=speech.round
                )
                # Filter to current round only
                round_speeches = [s for s in speeches_this_round if s.round == speech.round]
                if len(round_speeches) == 1:
                    # First speech in this round — fire round_start
                    notifier.notify(
                        "round_start",
                        discussion_id=discussion_id,
                        topic=disc.topic,
                        round_num=speech.round,
                    )

            # Round complete notification
            if round_complete and speech.round > 0:
                # Get key points from this round
                findings = self.db.get_findings(conn, discussion_id)
                round_findings = [f for f in findings if f.round == speech.round]
                key_points = [f.content for f in round_findings]
                notifier.notify(
                    "round_end",
                    discussion_id=discussion_id,
                    topic=disc.topic,
                    round_num=speech.round,
                    convergence=convergence_score,
                    key_points=key_points,
                )

            # Discussion auto-concluded notification
            if discussion_complete:
                self._notify_concluded(conn, disc, notifier)

            return {
                "ok": True,
                "speech_id": speech.id,
                "round": speech.round,
                "participant": speech.participant,
                "next_speaker": next_speaker,
                "round_complete": round_complete,
                "discussion_complete": discussion_complete,
                "convergence_score": convergence_score,
            }
        finally:
            conn.close()

    def read(
        self,
        discussion_id: str,
        *,
        since_round: Optional[int] = None,
        participant: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read discussion history (speeches)."""
        if not discussion_id:
            raise ValueError("discussion_id is required")

        if since_round is not None:
            try:
                since_round = int(since_round)
            except (TypeError, ValueError):
                raise ValueError("since_round must be an integer")

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")

            speeches = self.db.get_speeches(
                conn, discussion_id,
                since_round=since_round, participant=participant,
            )
            participants = self.db.get_participants(conn, discussion_id)
            p_map = {
                p.participant: {
                    "role": p.role,
                    "display_name": p.display_name,
                    "perspective": p.perspective,
                }
                for p in participants
            }

            return {
                "ok": True,
                "discussion_id": disc.id,
                "topic": disc.topic,
                "current_round": disc.current_round,
                "max_rounds": disc.max_rounds,
                "status": disc.status,
                "speeches": [
                    {
                        "id": s.id,
                        "round": s.round,
                        "participant": s.participant,
                        "display_name": p_map.get(s.participant, {}).get("display_name"),
                        "content": s.content,
                        "reply_to": s.reply_to,
                        "created_at": s.created_at,
                    }
                    for s in speeches
                ],
                "speech_count": len(speeches),
                "formatted_history": self._format_history(speeches, p_map),
            }
        finally:
            conn.close()

    def status(self, discussion_id: str) -> Dict[str, Any]:
        """Get discussion status including convergence metrics."""
        if not discussion_id:
            raise ValueError("discussion_id is required")

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")

            participants = self.db.get_participants(conn, discussion_id)
            speech_count = self.db.get_speech_count(conn, discussion_id)
            findings = self.db.get_findings(conn, discussion_id)
            conv_history = self.db.get_convergence_history(conn, discussion_id)

            consensus_pts = [f.content for f in findings if f.type == "consensus"]
            disagreement_pts = [f.content for f in findings if f.type == "disagreement"]
            new_points = [f.content for f in findings if f.type == "new_point"]

            active_names = self.db.get_active_participant_names(conn, discussion_id)
            next_speaker = None
            if disc.status == "active" and active_names:
                speakers_current = conn.execute(
                    """SELECT DISTINCT participant FROM speeches
                       WHERE discussion_id = ? AND round = ?""",
                    (discussion_id, disc.current_round),
                ).fetchall()
                spoke = {r["participant"] for r in speakers_current}
                for name in active_names:
                    if name not in spoke:
                        next_speaker = name
                        break

            return {
                "ok": True,
                "discussion_id": disc.id,
                "topic": disc.topic,
                "status": disc.status,
                "current_round": disc.current_round,
                "max_rounds": disc.max_rounds,
                "speech_order": disc.speech_order,
                "convergence_score": disc.convergence_score,
                "consensus_points": consensus_pts,
                "disagreement_points": disagreement_pts,
                "new_points": new_points,
                "speech_count": speech_count,
                "participant_count": len(participants),
                "next_speaker": next_speaker,
                "convergence_history": [
                    {
                        "round": c.round,
                        "score": c.score,
                        "consensus": c.consensus_count,
                        "disagreement": c.disagreement_count,
                        "new_points": c.new_point_count,
                    }
                    for c in conv_history
                ],
            }
        finally:
            conn.close()

    def summarize(self, discussion_id: str) -> Dict[str, Any]:
        """Generate summary data for a conclusion document."""
        if not discussion_id:
            raise ValueError("discussion_id is required")

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")

            participants = self.db.get_participants(conn, discussion_id)
            speeches = self.db.get_speeches(conn, discussion_id)
            findings = self.db.get_findings(conn, discussion_id)
            conv_history = self.db.get_convergence_history(conn, discussion_id)

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

            rounds_dict: dict = {}
            for s in speeches:
                rounds_dict.setdefault(s.round, []).append({
                    "id": s.id,
                    "participant": s.participant,
                    "display_name": p_map.get(s.participant, {}).get("display_name"),
                    "role": p_map.get(s.participant, {}).get("role"),
                    "content": s.content,
                    "reply_to": s.reply_to,
                })

            final_score = disc.convergence_score
            if not final_score and conv_history:
                final_score = conv_history[-1].score

            # Build a structured summary — compact enough for LLM context,
            # rich enough to write a conclusion without re-reading raw speeches.
            structured_summary = self._build_structured_summary(
                disc, participants, speeches, p_map,
                consensus_pts, disagreement_pts, new_points,
                final_score, conv_history,
            )

            return {
                "ok": True,
                "discussion_id": disc.id,
                "topic": disc.topic,
                "context": disc.context,
                "status": disc.status,
                "total_rounds": disc.current_round,
                "max_rounds": disc.max_rounds,
                "final_convergence_score": final_score,
                "participants": [
                    {
                        "profile": p.participant,
                        "display_name": p.display_name,
                        "role": p.role,
                        "perspective": p.perspective,
                    }
                    for p in participants
                ],
                "consensus_points": consensus_pts,
                "disagreement_points": disagreement_pts,
                "new_points": new_points,
                "speech_count": len(speeches),
                "rounds": rounds_dict,
                "convergence_history": [
                    {
                        "round": c.round,
                        "score": c.score,
                        "consensus": c.consensus_count,
                        "disagreement": c.disagreement_count,
                    }
                    for c in conv_history
                ],
                "output_path": disc.output_path,
                "formatted_history": self._format_history(speeches, p_map),
                "structured_summary": structured_summary,
            }
        finally:
            conn.close()

    def end_discussion(
        self,
        discussion_id: str,
        *,
        force: bool = False,
        conclusion: Optional[str] = None,
    ) -> Dict[str, Any]:
        """End a discussion (conclude or cancel)."""
        if not discussion_id:
            raise ValueError("discussion_id is required")

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")
            if disc.status != "active":
                raise DiscussionNotActiveError(
                    f"Discussion {discussion_id} is already {disc.status}"
                )

            if force:
                ok = self.db.cancel_discussion(conn, discussion_id)
                action = "cancelled"
            else:
                ok = self.db.conclude_discussion(conn, discussion_id, conclusion=conclusion)
                action = "concluded"

            # Fire concluded notification (only on conclude, not cancel)
            if action == "concluded":
                disc_after = self.db.get_discussion(conn, discussion_id)
                if disc_after:
                    notifier = self._make_notifier(disc.notifications)
                    self._notify_concluded(conn, disc_after, notifier)

            return {
                "ok": True,
                "discussion_id": discussion_id,
                "action": action,
                "success": ok,
            }
        finally:
            conn.close()

    def list_discussions(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """List all discussions with optional status filter."""
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer")

        conn = self.db.connect()
        try:
            discussions = self.db.list_discussions(conn, status=status, limit=limit)
            return {
                "ok": True,
                "discussions": [
                    {
                        "id": d.id,
                        "topic": d.topic,
                        "status": d.status,
                        "current_round": d.current_round,
                        "max_rounds": d.max_rounds,
                        "created_by": d.created_by,
                        "created_at": d.created_at,
                        "concluded_at": d.concluded_at,
                        "convergence_score": d.convergence_score,
                    }
                    for d in discussions
                ],
                "count": len(discussions),
                "filter_status": status,
            }
        finally:
            conn.close()

    def advance(self, discussion_id: str) -> Dict[str, Any]:
        """Explicitly advance to the next round.

        Returns dict with new_round, max_rounds, discussion_complete.
        """
        if not discussion_id:
            raise ValueError("discussion_id is required")

        conn = self.db.connect()
        try:
            result = self.db.advance_round(conn, discussion_id)
            return {"ok": True, "discussion_id": discussion_id, **result}
        finally:
            conn.close()

    def notify(
        self,
        discussion_id: str,
        event: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Manually trigger a notification for a discussion.

        Useful for custom notification flows or re-sending missed events.
        """
        if not discussion_id:
            raise ValueError("discussion_id is required")

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")

            notifier = self._make_notifier(disc.notifications)
            notifier.notify(
                event,
                discussion_id=discussion_id,
                topic=disc.topic,
                **kwargs,
            )
            return {"ok": True, "discussion_id": discussion_id, "event": event}
        finally:
            conn.close()

    def calculate_convergence(
        self, discussion_id: str, round_num: int
    ) -> Dict[str, Any]:
        """Calculate convergence score for a round from its findings.

        Score = consensus / (consensus + disagreement).
        Returns None score if no findings exist.
        """
        if not discussion_id:
            raise ValueError("discussion_id is required")

        conn = self.db.connect()
        try:
            score = self.db.calculate_convergence(conn, discussion_id, round_num)
            return {
                "ok": True,
                "discussion_id": discussion_id,
                "round": round_num,
                "convergence_score": score,
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_notifier(self, config: Optional[Dict[str, Any]]) -> Notifier:
        """Create a Notifier from a discussion's notification config."""
        return Notifier(config, send_fn=self._send_fn)

    def _notify_concluded(self, conn, disc, notifier: Notifier) -> None:
        """Fire the concluded notification with summary data."""
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

    def set_send_fn(self, send_fn) -> None:
        """Set or replace the notification send callback."""
        self._send_fn = send_fn

    @staticmethod
    def _format_history(speeches, participants_map: dict) -> str:
        """Format speech history into a human-readable string."""
        lines = []
        for s in speeches:
            p_info = participants_map.get(s.participant, {})
            display = p_info.get("display_name", s.participant)
            role = p_info.get("role", "")
            role_str = f"({role})" if role else ""
            ref_str = f" [引用 #{s.reply_to}]" if s.reply_to else ""
            lines.append(
                f"[#{s.id}] Round {s.round} | {display}{role_str}{ref_str}:\n  {s.content}"
            )
        return "\n\n".join(lines) if lines else "(暂无发言)"

    @staticmethod
    def _build_structured_summary(
        disc, participants, speeches, p_map,
        consensus_pts, disagreement_pts, new_points,
        final_score, conv_history,
    ) -> str:
        """Build a compact structured summary for LLM consumption.

        Returns a Markdown string (~500-2000 chars) that gives the coordinator
        enough context to write a conclusion document without re-reading all
        raw speech content.
        """
        lines = []
        lines.append(f"# 圆桌讨论摘要: {disc.topic}")
        if disc.context:
            lines.append(f"\n**背景**: {disc.context}")

        # Participants
        lines.append("\n## 参与者")
        for p in participants:
            name = p.display_name or p.participant
            role = p.role or "未指定"
            perspective = p.perspective or ""
            persp_str = f" — {perspective}" if perspective else ""
            lines.append(f"- **{name}** ({role}){persp_str}")

        # Per-round summary (key points only, truncate content)
        lines.append(f"\n## 讨论轮次 (共 {disc.current_round} 轮)")
        rounds_dict: dict = {}
        for s in speeches:
            rounds_dict.setdefault(s.round, []).append(s)

        for rnd in sorted(rounds_dict.keys()):
            round_speeches = rounds_dict[rnd]
            lines.append(f"\n### Round {rnd}")
            for s in round_speeches:
                p_info = p_map.get(s.participant, {})
                display = p_info.get("display_name", s.participant)
                role = p_info.get("role", "")
                role_str = f" ({role})" if role else ""
                # Truncate content to 300 chars for summary
                content = s.content
                if len(content) > 300:
                    content = content[:297] + "..."
                lines.append(f"- **{display}**{role_str}: {content}")

        # Findings
        if consensus_pts:
            lines.append("\n## 共识点")
            for pt in consensus_pts:
                lines.append(f"- {pt}")

        if disagreement_pts:
            lines.append("\n## 分歧点")
            for pt in disagreement_pts:
                lines.append(f"- {pt}")

        if new_points:
            lines.append("\n## 新议题")
            for pt in new_points:
                lines.append(f"- {pt}")

        # Convergence
        if final_score is not None:
            lines.append(f"\n## 收敛度: {final_score:.2f}")
        if conv_history:
            for c in conv_history:
                lines.append(
                    f"- Round {c.round}: score={c.score:.2f}, "
                    f"consensus={c.consensus_count}, disagreement={c.disagreement_count}"
                )

        return "\n".join(lines)
