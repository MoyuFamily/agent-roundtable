"""Core business logic for Roundtable discussions.

Framework-agnostic: uses only RoundtableDB + models. No agent-framework
imports. All handlers return plain dicts (JSON-serializable).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from typing import Any, ClassVar

from roundtable.db import RoundtableDB
from roundtable.exceptions import (
    DiscussionNotActiveError,
    DiscussionNotFoundError,
    InvalidParticipantError,
)
from roundtable.models import ConvergenceRecord, Discussion, Participant, Speech
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

    def __init__(self, db: RoundtableDB | None = None, send_fn: Any = None):
        self.db = db or RoundtableDB()
        self._send_fn = send_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_discussion(
        self,
        topic: str,
        participants: list[dict[str, Any]],
        *,
        context: str | None = None,
        max_rounds: int = 5,
        speech_order: str = "fixed",
        created_by: str = "coordinator",
        output_path: str | None = None,
        notifications: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        except (TypeError, ValueError) as err:
            raise ValueError("max_rounds must be an integer") from err

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
        reply_to: int | None = None,
    ) -> dict[str, Any]:
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
            except (TypeError, ValueError) as err:
                raise ValueError("reply_to must be an integer") from err

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
            )
            speech = result["speech"]
            round_complete = result["round_complete"]
            discussion_complete = result["discussion_complete"]
            next_speaker = result["next_speaker"]

            # Auto-calculate convergence when a round completes
            convergence_score = None
            if round_complete and speech.round > 0:
                convergence_score = self.db.calculate_convergence(conn, discussion_id, speech.round)

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
                speeches_this_round = self.db.get_speeches(conn, discussion_id, since_round=speech.round)
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
        since_round: int | None = None,
        participant: str | None = None,
    ) -> dict[str, Any]:
        """Read discussion history (speeches)."""
        if not discussion_id:
            raise ValueError("discussion_id is required")

        if since_round is not None:
            try:
                since_round = int(since_round)
            except (TypeError, ValueError) as err:
                raise ValueError("since_round must be an integer") from err

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")

            speeches = self.db.get_speeches(
                conn,
                discussion_id,
                since_round=since_round,
                participant=participant,
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

    def status(self, discussion_id: str) -> dict[str, Any]:
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

    def summarize(self, discussion_id: str, *, compact: bool = False) -> dict[str, Any]:
        """Generate summary data for a conclusion document.

        Args:
            discussion_id: The discussion to summarize.
            compact: If True, omit raw rounds data and formatted_history
                to keep output small (<5KB). Use structured_summary instead.
        """
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

            rounds_dict: dict[int, list[dict[str, Any]]] = {}
            for s in speeches:
                rounds_dict.setdefault(s.round, []).append(
                    {
                        "id": s.id,
                        "participant": s.participant,
                        "display_name": p_map.get(s.participant, {}).get("display_name"),
                        "role": p_map.get(s.participant, {}).get("role"),
                        "content": s.content,
                        "reply_to": s.reply_to,
                    }
                )

            final_score = disc.convergence_score
            if not final_score and conv_history:
                final_score = conv_history[-1].score

            # Build a structured summary — compact enough for LLM context,
            # rich enough to write a conclusion without re-reading raw speeches.
            structured_summary = self._build_structured_summary(
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

            result = {
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
                "structured_summary": structured_summary,
            }

            if not compact:
                # Full data — includes all raw speech content
                result["rounds"] = rounds_dict
                result["formatted_history"] = self._format_history(speeches, p_map)

            return result
        finally:
            conn.close()

    def end_discussion(
        self,
        discussion_id: str,
        *,
        force: bool = False,
        conclusion: str | None = None,
    ) -> dict[str, Any]:
        """End a discussion (conclude or cancel)."""
        if not discussion_id:
            raise ValueError("discussion_id is required")

        conn = self.db.connect()
        try:
            disc = self.db.get_discussion(conn, discussion_id)
            if not disc:
                raise DiscussionNotFoundError(f"Discussion {discussion_id} not found")
            if disc.status != "active":
                raise DiscussionNotActiveError(f"Discussion {discussion_id} is already {disc.status}")

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
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List all discussions with optional status filter."""
        try:
            limit = int(limit)
        except (TypeError, ValueError) as err:
            raise ValueError("limit must be an integer") from err

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

    def advance(self, discussion_id: str) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
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

    def calculate_convergence(self, discussion_id: str, round_num: int) -> dict[str, Any]:
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
    # Demo mode
    # ------------------------------------------------------------------

    # Default demo scenario — topic, participants, speeches, findings
    _DEMO_TOPIC: ClassVar[str] = "选择后端框架：FastAPI vs Go Gin vs Node Express"
    _DEMO_PARTICIPANTS: ClassVar[list[dict[str, Any]]] = [
        {
            "profile": "alice",
            "role": "全栈工程师",
            "display_name": "Alice",
            "perspective": "重视开发效率和生态",
        },
        {
            "profile": "bob",
            "role": "架构师",
            "display_name": "Bob",
            "perspective": "重视性能和可维护性",
        },
        {
            "profile": "carol",
            "role": "产品经理",
            "display_name": "Carol",
            "perspective": "重视交付速度和团队学习成本",
        },
    ]
    _DEMO_SPEECHES: ClassVar[dict[int, dict[str, str]]] = {
        1: {
            "alice": (
                "FastAPI 的类型提示和自动生成 OpenAPI 文档太香了，"
                "开发效率至少提升 30%。而且 async 原生支持，"
                "性能也不差。"
            ),
            "bob": (
                "Go Gin 编译后是原生二进制，内存占用只有 Python 的 1/10。"
                "对于我们这种高并发场景，性能优势明显。"
                "而且 Go 的 goroutine 天然适合并发。"
            ),
            "carol": (
                "从产品角度看，团队 80% 是 Python 背景。"
                "切 Go 需要 3 个月学习周期，这段时间功能迭代会停滞。"
                "FastAPI 能让我们更快交付 MVP。"
            ),
        },
        2: {
            "alice": (
                "同意 Carol 的观点。而且 FastAPI + Pydantic 的数据校验"
                "几乎是零成本的，Go 里要写大量 struct tag 和 binding 代码。"
                "维护成本 FastAPI 更低。"
            ),
            "bob": (
                "性能不能只看 hello world。FastAPI 在 CPU 密集型任务上"
                "还是有 GIL 瓶颈。不过我承认，如果用 asyncio + uvicorn，"
                "IO 密集场景差距没那么大。可以考虑 FastAPI + 分层架构。"
            ),
            "carol": (
                "Bob 说的分层架构我支持。先用 FastAPI 快速上线，"
                "性能瓶颈模块后续可以用 Go 重写微服务。"
                "这才是务实的技术选型策略。"
            ),
        },
        3: {
            "alice": (
                "最终方案：FastAPI 作为主力框架，搭配 Celery 处理异步任务。"
                "性能关键路径预留 Go 微服务接口。这样既保证了开发效率，"
                "又不堵死性能优化的路。"
            ),
            "bob": (
                "我同意这个折中方案。但需要在架构设计阶段就定义好"
                "服务边界和 API 契约，避免后面拆分时返工。"
                "建议第一周就定好领域模型。"
            ),
            "carol": (
                "完美！这样我们两周内就能出 MVP。技术风险可控，团队也不需要额外学习成本。我会把这个方案同步给管理层。"
            ),
        },
    }
    _DEMO_FINDINGS: ClassVar[dict[int, list[tuple[str, str]]]] = {
        1: [
            ("consensus", "团队熟悉 Python，学习成本是关键考量因素"),
            ("disagreement", "Go 性能优势 vs FastAPI 开发效率，优先级不同"),
            ("new_point", "需要评估 IO 密集 vs CPU 密集的实际占比"),
        ],
        2: [
            ("consensus", "IO 密集场景下 FastAPI 性能差距可接受"),
            ("consensus", "分层架构是合理的折中方案"),
            ("disagreement", "是否需要在第一阶段就引入 Go 微服务"),
        ],
        3: [
            ("consensus", "采用 FastAPI 主框架 + 预留 Go 微服务扩展"),
            ("consensus", "第一周完成领域模型和 API 契约设计"),
            ("consensus", "两周内交付 MVP，性能瓶颈模块后续迭代"),
        ],
    }

    def run_demo(
        self,
        *,
        topic: str | None = None,
        participants: list[dict[str, Any]] | None = None,
        max_rounds: int = 3,
        verbose: bool = True,
    ) -> dict[str, Any]:
        """Run a complete demo discussion with pre-scripted content.

        Simulates a realistic multi-round discussion with participants,
        speeches, findings, and convergence tracking. Prints formatted
        output to terminal when verbose=True.

        Args:
            topic: Custom topic (uses default demo topic if None).
            participants: Custom participants (uses default if None).
            max_rounds: Number of rounds (default 3).
            verbose: Print formatted output to stdout.

        Returns:
            Dict with discussion result, summary, and convergence data.
        """
        topic = topic or self._DEMO_TOPIC
        participants = participants or self._DEMO_PARTICIPANTS
        p_map = {p["profile"]: p for p in participants}
        p_names = [p["profile"] for p in participants]

        if verbose:
            self._demo_print_header(topic, participants, max_rounds)

        # 1. Create discussion
        result = self.create_discussion(
            topic=topic,
            participants=participants,
            max_rounds=max_rounds,
        )
        disc_id = result["discussion_id"]

        # 2. Run rounds
        for round_num in range(1, max_rounds + 1):
            if verbose:
                self._demo_print_round_start(round_num, max_rounds)

            # Use scripted speeches or generate simple defaults
            round_speeches = self._DEMO_SPEECHES.get(round_num, {})
            for name in p_names:
                content = round_speeches.get(
                    name,
                    f"Round {round_num} 发言：{name} 对本议题的看法（demo 默认内容）。",
                )
                self.speak(disc_id, name, content)
                if verbose:
                    p_info = p_map.get(name, {})
                    self._demo_print_speech(
                        name,
                        p_info.get("display_name", name),
                        p_info.get("role", ""),
                        content,
                    )

            # Add findings for this round
            round_findings = self._DEMO_FINDINGS.get(
                round_num,
                [
                    ("consensus", f"Round {round_num} 达成的共识"),
                    ("disagreement", f"Round {round_num} 存在的分歧"),
                ],
            )
            conn = self.db.connect()
            try:
                for ftype, content in round_findings:
                    self.db.add_finding(conn, disc_id, ftype, content, round_num)
                # Calculate convergence
                conv_score = self.db.calculate_convergence(conn, disc_id, round_num)
            finally:
                conn.close()

            if verbose:
                self._demo_print_round_end(round_findings, conv_score)

        # 3. Generate conclusion
        conclusion = (
            f"经过 {max_rounds} 轮讨论，团队达成一致："
            f"采用 FastAPI 作为主力框架，预留 Go 微服务扩展接口，"
            f"两周内交付 MVP。"
        )
        self.end_discussion(disc_id, conclusion=conclusion)

        # 4. Get final summary
        summary = self.summarize(disc_id, compact=True)

        if verbose:
            self._demo_print_conclusion(conclusion, summary)

        return {
            "ok": True,
            "discussion_id": disc_id,
            "topic": topic,
            "rounds_completed": max_rounds,
            "conclusion": conclusion,
            "convergence_score": summary.get("final_convergence_score"),
            "consensus_points": summary.get("consensus_points", []),
            "disagreement_points": summary.get("disagreement_points", []),
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Demo output formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _demo_print_header(topic: str, participants: list[dict[str, Any]], max_rounds: int) -> None:
        width = 58
        print()
        print("╭" + "─" * width + "╮")
        print("│" + " Roundtable Demo Discussion ".center(width) + "│")
        print("├" + "─" * width + "┤")
        topic_line = f" Topic: {topic}"
        if len(topic_line) > width - 1:
            topic_line = topic_line[: width - 2] + "…"
        print("│" + topic_line.ljust(width) + "│")
        print("│" + f" Rounds: {max_rounds}".ljust(width) + "│")
        print("│" + "".ljust(width) + "│")
        print("│" + " Participants:".ljust(width) + "│")
        for p in participants:
            icon = {"全栈工程师": "👩‍💻", "架构师": "👨‍💻", "产品经理": "👩‍💼"}.get(p.get("role", ""), "👤")
            line = f"   {icon} {p.get('display_name', p['profile'])} ({p.get('role', '')})"
            print("│" + line.ljust(width) + "│")
        print("╰" + "─" * width + "╯")
        print()

    @staticmethod
    def _demo_print_round_start(round_num: int, max_rounds: int) -> None:
        print(f"{'━' * 60}")
        print(f"  📍 Round {round_num}/{max_rounds}")
        print(f"{'━' * 60}")

    @staticmethod
    def _demo_print_speech(name: str, display_name: str, role: str, content: str) -> None:
        icon = {"全栈工程师": "👩‍💻", "架构师": "👨‍💻", "产品经理": "👩‍💼"}.get(role, "👤")
        print(f"\n  {icon} {display_name} ({role}):")
        # Word wrap content
        import textwrap

        for line in textwrap.wrap(content, width=52):
            print(f"     {line}")

    @staticmethod
    def _demo_print_round_end(findings: list[tuple[str, str]], conv_score: float | None) -> None:
        print()
        print(f"  {'─' * 52}")
        score_str = f"{conv_score:.2f}" if conv_score is not None else "N/A"
        print(f"  📊 Convergence: {score_str}")
        for ftype, content in findings:
            icon = {"consensus": "✅", "disagreement": "⚡", "new_point": "💡"}.get(ftype, "•")
            print(f"     {icon} [{ftype}] {content}")
        print()

    @staticmethod
    def _demo_print_conclusion(conclusion: str, summary: dict[str, Any]) -> None:
        width = 58
        print()
        print("╭" + "─" * width + "╮")
        print("│" + " 📋 Discussion Conclusion ".center(width) + "│")
        print("├" + "─" * width + "┤")

        # Conclusion text
        import textwrap

        for line in textwrap.wrap(conclusion, width=width - 4):
            print("│  " + line.ljust(width - 2) + "│")
        print("│" + "".ljust(width) + "│")

        # Convergence
        final_score = summary.get("final_convergence_score")
        if final_score is not None:
            score_line = f"  🎯 Final Convergence: {final_score:.2f}"
            print("│" + score_line.ljust(width) + "│")

        # Consensus points
        consensus = summary.get("consensus_points", [])
        if consensus:
            print("│" + "  ✅ Consensus:".ljust(width) + "│")
            for pt in consensus:
                for line in textwrap.wrap(pt, width=width - 8):
                    print("│    • " + line.ljust(width - 6) + "│")

        # Disagreement points
        disagreements = summary.get("disagreement_points", [])
        if disagreements:
            print("│" + "  ⚡ Disagreements:".ljust(width) + "│")
            for pt in disagreements:
                for line in textwrap.wrap(pt, width=width - 8):
                    print("│    • " + line.ljust(width - 6) + "│")

        print("╰" + "─" * width + "╯")
        print()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_notifier(self, config: dict[str, Any] | None) -> Notifier:
        """Create a Notifier from a discussion's notification config."""
        return Notifier(config, send_fn=self._send_fn)

    def _notify_concluded(self, conn: sqlite3.Connection, disc: Discussion, notifier: Notifier) -> None:
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

    def set_send_fn(self, send_fn: Callable[..., None] | None) -> None:
        """Set or replace the notification send callback."""
        self._send_fn = send_fn

    @staticmethod
    def _format_history(speeches: list[Speech], participants_map: dict[str, Any]) -> str:
        """Format speech history into a human-readable string."""
        lines = []
        for s in speeches:
            p_info = participants_map.get(s.participant, {})
            display = p_info.get("display_name", s.participant)
            role = p_info.get("role", "")
            role_str = f"({role})" if role else ""
            ref_str = f" [引用 #{s.reply_to}]" if s.reply_to else ""
            lines.append(f"[#{s.id}] Round {s.round} | {display}{role_str}{ref_str}:\n  {s.content}")
        return "\n\n".join(lines) if lines else "(暂无发言)"

    @staticmethod
    def _build_structured_summary(
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
        rounds_dict: dict[int, list[Speech]] = {}
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
