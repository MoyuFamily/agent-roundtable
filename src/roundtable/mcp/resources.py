"""MCP Resource definitions and handlers for Roundtable.

Resource specs are plain dicts so this module is importable without the
optional `mcp` SDK.
"""

from __future__ import annotations

from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB

RESOURCE_URIS: list[dict[str, str]] = [
    {
        "uri": "roundtable://agents",
        "name": "Registered Agents",
        "description": "All registered agents and their online status",
    },
    {
        "uri": "roundtable://discussions",
        "name": "Discussions",
        "description": "List of all discussions",
    },
]


def handle_resource_read(core: RoundtableCore, db: RoundtableDB, uri: str) -> Any:
    """Read a resource by URI."""
    conn = db.connect()
    try:
        if uri == "roundtable://agents":
            return {"agents": db.list_agents(conn)}

        elif uri == "roundtable://discussions":
            return core.list_discussions()

        elif uri.startswith("roundtable://discussions/"):
            parts = uri.replace("roundtable://discussions/", "").split("/")
            discussion_id = parts[0]
            if len(parts) > 1 and parts[1] == "transcript":
                return _build_transcript(core, discussion_id)
            return core.status(discussion_id)

        elif uri.startswith("roundtable://invitations/"):
            agent_id = uri.replace("roundtable://invitations/", "")
            invitations = db.get_invitations(conn, agent_id=agent_id, status="pending")
            return {"agent_id": agent_id, "pending_invitations": invitations}

        else:
            return {"error": f"Unknown resource: {uri}"}
    finally:
        conn.close()


def _build_transcript(core: RoundtableCore, discussion_id: str) -> dict[str, Any]:
    result = core.read(discussion_id)
    if not result.get("ok"):
        return result
    speeches = result.get("speeches", [])
    lines = [f"# Discussion: {result.get('topic', discussion_id)}\n"]
    current_round = -1
    for s in speeches:
        if s["round"] != current_round:
            current_round = s["round"]
            lines.append(f"\n## Round {current_round}\n")
        display = s.get("display_name") or s["participant"]
        lines.append(f"**{display}** ({s.get('role', '')}): {s['content']}\n")
    return {"transcript": "\n".join(lines), "discussion_id": discussion_id}
