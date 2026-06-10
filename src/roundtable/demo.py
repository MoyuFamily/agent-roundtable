from __future__ import annotations

import argparse
import logging
import textwrap
from typing import Any

from roundtable.demo_data import DEMO_FINDINGS, DEMO_PARTICIPANTS, DEMO_SPEECHES, DEMO_TOPIC

logger = logging.getLogger(__name__)


class DemoRunner:
    """Helper to run a complete demo discussion using a RoundtableCore instance."""

    def __init__(self, core: Any) -> None:
        self.core = core

    def run(
        self,
        *,
        topic: str | None = None,
        participants: list[dict[str, Any]] | None = None,
        max_rounds: int = 3,
        verbose: bool = True,
        web: bool = True,
        web_port: int = 8199,
        stream_delay: float = 0.0,
    ) -> dict[str, Any]:
        topic = topic or DEMO_TOPIC
        participants = participants or DEMO_PARTICIPANTS
        p_map = {p["profile"]: p for p in participants}
        p_names = [p["profile"] for p in participants]

        # 设置流式延迟
        self.core._stream_delay = stream_delay

        if verbose:
            self._demo_print_header(topic, participants, max_rounds)

        # 1. Create discussion
        result = self.core.create_discussion(
            topic=topic,
            participants=participants,
            max_rounds=max_rounds,
            web=web,
            web_port=web_port,
        )
        disc_id = result["discussion_id"]
        web_url = result.get("web_url")
        web_status = result.get("web_status")
        if verbose and web:
            if web_url:
                print(f"\n  Web viewer: {web_url}\n")
            else:
                print(f"\n  Web viewer unavailable: {result.get('web_error') or 'unknown error'}\n")

        self.core.speak(disc_id, "coordinator", f"开场：围绕「{topic}」展开圆桌讨论。")

        # 2. Run rounds
        for round_num in range(1, max_rounds + 1):
            if verbose:
                self._demo_print_round_start(round_num, max_rounds)

            # Use scripted speeches or generate simple defaults
            round_speeches = DEMO_SPEECHES.get(round_num, {})
            for name in p_names:
                content = round_speeches.get(
                    name,
                    f"Round {round_num} 发言：{name} 对本议题的看法（demo 默认内容）。",
                )
                self.core.speak(disc_id, name, content)

                if verbose:
                    p_info = p_map.get(name, {})
                    self._demo_print_speech(
                        name,
                        p_info.get("display_name", name),
                        p_info.get("role", ""),
                        content,
                    )

            # Add findings for this round
            round_findings = DEMO_FINDINGS.get(
                round_num,
                [
                    ("consensus", f"Round {round_num} 达成的共识"),
                    ("disagreement", f"Round {round_num} 存在的分歧"),
                ],
            )
            conn = self.core.db.connect()
            try:
                for ftype, content in round_findings:
                    self.core.db.add_finding(conn, disc_id, ftype, content, round_num)
                # Calculate convergence
                conv_score = self.core.db.calculate_convergence(conn, disc_id, round_num)
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
        self.core.end_discussion(disc_id, conclusion=conclusion)

        # 4. Get final summary
        summary = self.core.summarize(disc_id, compact=True)

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
            "web_url": web_url,
            "web_status": web_status,
            "web_error": result.get("web_error"),
            "web_help": result.get("web_help"),
        }

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

        for line in textwrap.wrap(conclusion, width=width - 4):
            print("│  " + line.ljust(width - 2) + "│")
        print("│" + "".ljust(width) + "│")

        final_score = summary.get("final_convergence_score")
        if final_score is not None:
            score_line = f"  🎯 Final Convergence: {final_score:.2f}"
            print("│" + score_line.ljust(width) + "│")

        consensus = summary.get("consensus_points", [])
        if consensus:
            print("│" + "  ✅ Consensus:".ljust(width) + "│")
            for pt in consensus:
                for line in textwrap.wrap(pt, width=width - 8):
                    print("│    • " + line.ljust(width - 6) + "│")

        disagreements = summary.get("disagreement_points", [])
        if disagreements:
            print("│" + "  ⚡ Disagreements:".ljust(width) + "│")
            for pt in disagreements:
                for line in textwrap.wrap(pt, width=width - 8):
                    print("│    • " + line.ljust(width - 6) + "│")

        print("╰" + "─" * width + "╯")
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Roundtable demo discussion")
    web_group = parser.add_mutually_exclusive_group()
    web_group.add_argument("--web", dest="web", action="store_true", help="Start the web viewer (default)")
    web_group.add_argument("--no-web", dest="web", action="store_false", help="Run without the web viewer")
    parser.set_defaults(web=True)
    parser.add_argument("--port", type=int, default=8199, help="Preferred web viewer port")
    parser.add_argument("--rounds", type=int, default=3, help="Number of demo rounds")
    return parser


def main() -> None:
    from roundtable.core import RoundtableCore

    args = build_parser().parse_args()
    core = RoundtableCore()
    result = core.run_demo(max_rounds=args.rounds, web=args.web, web_port=args.port)
    if result.get("web_url"):
        print(f"Web viewer: {result['web_url']}")
    else:
        print(f"Web status: {result.get('web_status', 'disabled')}")
        if result.get("web_error"):
            print(f"Web error: {result['web_error']}")
        if result.get("web_help"):
            print(result["web_help"])


if __name__ == "__main__":
    main()
