"""MCP Tool definitions and handlers for Roundtable.

Tool schemas are plain dicts so this module is importable without the
optional `mcp` SDK. The server module wraps them into `mcp.types.Tool`.
"""

from __future__ import annotations

import time
from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "roundtable_register_agent",
        "description": "Register this agent with the Roundtable server. Call on startup to make yourself discoverable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Unique agent identifier"},
                "platform": {"type": "string", "description": "Platform: claude-code|cursor|codex|windsurf|workbuddy"},
                "display_name": {"type": "string", "description": "Human-readable name"},
                "persona": {"type": "object", "description": "Agent persona: {role, avatar, title, description}"},
                "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Capabilities: speak, listen, coordinate"},
                "transport": {"type": "string", "enum": ["stdio", "http"], "default": "stdio"},
                "endpoint": {"type": "string", "description": "Webhook URL for http transport agents"},
            },
            "required": ["agent_id", "platform"],
        },
    },
    {
        "name": "roundtable_list_agents",
        "description": "List registered agents. Use online_only=true to see only active agents.",
        "inputSchema": {
            "type": "object",
            "properties": {"online_only": {"type": "boolean", "default": False}},
        },
    },
    {
        "name": "roundtable_create",
        "description": "Create a new roundtable discussion and optionally invite agents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Discussion topic"},
                "context": {"type": "string", "description": "Additional context"},
                "participants": {"type": "array", "items": {"type": "object"}, "description": "Initial participants [{profile, role, perspective, display_name}]"},
                "max_rounds": {"type": "integer", "default": 3},
                "speech_order": {"type": "string", "default": "fixed"},
                "invite_agents": {"type": "array", "items": {"type": "string"}, "description": "Agent IDs to invite"},
                "created_by": {"type": "string", "description": "Creator agent ID"},
            },
            "required": ["topic", "participants"],
        },
    },
    {
        "name": "roundtable_invite",
        "description": "Invite an agent to join an existing discussion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "agent_id": {"type": "string", "description": "Agent to invite"},
                "role": {"type": "string"},
                "perspective": {"type": "string"},
                "invited_by": {"type": "string", "description": "Inviter agent ID"},
            },
            "required": ["discussion_id", "agent_id", "invited_by"],
        },
    },
    {
        "name": "roundtable_accept_invite",
        "description": "Accept a pending invitation to join a discussion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "agent_id": {"type": "string", "description": "Your agent ID"},
            },
            "required": ["discussion_id", "agent_id"],
        },
    },
    {
        "name": "roundtable_decline_invite",
        "description": "Decline a pending invitation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
            "required": ["discussion_id", "agent_id"],
        },
    },
    {
        "name": "roundtable_inbox",
        "description": "Read your inbox messages (invitations, turn notices, etc). Marks messages as read.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "unread_only": {"type": "boolean", "default": True},
                "mark_read": {"type": "boolean", "default": True},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "roundtable_speak",
        "description": "Record your speech in the discussion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "participant": {"type": "string", "description": "Your participant profile name"},
                "content": {"type": "string", "description": "Your speech content (markdown)"},
                "reply_to": {"type": "integer", "description": "Optional speech ID to reply to"},
            },
            "required": ["discussion_id", "participant", "content"],
        },
    },
    {
        "name": "roundtable_read",
        "description": "Read discussion history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "since_round": {"type": "integer"},
                "participant": {"type": "string"},
            },
            "required": ["discussion_id"],
        },
    },
    {
        "name": "roundtable_status",
        "description": "Get discussion status including convergence metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {"discussion_id": {"type": "string"}},
            "required": ["discussion_id"],
        },
    },
    {
        "name": "roundtable_advance",
        "description": "Manually advance to the next round.",
        "inputSchema": {
            "type": "object",
            "properties": {"discussion_id": {"type": "string"}},
            "required": ["discussion_id"],
        },
    },
    {
        "name": "roundtable_summarize",
        "description": "Get structured summary data for the discussion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "compact": {"type": "boolean", "default": True},
            },
            "required": ["discussion_id"],
        },
    },
    {
        "name": "roundtable_end",
        "description": "End a discussion with an optional conclusion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "conclusion": {"type": "string"},
                "force": {"type": "boolean", "default": False, "description": "Force cancel instead of conclude"},
            },
            "required": ["discussion_id"],
        },
    },
    {
        "name": "roundtable_wait_for_turn",
        "description": "Check if it's your turn to speak. Returns immediately with current state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "agent_id": {"type": "string", "description": "Your participant profile name"},
            },
            "required": ["discussion_id", "agent_id"],
        },
    },
    {
        "name": "roundtable_list",
        "description": "List all discussions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "concluded", "cancelled"]},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
]


def get_mcp_tools() -> list[Any]:
    """Convert TOOL_SCHEMAS to mcp.types.Tool objects (requires mcp SDK)."""
    from mcp.types import Tool
    return [Tool(**schema) for schema in TOOL_SCHEMAS]


def handle_tool_call(core: RoundtableCore, db: RoundtableDB, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call to the appropriate handler."""
    conn = db.connect()
    try:
        if name == "roundtable_register_agent":
            return db.upsert_agent(
                conn,
                agent_id=arguments["agent_id"],
                platform=arguments["platform"],
                display_name=arguments.get("display_name"),
                persona=arguments.get("persona"),
                capabilities=arguments.get("capabilities"),
                transport=arguments.get("transport", "stdio"),
                endpoint=arguments.get("endpoint"),
            )

        elif name == "roundtable_list_agents":
            return {"agents": db.list_agents(conn, online_only=arguments.get("online_only", False))}

        elif name == "roundtable_create":
            result = core.create_discussion(
                topic=arguments["topic"],
                participants=arguments["participants"],
                context=arguments.get("context"),
                max_rounds=arguments.get("max_rounds", 3),
                speech_order=arguments.get("speech_order", "fixed"),
                created_by=arguments.get("created_by", "coordinator"),
            )
            invite_agents = arguments.get("invite_agents", [])
            discussion_id = result.get("discussion_id", "")
            for agent_id in invite_agents:
                _invite_agent(db, conn, discussion_id, agent_id, invited_by=arguments.get("created_by", "coordinator"))
            return result

        elif name == "roundtable_invite":
            return _invite_agent(
                db, conn,
                discussion_id=arguments["discussion_id"],
                agent_id=arguments["agent_id"],
                invited_by=arguments["invited_by"],
                role=arguments.get("role"),
                perspective=arguments.get("perspective"),
            )

        elif name == "roundtable_accept_invite":
            inv = db.get_invitations(conn, agent_id=arguments["agent_id"], discussion_id=arguments["discussion_id"])
            resp = db.respond_invitation(conn, arguments["discussion_id"], arguments["agent_id"], accept=True)
            if "error" not in resp and inv:
                _add_participant_from_invite(db, conn, arguments["discussion_id"], arguments["agent_id"], inv[0])
            return resp

        elif name == "roundtable_decline_invite":
            return db.respond_invitation(conn, arguments["discussion_id"], arguments["agent_id"], accept=False)

        elif name == "roundtable_inbox":
            agent_id = arguments["agent_id"]
            db.touch_agent(conn, agent_id)
            messages = db.read_inbox(conn, agent_id, unread_only=arguments.get("unread_only", True))
            if arguments.get("mark_read", True) and messages:
                db.mark_inbox_read(conn, [m["id"] for m in messages])
            return {"messages": messages}

        elif name == "roundtable_speak":
            return core.speak(
                discussion_id=arguments["discussion_id"],
                participant=arguments["participant"],
                content=arguments["content"],
                reply_to=arguments.get("reply_to"),
            )

        elif name == "roundtable_read":
            return core.read(
                discussion_id=arguments["discussion_id"],
                since_round=arguments.get("since_round"),
                participant=arguments.get("participant"),
            )

        elif name == "roundtable_status":
            return core.status(arguments["discussion_id"])

        elif name == "roundtable_advance":
            return core.advance(arguments["discussion_id"])

        elif name == "roundtable_summarize":
            return core.summarize(arguments["discussion_id"], compact=arguments.get("compact", True))

        elif name == "roundtable_end":
            return core.end_discussion(
                arguments["discussion_id"],
                conclusion=arguments.get("conclusion"),
                force=arguments.get("force", False),
            )

        elif name == "roundtable_wait_for_turn":
            return _check_turn(core, arguments["discussion_id"], arguments["agent_id"])

        elif name == "roundtable_list":
            return core.list_discussions(
                status=arguments.get("status"),
                limit=arguments.get("limit", 20),
            )

        else:
            return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def _invite_agent(
    db: RoundtableDB,
    conn: Any,
    discussion_id: str,
    agent_id: str,
    invited_by: str,
    role: str | None = None,
    perspective: str | None = None,
) -> dict[str, Any]:
    result = db.create_invitation(
        conn, discussion_id, agent_id, invited_by,
        role=role, perspective=perspective,
    )
    db.push_inbox(
        conn, agent_id, "invitation",
        payload={
            "discussion_id": discussion_id,
            "invited_by": invited_by,
            "role": role,
            "perspective": perspective,
        },
        discussion_id=discussion_id,
    )
    return result


def _add_participant_from_invite(
    db: RoundtableDB, conn: Any, discussion_id: str, agent_id: str, invitation: dict[str, Any]
) -> None:
    now = int(time.time())
    conn.execute(
        """INSERT OR IGNORE INTO participants
           (discussion_id, participant, role, perspective, display_name, joined_at, is_active)
           VALUES (?, ?, ?, ?, ?, ?, 1)""",
        (discussion_id, agent_id, invitation.get("role"), invitation.get("perspective"), agent_id, now),
    )


def _check_turn(core: RoundtableCore, discussion_id: str, agent_id: str) -> dict[str, Any]:
    status = core.status(discussion_id)
    if not status.get("ok"):
        return status
    next_speaker = status.get("next_speaker")
    return {
        "your_turn": next_speaker == agent_id,
        "next_speaker": next_speaker,
        "current_round": status.get("current_round"),
        "status": status.get("status"),
    }
