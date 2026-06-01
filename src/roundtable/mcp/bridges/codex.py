"""Codex CLI bridge — connects OpenAI Codex to Roundtable via HTTP."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.bridges.base import AgentBridge
from roundtable.mcp.tools import handle_tool_call

logger = logging.getLogger(__name__)


class CodexBridge(AgentBridge):
    """Bridge that allows OpenAI Codex CLI to participate in Roundtable discussions.

    Runs a local HTTP server that:
    1. Receives webhook invitations from the MCP server
    2. Spawns Codex CLI with roundtable function schemas
    3. Translates Codex function calls to RoundtableCore operations
    """

    def __init__(
        self,
        agent_id: str = "codex-local",
        port: int = 8201,
        host: str = "127.0.0.1",
        display_name: str = "Codex Agent",
        db_path: str | None = None,
    ):
        self._agent_id = agent_id
        self._port = port
        self._host = host
        self._display_name = display_name
        self._db = RoundtableDB(db_path=db_path)
        self._core = RoundtableCore(db=self._db)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def platform(self) -> str:
        return "codex"

    @property
    def port(self) -> int:
        return self._port

    @property
    def host(self) -> str:
        return self._host

    def start(self) -> None:
        conn = self._db.connect()
        try:
            self._db.upsert_agent(
                conn,
                agent_id=self._agent_id,
                platform="codex",
                display_name=self._display_name,
                transport="http",
                endpoint=f"http://{self._host}:{self._port}",
                capabilities=["speak", "listen"],
            )
        finally:
            conn.close()

        handler = _make_handler(self._core, self._db, self._agent_id)
        self._server = HTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Codex bridge started on http://%s:%d", self._host, self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            logger.info("Codex bridge stopped")

    async def on_invitation(self, invitation: dict[str, Any]) -> bool:
        return True

    async def generate_speech(self, context: dict[str, Any]) -> str:
        raise NotImplementedError("Codex generates speech via its own CLI process")


def _make_handler(core: RoundtableCore, db: RoundtableDB, agent_id: str) -> type[BaseHTTPRequestHandler]:
    """Create an HTTP request handler class with access to core/db."""

    class CodexBridgeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path

            if path == "/health":
                self._respond(200, {"status": "ok", "agent_id": agent_id, "platform": "codex"})

            elif path == "/agent":
                conn = db.connect()
                try:
                    agent = db.get_agent(conn, agent_id)
                    self._respond(200, agent or {"error": "not registered"})
                finally:
                    conn.close()

            elif path == "/inbox":
                conn = db.connect()
                try:
                    db.touch_agent(conn, agent_id)
                    messages = db.read_inbox(conn, agent_id, unread_only=True)
                    if messages:
                        db.mark_inbox_read(conn, [m["id"] for m in messages])
                    self._respond(200, {"messages": messages})
                finally:
                    conn.close()

            elif path.startswith("/status/"):
                disc_id = path[len("/status/") :]
                self._respond(200, core.status(disc_id))

            else:
                self._respond(404, {"error": "not found", "path": path})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            content_length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(content_length)) if content_length else {}
            except json.JSONDecodeError:
                self._respond(400, {"error": "invalid JSON"})
                return

            if path == "/invite":
                conn = db.connect()
                try:
                    db.respond_invitation(conn, body["discussion_id"], agent_id, accept=True)
                    self._respond(200, {"accepted": True})
                finally:
                    conn.close()

            elif path == "/tool":
                tool_name = body.get("name", "")
                arguments = body.get("arguments", {})
                if not tool_name:
                    self._respond(400, {"error": "name required"})
                    return
                result = handle_tool_call(core, db, tool_name, arguments)
                self._respond(200, result)

            elif path == "/speak":
                disc_id = body.get("discussion_id")
                content = body.get("content", "")
                participant = body.get("participant", agent_id)
                if not disc_id or not content:
                    self._respond(400, {"error": "discussion_id and content required"})
                    return
                result = core.speak(
                    discussion_id=disc_id,
                    participant=participant,
                    content=content,
                    reply_to=body.get("reply_to"),
                )
                self._respond(200, result)

            else:
                self._respond(404, {"error": "not found", "path": path})

        def _respond(self, status: int, data: dict[str, Any]) -> None:
            payload = json.dumps(data, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug(format, *args)

    return CodexBridgeHandler
