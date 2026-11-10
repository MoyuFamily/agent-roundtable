from __future__ import annotations

from typing import Any

from roundtable.models import ConvergenceRecord, Discussion, Finding, Participant, Speech, review_round_counts


def format_history(speeches: list[Speech], participants_map: dict[str, Any]) -> str:
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
    *,
    context_history: list[dict[str, Any]] | None = None,
    findings: list[Finding] | None = None,
) -> str:
    """Format recorded evidence; only speech excerpts are truncated, never the conclusion."""
    lines = []
    lines.append(f"# 圆桌讨论摘要: {disc.topic}")
    if disc.context:
        lines.append(f"\n**当前背景**: {disc.context}")
    if context_history and len(context_history) > 1:
        lines.append("\n## 背景修订记录")
        lines.append("当前背景取代旧版本中的冲突信息；历史发言保留当时的判断。")
        for revision in context_history:
            lines.append(f"- v{revision['revision']} · {revision['source']}: {revision['reason'] or '未填写原因'}")

    lines.append("\n## 最终结论")
    lines.append(disc.conclusion if disc.conclusion is not None else "尚未记录结论；会议结束不等于已形成决策建议。")
    lines.append("\n以下为已记录材料的整理，不自动判断共识、证据真伪或用户是否批准建议。")

    # Participants
    lines.append("\n## 参与者")
    for p in participants:
        name = p.display_name or p.participant
        role = p.role or "未指定"
        perspective = p.perspective or ""
        persp_str = f" — {perspective}" if perspective else ""
        lines.append(f"- **{name}** ({role}){persp_str}")

    # Per-round summary (key points only, truncate content)
    counts = review_round_counts(disc, speeches)
    lines.append(f"\n## 讨论轮次 (共 {counts['total_rounds']} 轮，已结束 {counts['completed_rounds']} 轮；不含开场)")
    rounds_dict: dict[int, list[Speech]] = {}
    for s in speeches:
        rounds_dict.setdefault(s.round, []).append(s)

    for rnd in sorted(rounds_dict.keys()):
        round_speeches = rounds_dict[rnd]
        lines.append("\n### 开场 (Round 0)" if rnd == 0 else f"\n### Round {rnd}")
        for s in round_speeches:
            p_info = p_map.get(s.participant, {})
            display = p_info.get("display_name", s.participant)
            role = p_info.get("role", "")
            role_str = f" ({role})" if role else ""
            # Truncate content to 300 chars for summary
            content = s.content
            if len(content) > 300:
                content = content[:297] + "... [摘录，请按发言 ID 读取全文]"
            lines.append(f"- [#{s.id}] **{display}**{role_str}: {content}")

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

    if findings:
        lines.append("\n## 标注来源（由协调者或参与者记录）")
        for finding in findings:
            refs = ", ".join(f"#{ref}" for ref in finding.related_speeches or []) or "未关联发言"
            lines.append(f"- 标注 {finding.id} ({finding.type}): {finding.content} — 发言 {refs}")
    elif not (consensus_pts or disagreement_pts or new_points):
        lines.append("\n尚无观点标注；空列表不表示没有分歧。")

    # Convergence
    if final_score is not None:
        lines.append(f"\n## 收敛度: {final_score:.2f}（已记录标注的比例，不代表决策质量）")
    if conv_history:
        for c in conv_history:
            lines.append(
                f"- Round {c.round}: score={c.score:.2f}, "
                f"consensus={c.consensus_count}, disagreement={c.disagreement_count}"
            )
    return "\n".join(lines)
