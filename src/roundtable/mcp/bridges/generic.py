"""Generic HTTP bridge — platform-agnostic adapter for any HTTP-capable agent.

Subclass or instantiate directly. WorkBuddy and similar platforms can use this
without writing a dedicated bridge: configure platform name, port, and an
optional webhook URL for push notifications.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.exceptions import DiscussionNotFoundError
from roundtable.mcp.bridges.base import AgentBridge
from roundtable.mcp.tools import handle_tool_call

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 1024 * 1024


class GenericBridge(AgentBridge):
    """HTTP bridge that any platform can drive.

    Endpoints:
        GET  /health            — liveness check
        GET  /inbox             — read unread messages (marks them read)
        POST /tool              — dispatch any roundtable tool
        POST /invite            — receive an invitation
        POST /summon            — accept a dispatch summon and join
        POST /turn              — forward a turn notice to the optional webhook
        POST /speak             — shorthand for roundtable_speak
        GET  /status/{disc_id}  — discussion status
        GET  /agent             — this bridge's agent metadata

    If `webhook_url` is set, the bridge forwards incoming invite/summon/turn
    requests and events from its own core. It does not watch the shared inbox
    or execute a model. The host owns speech generation and inbox consumption.
    """

    _summon_source = "generic_bridge"

    def __init__(
        self,
        agent_id: str,
        platform: str,
        *,
        port: int = 8202,
        host: str = "127.0.0.1",
        display_name: str | None = None,
        capabilities: list[str] | None = None,
        skills: list[str] | None = None,
        availability: str = "idle",
        accept_policy: str = "auto",
        metadata: dict[str, Any] | None = None,
        auth_token: str | None = None,
        webhook_url: str | None = None,
        db_path: str | None = None,
    ):
        self._agent_id = agent_id
        self._platform = platform
        self._port = port
        self._host = host
        self._display_name = display_name or agent_id
        self._capabilities = capabilities or ["speak", "listen"]
        self._skills = skills or ["agent-roundtable"]
        self._availability = availability
        self._accept_policy = accept_policy
        self._metadata = metadata or {}
        self._auth_token = auth_token
        self._webhook_url = webhook_url
        self._db = RoundtableDB(db_path=db_path)
        self._core = RoundtableCore(db=self._db, on_event=self._on_core_event)
        self._server: ThreadingHTTPServer | None = None
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

    @property
    def host(self) -> str:
        return self._host

    def start(self) -> None:
        if self._server is not None:
            return
        server = ThreadingHTTPServer((self._host, self._port), _make_handler(self))
        port = server.server_port
        try:
            conn = self._db.connect()
            try:
                self._db.upsert_agent(
                    conn,
                    agent_id=self._agent_id,
                    platform=self._platform,
                    display_name=self._display_name,
                    transport="http",
                    endpoint=f"http://{self._host}:{port}",
                    capabilities=self._capabilities,
                    metadata={
                        **self._metadata,
                        "skills": self._skills,
                        "availability": self._availability,
                        "accept_policy": self._accept_policy,
                        "_bridge_auth_token": self._auth_token,
                    },
                )
            finally:
                conn.close()
        except Exception:
            server.server_close()
            raise
        self._port = port
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(
            "GenericBridge[%s] started on http://%s:%d",
            self._platform,
            self._host,
            self._port,
        )

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            if self._thread:
                self._thread.join(timeout=2)
                self._thread = None
            logger.info("GenericBridge[%s] stopped", self._platform)

    def _on_core_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._post_webhook(event_type, payload)

    def _post_webhook(self, event_type: str, payload: dict[str, Any]) -> None:
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
            with urllib.request.urlopen(req, timeout=2):
                pass
        except (OSError, ValueError) as e:
            logger.warning("Webhook delivery failed: %s", e)


def _make_handler(bridge: GenericBridge) -> type[BaseHTTPRequestHandler]:
    db = bridge._db
    core = bridge._core
    agent_id = bridge.agent_id
    auth_token = bridge._auth_token

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path != "/health" and not self._require_auth():
                return

            if path == "/health":
                conn = db.connect()
                try:
                    db.touch_agent(conn, agent_id, availability=bridge._availability)
                finally:
                    conn.close()
                self._respond(
                    200,
                    {
                        "status": "ok",
                        "agent_id": agent_id,
                        "platform": bridge.platform,
                    },
                )

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
                if not disc_id:
                    self._respond(400, {"error": "discussion_id required"})
                    return
                try:
                    result = core.status(disc_id)
                except DiscussionNotFoundError as exc:
                    self._respond(404, {"error": str(exc)})
                else:
                    self._respond(200, result)

            else:
                self._respond(404, {"error": "not found", "path": path})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if not self._require_auth():
                return
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
                self._respond(400, {"error": "unsupported request framing"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length < 0:
                    raise ValueError
            except ValueError:
                self._respond(400, {"error": "invalid Content-Length"})
                return
            if length > MAX_REQUEST_BYTES:
                self._respond(413, {"error": "JSON body exceeds 1 MiB"})
                return
            try:
                self.connection.settimeout(10)
                body = json.loads(self.rfile.read(length)) if length else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._respond(400, {"error": "invalid JSON"})
                return
            except TimeoutError:
                self._respond(408, {"error": "request body timed out"})
                return
            if not isinstance(body, dict):
                self._respond(400, {"error": "JSON body must be an object"})
                return

            if path == "/tool":
                tool_name = body.get("name", "")
                arguments = body.get("arguments", {})
                if not isinstance(tool_name, str) or not tool_name.strip():
                    self._respond(400, {"error": "name must be a non-empty string"})
                    return
                if not isinstance(arguments, dict):
                    self._respond(400, {"error": "arguments must be an object"})
                    return
                result = handle_tool_call(core, db, tool_name, arguments)
                self._respond(200, result)

            elif path == "/invite":
                discussion_id = body.get("discussion_id")
                if not discussion_id:
                    self._respond(400, {"error": "discussion_id required"})
                    return
                if bridge._accept_policy == "auto":
                    result = handle_tool_call(
                        core,
                        db,
                        "roundtable_accept_invite",
                        {"discussion_id": discussion_id, "agent_id": agent_id},
                    )
                else:
                    result = {"status": "pending", "reason": "manual_accept_required"}
                bridge._post_webhook("invitation", {"request": body, "result": result})
                self._respond(200, {"accepted": result.get("status") == "accepted", "result": result})

            elif path == "/summon":
                discussion_id = body.get("discussion_id")
                if not discussion_id:
                    self._respond(400, {"error": "discussion_id required"})
                    return
                auto_accept = bridge._accept_policy == "auto"
                if auto_accept:
                    result = handle_tool_call(
                        core,
                        db,
                        "roundtable_accept_summon",
                        {
                            "discussion_id": discussion_id,
                            "agent_id": agent_id,
                            "metadata": {"source": bridge._summon_source, "summon_id": body.get("summon_id")},
                        },
                    )
                else:
                    result = {"status": "pending", "reason": "manual_accept_required"}
                bridge._post_webhook("summon", {"request": body, "result": result})
                self._respond(200, {"accepted": result.get("status") == "accepted", "result": result})

            elif path == "/turn":
                bridge._post_webhook("turn", body)
                self._respond(200, {"received": True, "payload": body})

            elif path == "/speak":
                disc_id = body.get("discussion_id")
                content = body.get("content", "")
                participant = body.get("participant", agent_id)
                if not disc_id or not content:
                    self._respond(400, {"error": "discussion_id and content required"})
                    return
                result = handle_tool_call(
                    core,
                    db,
                    "roundtable_speak",
                    {
                        "discussion_id": disc_id,
                        "participant": participant,
                        "content": content,
                        "reply_to": body.get("reply_to"),
                    },
                )
                self._respond(200, result)

            else:
                self._respond(404, {"error": "not found", "path": path})

        def _require_auth(self) -> bool:
            if not auth_token:
                return True
            bearer = self.headers.get("Authorization", "")
            token = ""
            if bearer.startswith("Bearer "):
                token = bearer[len("Bearer ") :].strip()
            token = token or self.headers.get("X-Roundtable-Token", "")
            if secrets.compare_digest(token, auth_token):
                return True
            self._respond(401, {"error": "unauthorized"})
            return False

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
