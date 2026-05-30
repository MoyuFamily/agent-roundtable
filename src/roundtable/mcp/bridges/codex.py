"""Codex CLI bridge — connects OpenAI Codex to Roundtable via HTTP."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import threading
from typing import Any

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
        db_path: str | None = None,
    ):
        self._agent_id = agent_id
        self._port = port
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

    def start(self) -> None:
        conn = self._db.connect()
        try:
            self._db.upsert_agent(
                conn,
                agent_id=self._agent_id,
                platform="codex",
                display_name="Codex Agent",
                transport="http",
                endpoint=f"http://localhost:{self._port}",
                capabilities=["speak", "listen"],
            )
        finally:
            conn.close()

        handler = _make_handler(self._core, self._db, self._agent_id)
        self._server = HTTPServer(("127.0.0.1", self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Codex bridge started on port %d", self._port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            logger.info("Codex bridge stopped")

    async def on_invitation(self, invitation: dict[str, Any]) -> bool:
        return True

    async def generate_speech(self, context: dict[str, Any]) -> str:
        raise NotImplementedError("Codex generates speech via its own CLI process")


def _make_handler(core: RoundtableCore, db: RoundtableDB, agent_id: str):
    """Create an HTTP request handler class with access to core/db."""

    class CodexBridgeHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            if self.path == "/invite":
                conn = db.connect()
                try:
                    db.respond_invitation(conn, body["discussion_id"], agent_id, accept=True)
                    self._respond(200, {"accepted": True})
                finally:
                    conn.close()

            elif self.path == "/tool":
                tool_name = body.get("name", "")
                arguments = body.get("arguments", {})
                result = handle_tool_call(core, db, tool_name, arguments)
                self._respond(200, result)

            else:
                self._respond(404, {"error": "not found"})

        def _respond(self, status: int, data: dict):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def log_message(self, format, *args):
            logger.debug(format, *args)

    return CodexBridgeHandler
