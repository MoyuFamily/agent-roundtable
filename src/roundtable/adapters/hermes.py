"""Hermes Agent adapter for Roundtable.

Drop-in replacement for hermes tools/roundtable_tools.py that delegates
to the independent roundtable library. Registers all 7 tools with the
Hermes tool registry.

Usage in Hermes:
    - Enable the ``roundtable`` toolset in profile config
    - This module auto-registers when imported by the tool discovery system
"""

from __future__ import annotations

import json
import logging
from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.exceptions import RoundtableError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy core singleton
# ---------------------------------------------------------------------------

_core: RoundtableCore | None = None


def _get_core() -> RoundtableCore:
    global _core
    if _core is None:
        _core = RoundtableCore()
    return _core


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(**fields: Any) -> str:
    return json.dumps({"ok": True, **fields})


def _err(msg: str) -> str:
    return json.dumps({"error": msg})


def _handle(args: dict, method: str, **extra) -> str:
    """Generic handler: call a RoundtableCore method, catch errors."""
    try:
        core = _get_core()
        fn = getattr(core, method)
        result = fn(**{**args, **extra})
        return json.dumps(result)
    except (ValueError, RoundtableError) as e:
        return _err(str(e))
    except Exception as e:
        logger.exception(f"roundtable_{method} failed")
        return _err(f"roundtable_{method}: {e}")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_init(args: dict, **kw) -> str:
    return _handle(args, "create_discussion")


def _handle_speak(args: dict, **kw) -> str:
    return _handle(args, "speak")


def _handle_read(args: dict, **kw) -> str:
    return _handle(args, "read")


def _handle_status(args: dict, **kw) -> str:
    discussion_id = args.get("discussion_id", "").strip()
    if not discussion_id:
        return _err("discussion_id is required")
    return _handle({"discussion_id": discussion_id}, "status")


def _handle_summarize(args: dict, **kw) -> str:
    discussion_id = args.get("discussion_id", "").strip()
    if not discussion_id:
        return _err("discussion_id is required")
    return _handle({"discussion_id": discussion_id}, "summarize")


def _handle_end(args: dict, **kw) -> str:
    return _handle(args, "end_discussion")


def _handle_list(args: dict, **kw) -> str:
    return _handle(args, "list_discussions")


def _handle_advance(args: dict, **kw) -> str:
    discussion_id = args.get("discussion_id", "").strip()
    if not discussion_id:
        return _err("discussion_id is required")
    return _handle({"discussion_id": discussion_id}, "advance")


# ---------------------------------------------------------------------------
# Tool schemas (identical to original)
# ---------------------------------------------------------------------------

ROUNDTABLE_INIT_SCHEMA = {
    "name": "roundtable_init",
    "description": (
        "Create a new roundtable discussion with a topic and participants. "
        "Each participant is an agent profile that will take turns speaking. "
        "Returns the discussion_id for subsequent calls."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "The discussion topic"},
            "participants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string", "description": "Agent profile name"},
                        "role": {"type": "string", "description": "Role description"},
                        "perspective": {"type": "string", "description": "Role perspective hint"},
                        "display_name": {"type": "string", "description": "Display name"},
                    },
                    "required": ["profile"],
                },
                "description": "List of participant profiles (min 2)",
            },
            "context": {"type": "string", "description": "Background context"},
            "max_rounds": {"type": "integer", "description": "Max rounds (default: 5)", "default": 5},
            "speech_order": {
                "type": "string",
                "enum": ["fixed", "random", "priority", "free"],
                "description": "Speech order strategy (default: fixed)",
                "default": "fixed",
            },
            "output_path": {"type": "string", "description": "Path to save conclusion"},
            "created_by": {"type": "string", "description": "Creator profile name"},
        },
        "required": ["topic", "participants"],
    },
}

ROUNDTABLE_SPEAK_SCHEMA = {
    "name": "roundtable_speak",
    "description": (
        "Record a participant's speech in a roundtable discussion. "
        "Automatically tracks rounds and advances when all participants have spoken."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string", "description": "Discussion ID (rt_xxxxxxxx)"},
            "participant": {"type": "string", "description": "Profile name of the speaker"},
            "content": {"type": "string", "description": "Speech content (Markdown supported)"},
            "reply_to": {"type": "integer", "description": "Optional: ID of a speech being referenced"},
        },
        "required": ["discussion_id", "participant", "content"],
    },
}

ROUNDTABLE_READ_SCHEMA = {
    "name": "roundtable_read",
    "description": (
        "Read the discussion history — all speeches or filtered by round/participant. "
        "Returns both structured data and a formatted history string."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string", "description": "Discussion ID (rt_xxxxxxxx)"},
            "since_round": {"type": "integer", "description": "Only speeches from this round onwards"},
            "participant": {"type": "string", "description": "Only speeches from this participant"},
        },
        "required": ["discussion_id"],
    },
}

ROUNDTABLE_STATUS_SCHEMA = {
    "name": "roundtable_status",
    "description": (
        "Get discussion status including current round, convergence score, "
        "consensus/disagreement points, and next speaker."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string", "description": "Discussion ID (rt_xxxxxxxx)"},
        },
        "required": ["discussion_id"],
    },
}

ROUNDTABLE_SUMMARIZE_SCHEMA = {
    "name": "roundtable_summarize",
    "description": (
        "Generate summary data for a conclusion document. Returns all discussion "
        "data organized by round, with consensus/disagreement points extracted."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string", "description": "Discussion ID (rt_xxxxxxxx)"},
        },
        "required": ["discussion_id"],
    },
}

ROUNDTABLE_END_SCHEMA = {
    "name": "roundtable_end",
    "description": (
        "End a roundtable discussion. By default, marks it as concluded. "
        "Use force=true to cancel instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string", "description": "Discussion ID (rt_xxxxxxxx)"},
            "force": {"type": "boolean", "description": "Cancel instead of conclude", "default": False},
            "conclusion": {"type": "string", "description": "Optional: conclusion text"},
        },
        "required": ["discussion_id"],
    },
}

ROUNDTABLE_LIST_SCHEMA = {
    "name": "roundtable_list",
    "description": "List roundtable discussions with optional status filter.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["active", "concluded", "cancelled"],
                "description": "Filter by status (omit for all)",
            },
            "limit": {"type": "integer", "description": "Max results (default: 50)", "default": 50},
        },
    },
}

ROUNDTABLE_ADVANCE_SCHEMA = {
    "name": "roundtable_advance",
    "description": (
        "Explicitly advance to the next round. Use when auto-advance "
        "doesn't trigger. If max_rounds is exceeded, the discussion "
        "is automatically concluded."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "discussion_id": {"type": "string", "description": "Discussion ID (rt_xxxxxxxx)"},
        },
        "required": ["discussion_id"],
    },
}


# ---------------------------------------------------------------------------
# Registration function — called by Hermes tool discovery
# ---------------------------------------------------------------------------


def register_roundtable_tools(registry, *, check_fn=None):
    """Register all 8 roundtable tools with a Hermes tool registry.

    Args:
        registry: The Hermes tools.registry object.
        check_fn: Optional gating function. If None, always enabled.
    """
    tools = [
        ("roundtable_init", ROUNDTABLE_INIT_SCHEMA, _handle_init, "🎯"),
        ("roundtable_speak", ROUNDTABLE_SPEAK_SCHEMA, _handle_speak, "💬"),
        ("roundtable_read", ROUNDTABLE_READ_SCHEMA, _handle_read, "📖"),
        ("roundtable_status", ROUNDTABLE_STATUS_SCHEMA, _handle_status, "📊"),
        ("roundtable_summarize", ROUNDTABLE_SUMMARIZE_SCHEMA, _handle_summarize, "📝"),
        ("roundtable_end", ROUNDTABLE_END_SCHEMA, _handle_end, "🏁"),
        ("roundtable_list", ROUNDTABLE_LIST_SCHEMA, _handle_list, "📋"),
        ("roundtable_advance", ROUNDTABLE_ADVANCE_SCHEMA, _handle_advance, "⏭️"),
    ]
    for name, schema, handler, emoji in tools:
        registry.register(
            name=name,
            toolset="roundtable",
            schema=schema,
            handler=handler,
            check_fn=check_fn,
            emoji=emoji,
        )


# ---------------------------------------------------------------------------
# Auto-registration when imported by Hermes tool discovery
# ---------------------------------------------------------------------------

def _auto_register():
    """Try to auto-register with Hermes if available."""
    try:
        from tools.registry import registry

        def _check_roundtable_enabled() -> bool:
            try:
                from hermes_cli.config import load_config
                cfg = load_config()
                return "roundtable" in cfg.get("toolsets", [])
            except Exception:
                return False

        register_roundtable_tools(registry, check_fn=_check_roundtable_enabled)
    except ImportError:
        # Not running inside Hermes — that's fine, the library works standalone
        pass


_auto_register()
