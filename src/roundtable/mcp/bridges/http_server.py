"""HTTP/SSE transport for the Roundtable MCP server.

Provides an HTTP endpoint for agents that can't use stdio MCP
(e.g. Codex, WorkBuddy, or browser-based clients).
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.tools import handle_tool_call

logger = logging.getLogger(__name__)


class RoundtableHTTPServer:
    """Lightweight HTTP server exposing roundtable tools as REST endpoints."""

    def __init__(self, core: RoundtableCore, db: RoundtableDB, port: int = 8200):
        self._core = core
        self._db = db
        self._port = port
        self._server: HTTPServer | None = None

    def start(self) -> None:
        handler = _make_handler(self._core, self._db)
        self._server = HTTPServer(("0.0.0.0", self._port), handler)
        logger.info("Roundtable HTTP server starting on port %d", self._port)
        self._server.serve_forever()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()


def _make_handler(core: RoundtableCore, db: RoundtableDB) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            if self.path == "/api/tool":
                tool_name = body.get("name", "")
                arguments = body.get("arguments", {})
                result = handle_tool_call(core, db, tool_name, arguments)
                self._respond(200, result)
            else:
                self._respond(404, {"error": "not found"})

        def do_GET(self) -> None:
            if self.path == "/api/health":
                self._respond(200, {"status": "ok", "server": "roundtable-mcp"})
            else:
                self._respond(404, {"error": "not found"})

        def _respond(self, status: int, data: dict[str, Any]) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug(format, *args)

    return Handler
