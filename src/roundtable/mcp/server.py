# type: ignore
"""MCP Server — registers tools, resources, and prompts for Roundtable.

Imports the optional `mcp` SDK only when this module is loaded (server runtime).
The tools/resources/prompts modules themselves are SDK-free and can be tested
directly via their handle_* functions.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.session import ServerSession
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    Resource,
    ResourcesCapability,
    TextContent,
    Tool,
)

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.prompts import PROMPT_SCHEMAS, handle_prompt_call
from roundtable.mcp.resources import RESOURCE_URIS, handle_resource_read
from roundtable.mcp.tools import TOOL_SCHEMAS, handle_tool_call

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """Tracks which sessions have subscribed to which resource URIs."""

    def __init__(self) -> None:
        self._subs: dict[str, set[ServerSession]] = {}

    def subscribe(self, uri: str, session: ServerSession) -> None:
        self._subs.setdefault(uri, set()).add(session)

    def unsubscribe(self, uri: str, session: ServerSession) -> None:
        if uri in self._subs:
            self._subs[uri].discard(session)
            if not self._subs[uri]:
                del self._subs[uri]

    def sessions_for(self, uri: str) -> list[ServerSession]:
        sessions = list(self._subs.get(uri, set()))
        # Discussion-level subscribers also receive transcript updates and vice versa.
        if uri.startswith("roundtable://discussions/") and not uri.endswith("/transcript"):
            sessions.extend(self._subs.get(f"{uri}/transcript", set()))
        if uri.endswith("/transcript"):
            base = uri[: -len("/transcript")]
            sessions.extend(self._subs.get(base, set()))
        return sessions


def create_server(db_path: str | None = None) -> Server:
    """Create and configure the Roundtable MCP server."""
    server = Server("agent-roundtable")
    db = RoundtableDB(db_path=db_path)
    subs = SubscriptionManager()
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

    def _on_event(event_type: str, payload: dict[str, Any]) -> None:
        discussion_id = payload.get("discussion_id")
        if not discussion_id:
            return
        uri = f"roundtable://discussions/{discussion_id}"
        sessions = subs.sessions_for(uri) + subs.sessions_for("roundtable://discussions")
        if not sessions:
            return
        loop = loop_holder.get("loop")
        if loop is None:
            return
        for session in sessions:
            asyncio.run_coroutine_threadsafe(
                _safe_notify(session, uri), loop
            )

    core = RoundtableCore(db=db, on_event=_on_event)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        loop_holder["loop"] = asyncio.get_running_loop()
        return [Tool(**schema) for schema in TOOL_SCHEMAS]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        loop_holder["loop"] = asyncio.get_running_loop()
        result = handle_tool_call(core, db, name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

    @server.list_resources()
    async def _list_resources() -> list[Resource]:
        loop_holder["loop"] = asyncio.get_running_loop()
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
        result = handle_resource_read(core, db, str(uri))
        return json.dumps(result, ensure_ascii=False, default=str)

    @server.subscribe_resource()
    async def _subscribe(uri: Any) -> None:
        loop_holder["loop"] = asyncio.get_running_loop()
        session = server.request_context.session
        subs.subscribe(str(uri), session)

    @server.unsubscribe_resource()
    async def _unsubscribe(uri: Any) -> None:
        session = server.request_context.session
        subs.unsubscribe(str(uri), session)

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

    server._roundtable_subs = subs
    server._roundtable_emit = _on_event
    return server


async def _safe_notify(session: ServerSession, uri: str) -> None:
    try:
        from pydantic import AnyUrl
        await session.send_resource_updated(AnyUrl(uri))
    except Exception as e:
        logger.debug("Failed to notify session for %s: %s", uri, e)


def build_initialization_options(server: Server) -> Any:
    """Initialization options that advertise resource subscribe capability."""
    opts = server.create_initialization_options(
        notification_options=NotificationOptions(resources_changed=True),
    )
    if opts.capabilities.resources is None:
        opts.capabilities.resources = ResourcesCapability(subscribe=True, listChanged=True)
    else:
        opts.capabilities.resources.subscribe = True
    return opts
