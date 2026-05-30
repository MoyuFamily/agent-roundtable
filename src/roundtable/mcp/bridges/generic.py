"""Generic HTTP bridge — platform-agnostic adapter for any HTTP-capable agent.

Subclass or instantiate directly. WorkBuddy and similar platforms can use this
without writing a dedicated bridge: configure platform name, port, and an
optional webhook URL for push notifications.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.bridges.base import AgentBridge
from roundtable.mcp.tools import handle_tool_call

logger = logging.getLogger(__name__)


class GenericBridge(AgentBridge):
    """HTTP bridge that any platform can drive.

    Endpoints:
        GET  /health            — liveness check
        GET  /inbox             — read unread messages (marks them read)
        POST /tool              — dispatch any roundtable tool
        POST /speak             — shorthand for roundtable_speak
        GET  /status/{disc_id}  — discussion status
        GET  /agent             — this bridge's agent metadata

    If `webhook_url` is set, the bridge POSTs to it whenever a new
    invitation lands in the agent's inbox (called by external poll loop
    or by setting on_event in the embedding process).
    """

    def __init__(
        self,
        agent_id: str,
        platform: str,
        *,
        port: int = 8202,
        host: str = "127.0.0.1",
        display_name: str | None = None,
        capabilities: list[str] | None = None,
        webhook_url: str | None = None,
        db_path: str | None = None,
    ):
        self._agent_id = agent_id
        self._platform = platform
        self._port = port
        self._host = host
        self._display_name = display_name or agent_id
        self._capabilities = capabilities or ["speak", "listen"]
        self._webhook_url = webhook_url
        self._db = RoundtableDB(db_path=db_path)
        self._core = RoundtableCore(db=self._db, on_event=self._on_core_event)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        conn = self._db.connect()
        try:
            self._db.upsert_agent(
                conn,
                agent_id=self._agent_id,
                platform=self._platform,
                display_name=self._display_name,
                transport="http",
                endpoint=f"http://{self._host}:{self._port}",
                capabilities=self._capabilities,
            )
        finally:
            conn.close()

        handler = _make_handler(self)
        self._server = HTTPServer((self._host, self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(
            "GenericBridge[%s] started on http://%s:%d",
            self._platform, self._host, self._port,
        )

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
            logger.info("GenericBridge[%s] stopped", self._platform)

    async def on_invitation(self, invitation: dict[str, Any]) -> bool:
        return True

    async def generate_speech(self, context: dict[str, Any]) -> str:
        raise NotImplementedError(
            "Speech generation is delegated to the platform. "
            "Receive the turn notice via /inbox or webhook, then POST to /speak."
        )

    def _on_core_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self._webhook_url:
            return
        try:
            data = json.dumps({"event": event_type, "payload": payload}).encode()
            req = urllib.request.Request(
                self._webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception as e:
            logger.debug("Webhook delivery failed: %s", e)


def _make_handler(bridge: GenericBridge) -> type[BaseHTTPRequestHandler]:
    db = bridge._db
    core = bridge._core
    agent_id = bridge.agent_id

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path

            if path == "/health":
                self._respond(200, {
                    "status": "ok",
                    "agent_id": agent_id,
                    "platform": bridge.platform,
                })

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
                disc_id = path[len("/status/"):]
                self._respond(200, core.status(disc_id))

            else:
                self._respond(404, {"error": "not found", "path": path})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length)) if length else {}
            except json.JSONDecodeError:
                self._respond(400, {"error": "invalid JSON"})
                return

            if path == "/tool":
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

    return Handler
