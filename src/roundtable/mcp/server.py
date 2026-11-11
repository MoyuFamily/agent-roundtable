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
import sqlite3
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
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

    def uris_for(self, session: ServerSession) -> set[str]:
        return {uri for uri, sessions in self._subs.items() if session in sessions}

    def remove_session(self, session: ServerSession) -> None:
        for uri in self.uris_for(session):
            self.unsubscribe(uri, session)


@dataclass
class _SubscriptionScope:
    session: ServerSession | None = None


async def _watch_database(conn: sqlite3.Connection, subs: SubscriptionManager, scope: _SubscriptionScope) -> None:
    """Coalesce shared-DB writes into invalidations of the exact subscribed URIs.

    A dedicated connection's data_version observes writes from other connections,
    including another stdio process, a bridge, or a daemon. Notifications are
    invalidations, not an event log: clients re-read resources for current state.
    This deliberately favors reliable delivery over per-table change filtering.
    """
    version = conn.execute("PRAGMA data_version").fetchone()[0]
    while True:
        await asyncio.sleep(0.2)
        try:
            current = conn.execute("PRAGMA data_version").fetchone()[0]
        except sqlite3.Error:
            logger.exception("Cannot inspect shared database changes; retrying")
            continue
        if current == version:
            continue
        version = current
        session = scope.session
        if session is None:
            continue
        for uri in sorted(subs.uris_for(session)):
            if not await _safe_notify(session, uri):
                subs.remove_session(session)
                break


def create_server(db_path: str | None = None) -> Server:
    """Create and configure the Roundtable MCP server."""
    db = RoundtableDB(db_path=db_path)
    subs = SubscriptionManager()

    @asynccontextmanager
    async def lifespan(_server):
        conn = db.connect()
        scope = _SubscriptionScope()
        watcher = asyncio.create_task(_watch_database(conn, subs, scope))
        try:
            yield scope
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            if scope.session is not None:
                subs.remove_session(scope.session)
            conn.close()

    server = Server("agent-roundtable", lifespan=lifespan)
    core = RoundtableCore(db=db)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [Tool(**schema) for schema in TOOL_SCHEMAS]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        # Waiting for another participant must not block its request or subscription delivery.
        result = await asyncio.to_thread(handle_tool_call, core, db, name, arguments or {})
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
        result = handle_resource_read(core, db, str(uri))
        return json.dumps(result, ensure_ascii=False, default=str)

    @server.subscribe_resource()
    async def _subscribe(uri: Any) -> None:
        session = server.request_context.session
        server.request_context.lifespan_context.session = session
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
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=result["text"]))],
        )

    return server


async def _safe_notify(session: ServerSession, uri: str) -> bool:
    try:
        from pydantic import AnyUrl

        await asyncio.wait_for(session.send_resource_updated(AnyUrl(uri)), timeout=5)
        return True
    except Exception as e:
        logger.debug("Failed to notify session for %s: %s", uri, e)
        return False


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
