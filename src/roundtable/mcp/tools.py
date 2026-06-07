"""MCP Tool definitions and handlers for Roundtable.

Tool schemas are plain dicts so this module is importable without the
optional `mcp` SDK. The server module wraps them into `mcp.types.Tool`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from importlib import import_module
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
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Capabilities: speak, listen, coordinate",
                },
                "transport": {"type": "string", "enum": ["stdio", "http"], "default": "stdio"},
                "endpoint": {"type": "string", "description": "Webhook URL for http transport agents"},
                "metadata": {"type": "object", "description": "Agent registry metadata"},
                "skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Installed skills, e.g. agent-roundtable",
                },
                "skill_versions": {"type": "object", "description": "Skill version map"},
                "roles": {"type": "array", "items": {"type": "string"}, "description": "Preferred roles"},
                "availability": {"type": "string", "description": "idle|busy|offline or platform-specific state"},
                "accept_policy": {"type": "string", "description": "auto|manual|never"},
            },
            "required": ["agent_id", "platform"],
        },
    },
    {
        "name": "roundtable_list_agents",
        "description": "List registered agents. Use filters to discover active agents with a required skill.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "online_only": {"type": "boolean", "default": False},
                "timeout_seconds": {"type": "integer", "default": 90},
                "required_skill": {"type": "string"},
                "availability": {"type": "string"},
            },
        },
    },
    {
        "name": "roundtable_heartbeat",
        "description": "Refresh this agent's runtime presence and availability.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "availability": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["agent_id"],
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
                "participants": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Initial participants [{profile, role, perspective, display_name}]",
                },
                "max_rounds": {"type": "integer", "default": 3},
                "speech_order": {"type": "string", "default": "fixed"},
                "web": {"type": "boolean", "default": False, "description": "Start the Web Viewer for this discussion"},
                "invite_agents": {"type": "array", "items": {"type": "string"}, "description": "Agent IDs to invite"},
                "created_by": {"type": "string", "description": "Creator agent ID"},
                "status": {"type": "string", "enum": ["assembling", "active"], "default": "active"},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "roundtable_summon_agents",
        "description": "Summon registered agents into a dispatch, optionally creating an assembling discussion first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string", "description": "Existing discussion to summon into"},
                "topic": {"type": "string", "description": "Topic when creating a new assembling discussion"},
                "context": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "object"}, "default": []},
                "max_rounds": {"type": "integer", "default": 3},
                "speech_order": {"type": "string", "default": "fixed"},
                "web": {"type": "boolean", "default": False},
                "coordinator_agent_id": {"type": "string"},
                "agent_ids": {"type": "array", "items": {"type": "string"}, "description": "Explicit agents to summon"},
                "required_skill": {"type": "string", "description": "Only summon agents advertising this skill"},
                "availability": {"type": "string", "description": "Only summon agents with this availability"},
                "online_only": {"type": "boolean", "default": True},
                "timeout_seconds": {"type": "integer", "default": 90},
                "dispatch_timeout_seconds": {"type": "integer", "default": 60},
                "mode": {"type": "string", "enum": ["managed", "federated"], "default": "federated"},
                "start_policy": {
                    "type": "string",
                    "enum": ["immediate", "quorum", "all", "timeout"],
                    "default": "quorum",
                },
                "min_accepts": {"type": "integer", "default": 1},
                "role": {"type": "string"},
                "perspective": {"type": "string"},
                "metadata": {"type": "object"},
                "idempotency_key": {"type": "string"},
                "allow_terminal_retry": {
                    "type": "boolean",
                    "default": False,
                    "description": "Release a terminal idempotency_key and create a retry dispatch.",
                },
            },
            "required": ["coordinator_agent_id"],
        },
    },
    {
        "name": "roundtable_dispatch_status",
        "description": "Inspect a dispatch and apply readiness/timeout transitions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dispatch_id": {"type": "string"},
                "discussion_id": {"type": "string"},
            },
        },
    },
    {
        "name": "roundtable_retry_summon",
        "description": "Retry pending, failed, delivered, or timed-out summons without creating duplicate summon rows.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dispatch_id": {"type": "string"},
                "summon_id": {"type": "string"},
                "discussion_id": {"type": "string"},
                "agent_ids": {"type": "array", "items": {"type": "string"}},
                "statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["pending", "delivered", "failed", "timeout"],
                },
                "retry_timeout_seconds": {"type": "integer", "default": 60},
                "requeue_inbox": {"type": "boolean", "default": True},
                "redeliver_http": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "roundtable_accept_summon",
        "description": "Accept a summon and join its discussion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["discussion_id", "agent_id"],
        },
    },
    {
        "name": "roundtable_decline_summon",
        "description": "Decline a summon.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["discussion_id", "agent_id"],
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
        "description": "Check if it's your turn to speak, optionally polling briefly until the turn arrives.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "discussion_id": {"type": "string"},
                "agent_id": {"type": "string", "description": "Your participant profile name"},
                "wait_seconds": {
                    "type": "number",
                    "default": 0,
                    "description": "Optional max seconds to poll until your turn before returning",
                },
                "poll_interval": {
                    "type": "number",
                    "default": 1,
                    "description": "Polling interval in seconds when wait_seconds > 0",
                },
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
                "status": {"type": "string", "enum": ["assembling", "active", "concluded", "cancelled"]},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
]


def get_mcp_tools() -> list[Any]:
    """Convert TOOL_SCHEMAS to mcp.types.Tool objects (requires mcp SDK)."""
    tool_cls = import_module("mcp.types").Tool

    return [tool_cls(**schema) for schema in TOOL_SCHEMAS]


def handle_tool_call(core: RoundtableCore, db: RoundtableDB, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call to the appropriate handler."""
    conn = db.connect()
    try:
        if name == "roundtable_register_agent":
            metadata = _agent_metadata_from_arguments(arguments)
            return db.upsert_agent(
                conn,
                agent_id=arguments["agent_id"],
                platform=arguments["platform"],
                display_name=arguments.get("display_name"),
                persona=arguments.get("persona"),
                capabilities=arguments.get("capabilities"),
                transport=arguments.get("transport", "stdio"),
                endpoint=arguments.get("endpoint"),
                metadata=metadata,
            )

        elif name == "roundtable_list_agents":
            return {
                "agents": db.list_agents(
                    conn,
                    online_only=arguments.get("online_only", False),
                    timeout_seconds=arguments.get("timeout_seconds", 90),
                    required_skill=arguments.get("required_skill"),
                    availability=arguments.get("availability"),
                )
            }

        elif name == "roundtable_heartbeat":
            return db.heartbeat_agent(
                conn,
                arguments["agent_id"],
                availability=arguments.get("availability"),
                metadata=arguments.get("metadata"),
            )

        elif name == "roundtable_create":
            result = core.create_discussion(
                topic=arguments["topic"],
                participants=arguments.get("participants", []),
                context=arguments.get("context"),
                max_rounds=arguments.get("max_rounds", 3),
                speech_order=arguments.get("speech_order", "fixed"),
                created_by=arguments.get("created_by", "coordinator"),
                status=arguments.get("status", "active"),
                web=arguments.get("web", False),
            )
            invite_agents = arguments.get("invite_agents", [])
            discussion_id = result.get("discussion_id", "")
            invite_results = []
            for agent_id in invite_agents:
                invite_results.append(
                    _invite_agent(
                        db,
                        conn,
                        discussion_id,
                        agent_id,
                        invited_by=arguments.get("created_by", "coordinator"),
                    )
                )
            if invite_results:
                result["invites"] = invite_results
            return result

        elif name == "roundtable_summon_agents":
            return _summon_agents(core, db, conn, arguments)

        elif name == "roundtable_dispatch_status":
            return _dispatch_status(db, conn, arguments)

        elif name == "roundtable_retry_summon":
            return _retry_summon(core, db, conn, arguments)

        elif name == "roundtable_accept_summon":
            result = db.respond_summon(
                conn,
                arguments["discussion_id"],
                arguments["agent_id"],
                accept=True,
                metadata=arguments.get("metadata"),
            )
            dispatch_id = result.get("dispatch_id") if isinstance(result, dict) else None
            if dispatch_id:
                result["dispatch"] = db.apply_dispatch_readiness(conn, dispatch_id)
            core._sync_web_discussion_state(arguments["discussion_id"], conn)
            return result

        elif name == "roundtable_decline_summon":
            result = db.respond_summon(
                conn,
                arguments["discussion_id"],
                arguments["agent_id"],
                accept=False,
                metadata=arguments.get("metadata"),
            )
            dispatch_id = result.get("dispatch_id") if isinstance(result, dict) else None
            if dispatch_id:
                result["dispatch"] = db.apply_dispatch_readiness(conn, dispatch_id)
            core._sync_web_discussion_state(arguments["discussion_id"], conn)
            return result

        elif name == "roundtable_invite":
            return _invite_agent(
                db,
                conn,
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
            result = core.speak(
                discussion_id=arguments["discussion_id"],
                participant=arguments["participant"],
                content=arguments["content"],
                reply_to=arguments.get("reply_to"),
            )
            next_speaker = result.get("next_speaker")
            if next_speaker:
                speech_round = int(result.get("round", 0))
                notice_round = speech_round + 1 if result.get("round_complete") else speech_round
                result["turn_notice"] = _notify_next_speaker(
                    db,
                    conn,
                    arguments["discussion_id"],
                    str(next_speaker),
                    notice_round,
                )
            return result

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
            return _check_turn(
                core,
                arguments["discussion_id"],
                arguments["agent_id"],
                wait_seconds=arguments.get("wait_seconds", 0),
                poll_interval=arguments.get("poll_interval", 1),
            )

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


def _agent_metadata_from_arguments(arguments: dict[str, Any]) -> dict[str, Any] | None:
    metadata = dict(arguments.get("metadata") or {})
    for key in ("skills", "skill_versions", "roles", "availability", "accept_policy"):
        value = arguments.get(key)
        if value is not None:
            metadata[key] = value
    return metadata or None


def _summon_agents(core: RoundtableCore, db: RoundtableDB, conn: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    discussion_id = arguments.get("discussion_id")
    created = None
    if not discussion_id:
        if not arguments.get("topic"):
            return {"error": "topic is required when discussion_id is not provided"}
        created = core.create_discussion(
            topic=arguments["topic"],
            participants=arguments.get("participants", []),
            context=arguments.get("context"),
            max_rounds=arguments.get("max_rounds", 3),
            speech_order=arguments.get("speech_order", "fixed"),
            created_by=arguments["coordinator_agent_id"],
            status="assembling",
            web=arguments.get("web", False),
        )
        discussion_id = created["discussion_id"]

    agents = _select_summon_agents(db, conn, arguments)
    if not agents:
        return {
            "ok": False,
            "error": "No matching agents found",
            "discussion_id": discussion_id,
            "created": created,
        }

    dispatch = db.create_dispatch(
        conn,
        discussion_id,
        arguments["coordinator_agent_id"],
        mode=arguments.get("mode", "federated"),
        start_policy=arguments.get("start_policy", "quorum"),
        min_accepts=arguments.get("min_accepts", 1),
        timeout_seconds=arguments.get("dispatch_timeout_seconds", 60),
        idempotency_key=arguments.get("idempotency_key"),
        allow_terminal_retry=arguments.get("allow_terminal_retry", False),
        metadata=arguments.get("metadata"),
    )

    summons = []
    deliveries = []
    expires_at = int(time.time()) + int(arguments.get("dispatch_timeout_seconds", 60))
    for agent in agents:
        summon = db.create_summon(
            conn,
            discussion_id,
            agent["agent_id"],
            arguments["coordinator_agent_id"],
            dispatch_id=dispatch["id"],
            role=arguments.get("role"),
            perspective=arguments.get("perspective"),
            required_skill=arguments.get("required_skill"),
            expires_at=expires_at,
            allow_terminal_retry=arguments.get("allow_terminal_retry", False),
            metadata=arguments.get("metadata"),
        )
        summons.append(summon)
        inbox_id = db.push_inbox(
            conn,
            agent["agent_id"],
            "summon",
            payload={
                "summon_id": summon["id"],
                "dispatch_id": dispatch["id"],
                "discussion_id": discussion_id,
                "invited_by": arguments["coordinator_agent_id"],
                "role": summon.get("role"),
                "perspective": summon.get("perspective"),
                "required_skill": summon.get("required_skill"),
                "expires_at": summon.get("expires_at"),
            },
            discussion_id=discussion_id,
        )
        delivery = _deliver_http_summon(db, conn, summon["id"])
        if delivery:
            deliveries.append(delivery)
        else:
            deliveries.append({"agent_id": agent["agent_id"], "inbox_message_id": inbox_id})

    readiness = db.apply_dispatch_readiness(conn, dispatch["id"])
    core._sync_web_discussion_state(discussion_id, conn)
    return {
        "ok": True,
        "discussion_id": discussion_id,
        "created": created,
        "dispatch": readiness.get("dispatch") or dispatch,
        "readiness": readiness.get("readiness"),
        "summons": db.get_summons(conn, dispatch_id=dispatch["id"]),
        "deliveries": deliveries,
    }


def _select_summon_agents(db: RoundtableDB, conn: Any, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_ids = arguments.get("agent_ids") or []
    if explicit_ids:
        agents = []
        for agent_id in explicit_ids:
            agent = db.get_agent(conn, agent_id)
            if agent:
                agents.append(agent)
    else:
        agents = db.list_agents(
            conn,
            online_only=arguments.get("online_only", True),
            timeout_seconds=arguments.get("timeout_seconds", 90),
            required_skill=arguments.get("required_skill"),
            availability=arguments.get("availability"),
        )

    selected = []
    required_skill = arguments.get("required_skill")
    availability = arguments.get("availability")
    coordinator = arguments.get("coordinator_agent_id")
    for agent in agents:
        if agent["agent_id"] == coordinator:
            continue
        if required_skill and required_skill not in agent.get("skills", []):
            continue
        if availability and agent.get("availability") != availability:
            continue
        selected.append(agent)
    return selected


def _dispatch_status(db: RoundtableDB, conn: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    dispatch_ids = []
    if arguments.get("dispatch_id"):
        dispatch_ids.append(arguments["dispatch_id"])
    elif arguments.get("discussion_id"):
        dispatch_ids.extend(d["id"] for d in db.list_dispatches(conn, discussion_id=arguments["discussion_id"]))
    else:
        return {"error": "dispatch_id or discussion_id is required"}

    results = []
    for dispatch_id in dispatch_ids:
        status = db.apply_dispatch_readiness(conn, dispatch_id)
        dispatch = status.get("dispatch")
        results.append(
            {
                **status,
                "summons": db.get_summons(conn, dispatch_id=dispatch_id),
                "events": db.list_summon_events(conn, dispatch_id=dispatch_id),
                "discussion_id": dispatch.get("discussion_id") if dispatch else None,
            }
        )
    return {"ok": True, "dispatches": results, "count": len(results)}


def _retry_summon(core: RoundtableCore, db: RoundtableDB, conn: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    summons = _select_retry_summons(db, conn, arguments)
    if isinstance(summons, dict):
        return summons

    retryable_statuses = {"pending", "delivered", "failed", "timeout"}
    requested_statuses = set(arguments.get("statuses") or ["pending", "delivered", "failed", "timeout"])
    retry_statuses = requested_statuses & retryable_statuses
    agent_ids = set(arguments.get("agent_ids") or [])
    retry_timeout_seconds = int(arguments.get("retry_timeout_seconds", 60))
    expires_at = int(time.time()) + max(0, retry_timeout_seconds) if retry_timeout_seconds >= 0 else None
    requeue_inbox = arguments.get("requeue_inbox", True)
    redeliver_http = arguments.get("redeliver_http", True)

    retried = []
    skipped = []
    deliveries = []
    dispatch_ids: set[str] = set()
    discussion_ids: set[str] = set()
    for summon in summons:
        if agent_ids and summon["agent_id"] not in agent_ids:
            skipped.append({"summon_id": summon["id"], "agent_id": summon["agent_id"], "reason": "agent_filtered"})
            continue
        if summon["status"] not in retry_statuses:
            skipped.append(
                {
                    "summon_id": summon["id"],
                    "agent_id": summon["agent_id"],
                    "status": summon["status"],
                    "reason": "status_not_retryable",
                }
            )
            continue

        if summon.get("dispatch_id"):
            db.reopen_dispatch_for_retry(
                conn,
                summon["dispatch_id"],
                retry_timeout_seconds=retry_timeout_seconds,
            )
            dispatch_ids.add(summon["dispatch_id"])
        discussion_ids.add(summon["discussion_id"])
        reset = db.reset_summon_for_retry(
            conn,
            summon["id"],
            expires_at=expires_at,
            payload={"previous_status": summon["status"], "retry_timeout_seconds": retry_timeout_seconds},
        )
        if not reset:
            skipped.append({"summon_id": summon["id"], "agent_id": summon["agent_id"], "reason": "not_found"})
            continue

        delivery: dict[str, Any] = {"agent_id": summon["agent_id"], "summon_id": summon["id"]}
        if requeue_inbox:
            inbox_id = db.push_inbox(
                conn,
                summon["agent_id"],
                "summon",
                payload={
                    "summon_id": summon["id"],
                    "dispatch_id": summon.get("dispatch_id"),
                    "discussion_id": summon["discussion_id"],
                    "invited_by": summon["invited_by"],
                    "role": summon.get("role"),
                    "perspective": summon.get("perspective"),
                    "required_skill": summon.get("required_skill"),
                    "expires_at": expires_at,
                    "retry": True,
                },
                discussion_id=summon["discussion_id"],
            )
            delivery["inbox_message_id"] = inbox_id
        if redeliver_http:
            http_delivery = _deliver_http_summon(db, conn, summon["id"])
            if http_delivery:
                delivery["http"] = http_delivery
        deliveries.append(delivery)
        retried.append(db.get_summon(conn, summon["id"]) or reset)

    dispatch_results = []
    for dispatch_id in sorted(dispatch_ids):
        dispatch_results.append(db.apply_dispatch_readiness(conn, dispatch_id))
    for discussion_id in sorted(discussion_ids):
        core._sync_web_discussion_state(discussion_id, conn)

    return {
        "ok": True,
        "retried": retried,
        "skipped": skipped,
        "deliveries": deliveries,
        "dispatches": dispatch_results,
        "count": len(retried),
    }


def _select_retry_summons(
    db: RoundtableDB,
    conn: Any,
    arguments: dict[str, Any],
) -> list[dict[str, Any]] | dict[str, Any]:
    if arguments.get("summon_id"):
        summon = db.get_summon(conn, arguments["summon_id"])
        return [summon] if summon else {"error": "summon not found"}
    if arguments.get("dispatch_id"):
        return db.get_summons(conn, dispatch_id=arguments["dispatch_id"])
    if arguments.get("discussion_id"):
        return db.get_summons(conn, discussion_id=arguments["discussion_id"])
    return {"error": "summon_id, dispatch_id, or discussion_id is required"}


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
        conn,
        discussion_id,
        agent_id,
        invited_by,
        role=role,
        perspective=perspective,
    )
    db.push_inbox(
        conn,
        agent_id,
        "invitation",
        payload={
            "discussion_id": discussion_id,
            "invited_by": invited_by,
            "role": role,
            "perspective": perspective,
        },
        discussion_id=discussion_id,
    )
    delivery = _deliver_http_invitation(db, conn, agent_id, discussion_id, invited_by, role, perspective)
    if delivery:
        result["delivery"] = delivery
    return result


def _add_participant_from_invite(
    db: RoundtableDB, conn: Any, discussion_id: str, agent_id: str, invitation: dict[str, Any]
) -> None:
    db.add_participant(
        conn,
        discussion_id,
        agent_id,
        role=invitation.get("role"),
        perspective=invitation.get("perspective"),
        display_name=agent_id,
    )


def _deliver_http_invitation(
    db: RoundtableDB,
    conn: Any,
    agent_id: str,
    discussion_id: str,
    invited_by: str,
    role: str | None,
    perspective: str | None,
) -> dict[str, Any] | None:
    agent = db.get_agent(conn, agent_id, include_private=True)
    if not agent or agent.get("transport") != "http" or not agent.get("endpoint"):
        return None

    payload = {
        "type": "invitation",
        "discussion_id": discussion_id,
        "agent_id": agent_id,
        "invited_by": invited_by,
        "role": role,
        "perspective": perspective,
    }
    url = f"{str(agent['endpoint']).rstrip('/')}/invite"
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=_http_headers_for_agent(agent),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read().decode("utf-8")
        return {"transport": "http", "endpoint": url, "ok": True, "response": body}
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {"transport": "http", "endpoint": url, "ok": False, "error": str(exc)}


def _deliver_http_summon(db: RoundtableDB, conn: Any, summon_id: str) -> dict[str, Any] | None:
    summon = db.get_summon(conn, summon_id)
    if not summon:
        return None
    agent = db.get_agent(conn, summon["agent_id"], include_private=True)
    if not agent or agent.get("transport") != "http" or not agent.get("endpoint"):
        return None

    payload = {
        "type": "summon",
        "summon_id": summon["id"],
        "dispatch_id": summon["dispatch_id"],
        "discussion_id": summon["discussion_id"],
        "agent_id": summon["agent_id"],
        "invited_by": summon["invited_by"],
        "role": summon["role"],
        "perspective": summon["perspective"],
        "required_skill": summon["required_skill"],
        "expires_at": summon["expires_at"],
    }
    url = f"{str(agent['endpoint']).rstrip('/')}/summon"
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=_http_headers_for_agent(agent),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read().decode("utf-8")
        delivery = {"agent_id": summon["agent_id"], "transport": "http", "endpoint": url, "ok": True, "response": body}
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        delivery = {
            "agent_id": summon["agent_id"],
            "transport": "http",
            "endpoint": url,
            "ok": False,
            "error": str(exc),
        }
    db.mark_summon_delivered(conn, summon_id, delivery, transport="http", endpoint=url)
    return delivery


def _notify_next_speaker(
    db: RoundtableDB,
    conn: Any,
    discussion_id: str,
    agent_id: str,
    round_num: Any,
) -> dict[str, Any]:
    agent = db.get_agent(conn, agent_id, include_private=True)
    if not agent:
        return {"skipped": True, "reason": "agent_not_registered"}

    payload = {
        "discussion_id": discussion_id,
        "agent_id": agent_id,
        "round": round_num,
    }
    message_id = db.push_inbox(conn, agent_id, "turn", payload=payload, discussion_id=discussion_id)
    result: dict[str, Any] = {"inbox_message_id": message_id}

    if agent.get("transport") != "http" or not agent.get("endpoint"):
        return result

    url = f"{str(agent['endpoint']).rstrip('/')}/turn"
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps({"type": "turn", **payload}).encode(),
            headers=_http_headers_for_agent(agent),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            body = response.read().decode("utf-8")
        result["delivery"] = {"transport": "http", "endpoint": url, "ok": True, "response": body}
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        result["delivery"] = {"transport": "http", "endpoint": url, "ok": False, "error": str(exc)}
    return result


def _http_headers_for_agent(agent: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    metadata = agent.get("metadata") or {}
    token = (
        metadata.get("_bridge_auth_token")
        or metadata.get("bridge_auth_token")
        or metadata.get("auth_token")
        or metadata.get("roundtable_auth_token")
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _check_turn(
    core: RoundtableCore,
    discussion_id: str,
    agent_id: str,
    *,
    wait_seconds: float | int = 0,
    poll_interval: float | int = 1,
) -> dict[str, Any]:
    deadline = time.time() + max(0.0, float(wait_seconds or 0))
    interval = min(max(0.1, float(poll_interval or 1)), 5.0)

    while True:
        status = core.status(discussion_id)
        if not status.get("ok"):
            return status
        next_speaker = status.get("next_speaker")
        if next_speaker == agent_id or status.get("status") != "active" or time.time() >= deadline:
            break
        time.sleep(interval)

    return {
        "your_turn": next_speaker == agent_id,
        "next_speaker": next_speaker,
        "current_round": status.get("current_round"),
        "status": status.get("status"),
        "waited": wait_seconds,
    }
