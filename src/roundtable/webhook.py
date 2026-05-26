"""Webhook notification sender for Discord and Slack.

Zero external dependencies — uses only urllib from stdlib.
Supports Discord webhooks (embeds) and Slack webhooks (Block Kit).

Usage:
    from roundtable.webhook import WebhookSender

    sender = WebhookSender()
    sender.send_discord("https://discord.com/api/webhooks/...", embed={...})
    sender.send_slack("https://hooks.slack.com/services/...", blocks=[...])
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WebhookSender
# ---------------------------------------------------------------------------


class WebhookSender:
    """Sends webhook notifications to Discord and Slack.

    All sends are fire-and-forget: exceptions are caught and logged,
    never propagated to the caller.

    Args:
        timeout: HTTP request timeout in seconds (default 10).
    """

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Discord
    # ------------------------------------------------------------------

    def send_discord(
        self,
        webhook_url: str,
        *,
        content: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Send a message to a Discord webhook.

        Args:
            webhook_url: Full Discord webhook URL.
            content: Plain text content (max 2000 chars).
            embeds: List of embed objects.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not webhook_url:
            return False

        payload: dict[str, Any] = {}
        if content:
            payload["content"] = content[:2000]
        if embeds:
            payload["embeds"] = embeds[:10]  # Discord limit

        if not payload:
            return False

        return self._post_json(webhook_url, payload)

    # ------------------------------------------------------------------
    # Slack
    # ------------------------------------------------------------------

    def send_slack(
        self,
        webhook_url: str,
        *,
        text: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Send a message to a Slack incoming webhook.

        Args:
            webhook_url: Full Slack webhook URL.
            text: Fallback text (required by Slack).
            blocks: Block Kit blocks array.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not webhook_url:
            return False

        payload: dict[str, Any] = {}
        if text:
            payload["text"] = text[:4000]  # Slack practical limit
        if blocks:
            payload["blocks"] = blocks[:50]  # Slack limit

        if not payload:
            return False

        return self._post_json(webhook_url, payload)

    # ------------------------------------------------------------------
    # Generic HTTP POST
    # ------------------------------------------------------------------

    def _post_json(self, url: str, payload: dict[str, Any]) -> bool:
        """POST JSON payload to URL. Returns True on success."""
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                # Discord returns 204, Slack returns 200
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            logger.warning("Webhook HTTP error %s for %s: %s", e.code, url, e.reason)
        except urllib.error.URLError as e:
            logger.warning("Webhook URL error for %s: %s", url, e.reason)
        except Exception as e:
            logger.warning("Webhook send failed for %s: %s", url, e)
        return False


# ---------------------------------------------------------------------------
# Message formatters — produce platform-specific payloads
# ---------------------------------------------------------------------------


def format_discord_embed(
    event: str,
    *,
    discussion_id: str,
    topic: str = "",
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Format a discussion event as a Discord embed object.

    Returns None if event type is unknown.
    """
    short_id = discussion_id[:12] if len(discussion_id) > 12 else discussion_id
    topic_short = topic[:50] + ("..." if len(topic) > 50 else "")

    if event == "round_start":
        round_num = kwargs.get("round_num", "?")
        embed: dict[str, Any] = {
            "title": f"📢 第{round_num}轮讨论开始",
            "description": topic_short or "圆桌讨论",
            "color": 0x5865F2,  # Discord blurple
            "footer": {"text": f"Roundtable · {short_id}"},
        }
        prev_summary = kwargs.get("prev_summary", "")
        if prev_summary:
            embed["fields"] = [{"name": "上轮回顾", "value": prev_summary[:200], "inline": False}]
        return embed

    if event == "speech":
        participant = kwargs.get("participant", "unknown")
        display_name = kwargs.get("display_name", participant)
        role = kwargs.get("role", "")
        round_num = kwargs.get("round_num", "?")
        content = kwargs.get("content", "")
        role_str = f" · {role}" if role else ""
        return {
            "title": f"💬 第{round_num}轮 | {display_name}{role_str}",
            "description": content[:300] + ("..." if len(content) > 300 else ""),
            "color": _role_color_hex(role),
            "footer": {"text": f"Roundtable · {short_id}"},
        }

    if event == "round_end":
        round_num = kwargs.get("round_num", "?")
        convergence = kwargs.get("convergence")
        key_points = kwargs.get("key_points", [])
        fields: list[dict[str, Any]] = []
        if convergence is not None:
            bar = _convergence_bar_text(convergence)
            fields.append({"name": "收敛度", "value": bar, "inline": True})
        if key_points:
            pts = "\n".join(f"• {p[:80]}" for p in key_points[:5])
            fields.append({"name": "本轮关键观点", "value": pts, "inline": False})
        return {
            "title": f"✅ 第{round_num}轮讨论结束",
            "color": 0x57F287,  # Green
            "fields": fields,
            "footer": {"text": f"Roundtable · {short_id}"},
        }

    if event == "concluded":
        conclusion = kwargs.get("conclusion", "")
        convergence = kwargs.get("convergence")
        consensus = kwargs.get("consensus_points", [])
        disagreements = kwargs.get("disagreement_points", [])
        fields_c: list[dict[str, Any]] = []
        if convergence is not None:
            fields_c.append({"name": "最终收敛度", "value": _convergence_bar_text(convergence), "inline": True})
        if conclusion:
            fields_c.append({"name": "结论", "value": conclusion[:300], "inline": False})
        if consensus:
            pts = "\n".join(f"✅ {p[:80]}" for p in consensus[:5])
            fields_c.append({"name": f"共识点({len(consensus)})", "value": pts, "inline": False})
        if disagreements:
            pts = "\n".join(f"⚡ {p[:80]}" for p in disagreements[:5])
            fields_c.append({"name": f"分歧点({len(disagreements)})", "value": pts, "inline": False})
        return {
            "title": "🏁 讨论结束",
            "description": topic_short or "圆桌讨论",
            "color": 0xFEE75C,  # Yellow
            "fields": fields_c,
            "footer": {"text": f"Roundtable · {short_id}"},
        }

    return None


def format_slack_blocks(
    event: str,
    *,
    discussion_id: str,
    topic: str = "",
    **kwargs: Any,
) -> list[dict[str, Any]] | None:
    """Format a discussion event as Slack Block Kit blocks.

    Returns None if event type is unknown.
    """
    short_id = discussion_id[:12] if len(discussion_id) > 12 else discussion_id

    if event == "round_start":
        round_num = kwargs.get("round_num", "?")
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📢 第{round_num}轮讨论开始"},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*{topic[:50]}* · " + f"`{short_id}`"}],
            },
        ]
        prev_summary = kwargs.get("prev_summary", "")
        if prev_summary:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*上轮回顾:*\n{prev_summary[:200]}"},
            })
        return blocks

    if event == "speech":
        participant = kwargs.get("participant", "unknown")
        display_name = kwargs.get("display_name", participant)
        role = kwargs.get("role", "")
        round_num = kwargs.get("round_num", "?")
        content = kwargs.get("content", "")
        role_str = f" · {role}" if role else ""
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*💬 第{round_num}轮 | {display_name}{role_str}*\n{content[:300]}",
                },
            },
        ]

    if event == "round_end":
        round_num = kwargs.get("round_num", "?")
        convergence = kwargs.get("convergence")
        key_points = kwargs.get("key_points", [])
        text = f"*✅ 第{round_num}轮讨论结束*"
        if convergence is not None:
            text += f"\n收敛度: {convergence:.0%}"
        blocks_r: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]
        if key_points:
            pts = "\n".join(f"• {p[:80]}" for p in key_points[:5])
            blocks_r.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*本轮关键观点:*\n{pts}"},
            })
        return blocks_r

    if event == "concluded":
        conclusion = kwargs.get("conclusion", "")
        convergence = kwargs.get("convergence")
        consensus = kwargs.get("consensus_points", [])
        text_c = "*🏁 讨论结束*"
        if convergence is not None:
            text_c += f"\n收敛度: {convergence:.0%}"
        blocks_c: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🏁 讨论结束 — {topic[:50]}"},
            },
        ]
        if conclusion:
            blocks_c.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*结论:*\n{conclusion[:300]}"},
            })
        if consensus:
            pts = "\n".join(f"✅ {p[:80]}" for p in consensus[:5])
            blocks_c.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*共识点({len(consensus)}):*\n{pts}"},
            })
        return blocks_c

    return None


def format_discord_text(event: str, *, discussion_id: str, topic: str = "", **kwargs: Any) -> str | None:
    """Format event as plain text for Discord (fallback when no embeds)."""
    embed = format_discord_embed(event, discussion_id=discussion_id, topic=topic, **kwargs)
    if embed is None:
        return None
    parts = [embed.get("title", "")]
    if embed.get("description"):
        parts.append(embed["description"])
    for field in embed.get("fields", []):
        parts.append(f"{field.get('name', '')}: {field.get('value', '')}")
    return "\n".join(parts)


def format_slack_text(event: str, *, discussion_id: str, topic: str = "", **kwargs: Any) -> str | None:
    """Format event as plain text for Slack (fallback text field)."""
    blocks = format_slack_blocks(event, discussion_id=discussion_id, topic=topic, **kwargs)
    if blocks is None:
        return None
    parts = []
    for block in blocks:
        if block.get("type") == "header" or block.get("type") == "section":
            parts.append(block.get("text", {}).get("text", ""))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _role_color_hex(role: str) -> int:
    """Map role name to a Discord-friendly hex color."""
    r = role.lower() if role else ""
    if "design" in r or "设计" in r:
        return 0xEB459E  # Pink
    if "product" in r or "产品" in r or "总监" in r:
        return 0x5865F2  # Blurple
    if "engineer" in r or "tech" in r or "技术" in r or "开发" in r:
        return 0x57F287  # Green
    if "research" in r or "研究" in r:
        return 0xFEE75C  # Yellow
    if "marketing" in r or "运营" in r:
        return 0xED4245  # Red
    return 0x95A5A6  # Gray


def _convergence_bar_text(score: float) -> str:
    """Visual text bar for convergence score (0-1)."""
    pct = max(0, min(1, score)) * 100
    filled = int(pct / 10)
    empty = 10 - filled
    return f"{'█' * filled}{'░' * empty} {pct:.0f}%"
