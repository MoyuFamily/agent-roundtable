"""MCP Server — registers tools, resources, and prompts for Roundtable.

Imports the optional `mcp` SDK only when this module is loaded (server runtime).
The tools/resources/prompts modules themselves are SDK-free and can be tested
directly via their handle_* functions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    TextContent,
    Tool,
)

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.prompts import PROMPT_SCHEMAS, handle_prompt_call
from roundtable.mcp.resources import RESOURCE_URIS, handle_resource_read
from roundtable.mcp.tools import TOOL_SCHEMAS, handle_tool_call

logger = logging.getLogger(__name__)


def create_server(db_path: str | None = None) -> Server:
    """Create and configure the Roundtable MCP server."""
    server = Server("agent-roundtable")
    db = RoundtableDB(db_path=db_path)
    core = RoundtableCore(db=db, on_event=lambda t, p: _on_core_event(server, t, p))

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [Tool(**schema) for schema in TOOL_SCHEMAS]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        result = handle_tool_call(core, db, name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    @server.list_resources()
    async def _list_resources() -> list[Resource]:
        return [
            Resource(
                uri=spec["uri"],
                name=spec["name"],
                description=spec["description"],
                mimeType="application/json",
            )
            for spec in RESOURCE_URIS
        ]

    @server.read_resource()
    async def _read_resource(uri: str) -> str:
        result = handle_resource_read(core, db, uri)
        return json.dumps(result, ensure_ascii=False, default=str)

    @server.list_prompts()
    async def _list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name=spec["name"],
                description=spec["description"],
                arguments=[PromptArgument(**a) for a in spec.get("arguments", [])],
            )
            for spec in PROMPT_SCHEMAS
        ]

    @server.get_prompt()
    async def _get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
        result = handle_prompt_call(core, db, name, arguments or {})
        return GetPromptResult(
            description=result["description"],
            messages=[
                PromptMessage(role="user", content=TextContent(type="text", text=result["text"]))
            ],
        )

    return server


def _on_core_event(server: Server, event_type: str, payload: dict[str, Any]) -> None:
    """Bridge core events to MCP resource update notifications."""
    discussion_id = payload.get("discussion_id")
    if discussion_id:
        try:
            server.request_context.session.send_resource_updated(
                f"roundtable://discussions/{discussion_id}"
            )
        except Exception:
            pass
