"""Runtime daemon for registered Roundtable agents.

The daemon is intentionally small: it registers an agent, refreshes heartbeat
state, polls inbox messages, and accepts summons/invitations according to the
configured policy. Speech generation remains the responsibility of the host app.
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.tools import handle_tool_call

logger = logging.getLogger(__name__)


class AgentDaemon:
    """Register and keep a non-HTTP agent available for summons."""

    def __init__(
        self,
        *,
        agent_id: str,
        platform: str,
        db: RoundtableDB | None = None,
        display_name: str | None = None,
        skills: list[str] | None = None,
        capabilities: list[str] | None = None,
        availability: str = "idle",
        accept_policy: str = "auto",
        transport: str = "stdio",
        endpoint: str | None = None,
        poll_interval: float = 2.0,
    ):
        self.agent_id = agent_id
        self.platform = platform
        self.db = db or RoundtableDB()
        self.core = RoundtableCore(db=self.db)
        self.display_name = display_name or agent_id
        self.skills = skills or ["agent-roundtable"]
        self.capabilities = capabilities or ["speak", "listen"]
        self.availability = availability
        self.accept_policy = accept_policy
        self.transport = transport
        self.endpoint = endpoint
        self.poll_interval = max(0.1, float(poll_interval))

    def register(self) -> dict[str, Any]:
        return handle_tool_call(
            self.core,
            self.db,
            "roundtable_register_agent",
            {
                "agent_id": self.agent_id,
                "platform": self.platform,
                "display_name": self.display_name,
                "capabilities": self.capabilities,
                "transport": self.transport,
                "endpoint": self.endpoint,
                "skills": self.skills,
                "availability": self.availability,
                "accept_policy": self.accept_policy,
            },
        )

    def heartbeat(self) -> dict[str, Any]:
        return handle_tool_call(
            self.core,
            self.db,
            "roundtable_heartbeat",
            {
                "agent_id": self.agent_id,
                "availability": self.availability,
                "metadata": {"skills": self.skills, "accept_policy": self.accept_policy},
            },
        )

    def tick(self) -> dict[str, Any]:
        """Run one deterministic daemon cycle."""
        self.heartbeat()
        inbox = handle_tool_call(
            self.core,
            self.db,
            "roundtable_inbox",
            {"agent_id": self.agent_id, "unread_only": True, "mark_read": True},
        )
        messages = inbox.get("messages", [])
        handled = [self._handle_message(message) for message in messages]
        return {"agent_id": self.agent_id, "messages": messages, "handled": handled}

    def run_forever(self) -> None:
        self.register()
        logger.info("Roundtable agent daemon registered: %s", self.agent_id)
        while True:
            self.tick()
            time.sleep(self.poll_interval)

    def _handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        payload = message.get("payload") or {}
        msg_type = message.get("type")
        if self.accept_policy != "auto":
            return {"message_id": message.get("id"), "status": "ignored", "reason": "manual_accept_required"}

        if msg_type == "summon" and payload.get("discussion_id"):
            result = handle_tool_call(
                self.core,
                self.db,
                "roundtable_accept_summon",
                {
                    "discussion_id": payload["discussion_id"],
                    "agent_id": self.agent_id,
                    "metadata": {"source": "agent_daemon", "summon_id": payload.get("summon_id")},
                },
            )
            return {"message_id": message.get("id"), "type": msg_type, "result": result}

        if msg_type == "invitation" and payload.get("discussion_id"):
            result = handle_tool_call(
                self.core,
                self.db,
                "roundtable_accept_invite",
                {"discussion_id": payload["discussion_id"], "agent_id": self.agent_id},
            )
            return {"message_id": message.get("id"), "type": msg_type, "result": result}

        return {"message_id": message.get("id"), "status": "ignored", "type": msg_type}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roundtable agent daemon")
    parser.add_argument("--agent-id", required=True, help="Unique agent identifier")
    parser.add_argument("--platform", required=True, help="Platform name, e.g. codex or claude-code")
    parser.add_argument("--db", type=str, default=None, help="SQLite database path")
    parser.add_argument("--display-name", default=None, help="Human-readable agent name")
    parser.add_argument("--skill", action="append", dest="skills", help="Installed skill; can be repeated")
    parser.add_argument("--availability", default="idle", help="Runtime availability")
    parser.add_argument("--accept-policy", default="auto", choices=["auto", "manual", "never"], help="Summon policy")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "http"], help="Agent transport")
    parser.add_argument("--endpoint", default=None, help="HTTP endpoint when transport=http")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Inbox polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run one heartbeat/inbox cycle and exit")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    daemon = AgentDaemon(
        agent_id=args.agent_id,
        platform=args.platform,
        db=RoundtableDB(args.db),
        display_name=args.display_name,
        skills=args.skills or ["agent-roundtable"],
        availability=args.availability,
        accept_policy=args.accept_policy,
        transport=args.transport,
        endpoint=args.endpoint,
        poll_interval=args.poll_interval,
    )
    registration = daemon.register()
    if args.once:
        result = daemon.tick()
        print({"registration": registration, "tick": result})
        return
    daemon.run_forever()


if __name__ == "__main__":
    main()
