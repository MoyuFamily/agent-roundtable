"""MCP Prompt definitions for Roundtable.

Prompt specs are plain dicts so this module is importable without the
optional `mcp` SDK.
"""

from __future__ import annotations

from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB

PROMPT_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "coordinator_kickoff",
        "description": "Template for a coordinator to start a roundtable discussion",
        "arguments": [
            {"name": "topic", "description": "Discussion topic", "required": True},
            {"name": "participants", "description": "Comma-separated participant names", "required": True},
            {"name": "max_rounds", "description": "Maximum rounds", "required": False},
        ],
    },
    {
        "name": "participant_turn",
        "description": "Template for a participant when it's their turn to speak",
        "arguments": [
            {"name": "discussion_id", "description": "Discussion ID", "required": True},
            {"name": "role", "description": "Your role in the discussion", "required": True},
            {"name": "perspective", "description": "Your perspective/focus area", "required": False},
        ],
    },
    {
        "name": "coordinator_summarize",
        "description": "Template for the coordinator to summarize and conclude",
        "arguments": [
            {"name": "discussion_id", "description": "Discussion ID", "required": True},
        ],
    },
]


def handle_prompt_call(core: RoundtableCore, db: RoundtableDB, name: str, arguments: dict[str, str]) -> dict[str, str]:
    """Render a prompt template. Returns {description, text}."""
    if name == "coordinator_kickoff":
        return _coordinator_kickoff(arguments)
    elif name == "participant_turn":
        return _participant_turn(core, arguments)
    elif name == "coordinator_summarize":
        return _coordinator_summarize(arguments)
    else:
        return {"description": f"Unknown prompt: {name}", "text": f"Unknown prompt: {name}"}


def _coordinator_kickoff(arguments: dict[str, str]) -> dict[str, str]:
    topic = arguments.get("topic", "")
    participants = arguments.get("participants", "")
    max_rounds = arguments.get("max_rounds", "3")
    text = f"""You are the coordinator of a roundtable discussion.

## Your Task
1. Create the discussion using roundtable_create with the topic below
2. Invite the listed agents using roundtable_invite
3. Manage the discussion rounds — after each round, check status and advance
4. When convergence is high or max rounds reached, summarize and end

## Discussion Setup
- Topic: {topic}
- Participants: {participants}
- Max Rounds: {max_rounds}

## Workflow
1. Call roundtable_create with topic and participants
2. Make your opening statement with roundtable_speak (as coordinator, round 0)
3. Monitor roundtable_inbox or roundtable_status for progress
4. After all rounds, call roundtable_summarize then roundtable_end
"""
    return {"description": f"Coordinator kickoff for: {topic}", "text": text}


def _participant_turn(core: RoundtableCore, arguments: dict[str, str]) -> dict[str, str]:
    discussion_id = arguments.get("discussion_id", "")
    role = arguments.get("role", "participant")
    perspective = arguments.get("perspective", "")

    history_text = ""
    try:
        result = core.read(discussion_id)
        if result.get("ok"):
            speeches = result.get("speeches", [])
            lines = []
            for s in speeches:
                display = s.get("display_name") or s["participant"]
                lines.append(f"- **{display}**: {s['content'][:200]}...")
            history_text = "\n".join(lines[-10:])
    except Exception:
        history_text = "(unable to load history)"

    text = f"""You are participating in a roundtable discussion.

## Your Role: {role}
## Your Perspective: {perspective or 'General'}

## Discussion History (recent)
{history_text}

## Instructions
- Share your viewpoint from your role's perspective (200-500 words)
- Reference or respond to other participants' points
- If you agree, state it explicitly; if you disagree, explain why
- After composing your speech, call roundtable_speak to record it

Call: roundtable_speak(discussion_id="{discussion_id}", participant="<your_profile>", content="<your speech>")
"""
    return {"description": f"Participant turn ({role})", "text": text}


def _coordinator_summarize(arguments: dict[str, str]) -> dict[str, str]:
    discussion_id = arguments.get("discussion_id", "")
    text = f"""Review the discussion and write a conclusion.

1. Call roundtable_summarize(discussion_id="{discussion_id}") to get the structured data
2. Identify consensus points and remaining disagreements
3. Write a brief conclusion (2-3 sentences)
4. Call roundtable_end(discussion_id="{discussion_id}", conclusion="<your conclusion>")
"""
    return {"description": "Coordinator summarize and conclude", "text": text}
