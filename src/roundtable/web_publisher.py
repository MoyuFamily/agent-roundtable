"""WebPublisher — manages a live web viewer for a roundtable discussion.

Starts a shared local Node.js web server when possible, writes discussion
state to JSON for the server to read, and keeps the Python discussion flow
independent from web viewer startup.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib import error as url_error
from urllib import request as url_request

from roundtable.web_helpers import (
    get_avatar_for_participant,
    get_display_name_for_participant,
    get_role_for_participant,
)

logger = logging.getLogger(__name__)

SHARED_PM2_NAME = "roundtable-web"
SHARED_DATA_DIR = Path(tempfile.gettempdir()) / "roundtable_web"
MIN_NODE_MAJOR = 18
WEB_HELP = (
    "Roundtable created the discussion but could not start the web viewer. "
    "Install Node.js 18+ and run `npm install --omit=dev` in the project if automatic setup failed."
)
_DIRECT_SERVER_PROCESSES: list[Any] = []

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]


class _FileLock:
    """Best-effort advisory file lock with a no-op fallback on platforms without fcntl."""

    def __init__(self, file_obj: Any, mode: int) -> None:
        self._file_obj = file_obj
        self._mode = mode

    def __enter__(self) -> None:
        if fcntl is not None:
            fcntl.flock(self._file_obj.fileno(), self._mode)

    def __exit__(self, *_exc: object) -> None:
        if fcntl is not None:
            fcntl.flock(self._file_obj.fileno(), fcntl.LOCK_UN)


def _lock_ex(file_obj: Any) -> _FileLock:
    mode = fcntl.LOCK_EX if fcntl is not None else 0
    return _FileLock(file_obj, mode)


def _lock_sh(file_obj: Any) -> _FileLock:
    mode = fcntl.LOCK_SH if fcntl is not None else 0
    return _FileLock(file_obj, mode)


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

try:
    from nanoid import generate as _nanoid_generate  # type: ignore[import-untyped]

    def _generate_token(size: int = 21) -> str:
        return str(_nanoid_generate(size=size))
except ImportError:
    logger.debug("nanoid not installed, falling back to secrets.token_urlsafe")

    def _generate_token(size: int = 21) -> str:
        return secrets.token_urlsafe(size)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    """Return a Node-verifiable PBKDF2 password hash."""
    salt = secrets.token_urlsafe(18)
    iterations = 260_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def _safe_tail(text: str, limit: int = 500) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def _parse_node_major(version: str) -> int | None:
    cleaned = version.strip()
    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    major = cleaned.split(".", 1)[0]
    if not major.isdigit():
        return None
    return int(major)


# ---------------------------------------------------------------------------
# WebPublisher
# ---------------------------------------------------------------------------


class WebPublisher:
    """Manages a live web viewer for a single roundtable discussion.

    Usage::

        publisher = WebPublisher("/path/to/output/rt_abc123")
        url = publisher.start("rt_abc123")

        # During the discussion:
        for speech in speeches:
            publisher.on_speech(speech)

        # At the end:
        publisher.conclude("We agreed on ...")
        publisher.stop()

    Args:
        discussion_dir: Directory where ``discussion.json`` will be written.
            Typically ``output/{discussion_id}/``.
        port: Preferred HTTP port (default 8199). Auto-increments on conflict.
        host: Bind address (default ``0.0.0.0``).
    """

    def __init__(
        self,
        discussion_dir: str | Path,
        port: int = 8199,
        host: str = "0.0.0.0",
        password: str | None = None,
    ) -> None:
        self._discussion_dir = Path(discussion_dir)
        self._discussion_dir.mkdir(parents=True, exist_ok=True)
        self._port = port
        self._host = host
        self._url_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
        self._password = password
        self._password_hash: str | None = _hash_password(password) if password else None
        self._token: str | None = None
        self._owner_secret: str | None = None
        self._owner_secret_hash: str | None = None
        self._discussion_id: str | None = None
        self._revoked: bool = False
        self._speeches: list[dict[str, Any]] = []
        self._round_summaries: list[dict[str, Any]] = []
        self._stream_events: list[dict[str, Any]] = []
        self._event_seq: int = 0
        self._participants: list[dict[str, Any]] = []
        self._topic: str | None = None
        self._conclusion: str | None = None
        self._final_summary: dict[str, Any] | None = None
        self._status: str = "active"
        self._actual_port: int = port
        self._expires_at: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        discussion_id: str,
        token: str | None = None,
        topic: str | None = None,
        participants: list[dict[str, Any]] | None = None,
        status: str = "active",
        expires_at: float | None = None,
    ) -> str:
        """Start the web viewer service and return the full URL.

        1. Generate token (nanoid 21) if not provided
        2. Write initial discussion.json (includes password_hash if set)
        3. Ensure the shared local Node.js web server is running
        4. Return owner URL: ``http://<host>:<port>/r/<token>?owner=<secret>``
        """
        self._discussion_id = discussion_id
        self._token = token or _generate_token()
        self._owner_secret = _generate_token(32)
        self._owner_secret_hash = _hash_token(self._owner_secret)
        self._topic = topic or f"Discussion {discussion_id}"
        self._participants = participants or []
        self._status = status
        self._expires_at = expires_at

        self._write_discussion_json()
        self._ensure_shared_server_running()

        url = self.url
        if url is None:
            raise RuntimeError("Web viewer started without a URL")
        logger.info("Web viewer started: %s", url)
        return url

    def on_speech(self, speech: dict[str, Any]) -> None:
        """Hook: called when a new speech is recorded.

        Updates discussion.json with the new speech via file lock.
        Express detects the change via fs.watch and pushes SSE.
        """
        if self._revoked:
            return

        speech_payload = {
            "id": speech.get("id", len(self._speeches) + 1),
            "round": speech.get("round", 0),
            "participant": speech.get("participant", ""),
            "display_name": speech.get("display_name", ""),
            "content": speech.get("content", ""),
            "created_at": speech.get("created_at", time.time()),
        }
        self._speeches.append(speech_payload)
        self._append_stream_event("speech_delta", {"speech": speech_payload})
        self._write_discussion_json()

    def on_speech_start(
        self,
        speech_id: str | int,
        agent: str,
        avatar: str = "🤖",
        round_num: int = 0,
        *,
        display_name: str | None = None,
        role: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        """Append a PRD-shaped speech_start stream event."""
        if self._revoked:
            return

        event: dict[str, Any] = {
            "type": "speech_start",
            "id": speech_id,
            "agent": agent,
            "avatar": avatar,
            "round": round_num,
            "timestamp": time.time(),
        }
        if display_name is not None:
            event["display_name"] = display_name
        if role is not None:
            event["role"] = role
        if title is not None:
            event["title"] = title
        if description is not None:
            event["description"] = description
        self._append_stream_event(event)
        self._write_discussion_json()

    def on_speech_token(self, speech_id: str | int, delta: str, seq: int | None = None) -> None:
        """Append a PRD-shaped speech_token stream event."""
        if self._revoked or not delta:
            return

        event = {
            "type": "speech_token",
            "id": speech_id,
            "delta": delta,
            "seq": seq if seq is not None else self._event_seq + 1,
            "timestamp": time.time(),
        }
        self._append_stream_event(event)
        self._write_discussion_json()

    def on_speech_end(self, speech_id: str | int, total_tokens: int = 0) -> None:
        """Append a PRD-shaped speech_end stream event."""
        if self._revoked:
            return

        event = {
            "type": "speech_end",
            "id": speech_id,
            "total_tokens": total_tokens,
            "timestamp": time.time(),
        }
        self._append_stream_event(event)
        self._write_discussion_json()

    def on_round_summary(
        self,
        summary: dict[str, Any] | None = None,
        *,
        round_num: int | None = None,
        consensus: list[dict[str, Any]] | None = None,
        disagreement: list[dict[str, Any]] | None = None,
    ) -> None:
        """Hook: called when a round summary/viewpoint snapshot is available."""
        if self._revoked:
            return

        source = summary or {}
        normalized: dict[str, Any] = {
            "type": "round_summary",
            "round": round_num if round_num is not None else source.get("round", 0),
            "consensus": consensus if consensus is not None else list(source.get("consensus", [])),
            "disagreement": disagreement if disagreement is not None else list(source.get("disagreement", [])),
            "timestamp": source.get("timestamp", time.time()),
        }
        if "consensus_points" in source:
            normalized["consensus_points"] = list(source.get("consensus_points", []))
        if "disagreement_points" in source:
            normalized["disagreement_points"] = list(source.get("disagreement_points", []))
        if "new_points" in source:
            normalized["new_points"] = list(source.get("new_points", []))
        if "convergence_score" in source:
            normalized["convergence_score"] = source.get("convergence_score")

        summary_round = normalized["round"]
        self._round_summaries = [s for s in self._round_summaries if s.get("round") != summary_round]
        self._round_summaries.append(normalized)
        self._round_summaries.sort(key=lambda item: int(item.get("round", 0)))
        self._append_stream_event(normalized)
        self._write_discussion_json()

    def on_final_summary(
        self,
        *,
        consensus: list[dict[str, Any]] | None = None,
        disagreement: list[dict[str, Any]] | None = None,
        verdict: str = "",
        consensus_points: list[str] | None = None,
        disagreement_points: list[str] | None = None,
    ) -> None:
        """Append a final summary stream event for end-of-discussion cards.

        Supports updating the final summary if the new call provides a different
        verdict or a more complete set of consensus/disagreement items.
        """
        if self._revoked:
            return
        # Allow updating final summary if verdict changed or more items are available
        if self._final_summary is not None:
            old_verdict = self._final_summary.get("verdict", "")
            old_items_count = len(self._final_summary.get("consensus", [])) + len(
                self._final_summary.get("disagreement", [])
            )
            new_items_count = len(consensus or []) + len(disagreement or [])
            verdict_changed = verdict != old_verdict
            has_more_items = new_items_count > old_items_count
            if not verdict_changed and not has_more_items:
                return

        event: dict[str, Any] = {
            "type": "final_summary",
            "consensus": consensus if consensus is not None else [],
            "disagreement": disagreement if disagreement is not None else [],
            "verdict": verdict,
            "timestamp": time.time(),
        }
        if consensus_points is not None:
            event["consensus_points"] = consensus_points
        if disagreement_points is not None:
            event["disagreement_points"] = disagreement_points

        self._final_summary = event
        self._append_stream_event(event)
        self._write_discussion_json()

    def conclude(self, conclusion: str) -> None:
        """Hook: called when the discussion concludes.

        Appends the conclusion and sets status to 'concluded'.
        """
        self._conclusion = conclusion
        self._status = "concluded"
        self._append_stream_event("status_delta", {"status": self._status, "conclusion": conclusion})
        self._write_discussion_json()
        logger.info("Discussion %s concluded", self._discussion_id)

    def revoke(self) -> None:
        """L1 link revocation. Marks the token as revoked."""
        self._revoked = True
        data = self._read_discussion_json()
        if data:
            revoked = data.get("revoked_token_hashes", [])
            if self._token:
                token_hash = _hash_token(self._token)
                if token_hash not in revoked:
                    revoked.append(token_hash)
            data["revoked_token_hashes"] = revoked
            data["updated_at"] = time.time()
            self._write_discussion_json_raw(data)
        logger.info("Token revoked for discussion %s", self._discussion_id)

    def stop(self) -> None:
        """Remove this discussion from the shared web server.

        Deletes the discussion subdirectory so the shared Express instance
        drops the token from its registry. The shared PM2 process keeps running.
        """
        try:
            for fname in (
                "discussion.json",
                "token_stream.jsonl",
                "discussion.json.lock",
                "discussion.json.tmp",
            ):
                (self._discussion_dir / fname).unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                self._discussion_dir.rmdir()
            logger.info("Discussion dir removed for %s", self._discussion_id)
        except Exception:
            logger.exception("Failed to remove discussion dir for %s", self._discussion_id)

    @property
    def url(self) -> str | None:
        """Current web page URL, or None if not started."""
        if self._actual_port and self._token:
            url = f"http://{self._url_host}:{self._actual_port}/r/{self._token}"
            if self._owner_secret:
                return f"{url}?owner={self._owner_secret}"
            return url
        return None

    @property
    def port(self) -> int | None:
        """Actual port the Express server is listening on."""
        return self._actual_port

    @property
    def token(self) -> str | None:
        """The access token."""
        return self._token

    @property
    def owner_secret(self) -> str | None:
        """Secret required for owner-only operations such as link revocation."""
        return self._owner_secret

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_shared_server_running(self) -> None:
        """Start or reuse a shared local web server on a usable port."""
        server_path = Path(__file__).parent / "web" / "server.mjs"
        if not server_path.exists():
            raise FileNotFoundError(f"Roundtable web server not found: {server_path}")

        SHARED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._actual_port = self._select_port(self._port)

        if self._is_roundtable_server_ready(self._actual_port):
            return

        if self._is_shared_running() and self._wait_for_port(timeout=3.0):
            return

        node = shutil.which("node")
        if not node:
            raise RuntimeError("Node.js 18+ is required for the web viewer but `node` was not found on PATH.")
        self._ensure_supported_node(node)

        attempts: list[str] = []
        if self._start_direct_node_server(node, server_path):
            return
        attempts.append("direct `node server.mjs` did not become ready")

        install_result = self._install_web_dependencies()
        if install_result is not None:
            attempts.append(install_result)
            if self._start_direct_node_server(node, server_path):
                return

        pm2_result = self._start_pm2_server(node, server_path)
        if pm2_result is None:
            return
        attempts.append(pm2_result)

        detail = "; ".join(a for a in attempts if a)
        raise RuntimeError(f"Could not start Roundtable web viewer on port {self._actual_port}. {detail}")

    def _ensure_supported_node(self, node: str) -> None:
        try:
            result = subprocess.run(
                [node, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Could not check Node.js version for the web viewer: {exc}") from exc

        version = (result.stdout or result.stderr).strip()
        major = _parse_node_major(version)
        if result.returncode != 0 or major is None:
            raise RuntimeError(f"Could not check Node.js version for the web viewer: {version or 'unknown error'}")
        if major < MIN_NODE_MAJOR:
            raise RuntimeError(
                f"Node.js {MIN_NODE_MAJOR}+ is required for the web viewer; found {version}. "
                "Install a current Node.js release or run with web=False."
            )

    def _select_port(self, preferred: int) -> int:
        """Return a reusable Roundtable port or the next free local TCP port."""
        for candidate in range(preferred, preferred + 50):
            if self._is_roundtable_server_ready(candidate):
                return candidate
            if not self._is_port_open(candidate):
                return candidate
        raise RuntimeError(f"No free port found in range {preferred}-{preferred + 49}")

    def _is_shared_running(self) -> bool:
        """Check whether the shared PM2 process is online."""
        if shutil.which("pm2") is None:
            return False
        try:
            result = subprocess.run(
                ["pm2", "jlist"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False
            procs = json.loads(result.stdout or "[]")
            for p in procs:
                if p.get("name") == SHARED_PM2_NAME:
                    status = p.get("pm2_env", {}).get("status")
                    return bool(status == "online")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return False
        return False

    def _wait_for_port(self, timeout: float = 10.0) -> bool:
        """Block until the shared server accepts TCP connections on self._port."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._is_roundtable_server_ready(self._actual_port):
                logger.info("Shared web server ready on port %d", self._actual_port)
                return True
            time.sleep(0.25)
        logger.warning("Shared web server not reachable on port %d after %.1fs", self._actual_port, timeout)
        return False

    def _is_port_open(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.3)
                s.connect(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def _is_roundtable_server_ready(self, port: int) -> bool:
        try:
            with url_request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.5) as response:
                if response.status != 200:
                    return False
                payload = json.loads(response.read().decode("utf-8"))
                data_dir = Path(str(payload.get("data_dir", ""))).resolve()
                return bool(payload.get("ok")) and data_dir == SHARED_DATA_DIR.resolve()
        except (OSError, TimeoutError, url_error.URLError, json.JSONDecodeError, ValueError):
            return False

    def _start_direct_node_server(self, node: str, server_path: Path) -> bool:
        cmd = [
            node,
            str(server_path),
            "--port",
            str(self._actual_port),
            "--data-dir",
            str(SHARED_DATA_DIR),
        ]
        log_path = SHARED_DATA_DIR / f"server-{self._actual_port}.log"
        logger.info("Starting Roundtable web server: %s", " ".join(cmd))
        log_file = None
        try:
            log_file = open(log_path, "ab")  # noqa: SIM115 - kept open while the child process owns it.
            popen_kwargs: dict[str, Any] = {
                "stdout": log_file,
                "stderr": log_file,
                "stdin": subprocess.DEVNULL,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(cmd, **popen_kwargs)
            _DIRECT_SERVER_PROCESSES.append((proc, log_file))
        except OSError as exc:
            if log_file is not None:
                with contextlib.suppress(OSError):
                    log_file.close()
            logger.warning("Direct Node web server start failed: %s", exc)
            return False

        if self._wait_for_port(timeout=8.0):
            return True

        if proc.poll() is not None:
            logger.warning(
                "Roundtable web server exited with code %s. Log tail: %s",
                proc.returncode,
                self._read_server_log_tail(log_path),
            )
        return False

    def _read_server_log_tail(self, log_path: Path) -> str:
        try:
            return _safe_tail(log_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return ""

    def _find_npm_project_dir(self) -> Path | None:
        candidates = [
            Path(__file__).resolve().parent / "web",
            Path(__file__).resolve().parents[2],
        ]
        for candidate in candidates:
            if (candidate / "package.json").exists():
                return candidate
        return None

    def _install_web_dependencies(self) -> str | None:
        npm = shutil.which("npm")
        project_dir = self._find_npm_project_dir()
        if project_dir is None:
            return "no local package.json found for npm dependency installation"
        if npm is None:
            return "npm was not found on PATH, so web dependencies could not be installed automatically"

        cmd = [npm, "install", "--omit=dev"]
        logger.info("Installing Roundtable web dependencies in %s: %s", project_dir, " ".join(cmd))
        env = os.environ.copy()
        env.setdefault("PUPPETEER_SKIP_DOWNLOAD", "true")
        try:
            result = subprocess.run(
                cmd,
                cwd=project_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"`npm install --omit=dev` failed: {exc}"

        if result.returncode != 0:
            stderr = _safe_tail(result.stderr or result.stdout)
            return f"`npm install --omit=dev` exited {result.returncode}: {stderr}"
        return "`npm install --omit=dev` completed"

    def _start_pm2_server(self, node: str, server_path: Path) -> str | None:
        pm2 = shutil.which("pm2")
        if pm2 is None:
            return "PM2 is not installed; skipped optional PM2 fallback"

        cmd = [
            pm2,
            "start",
            str(server_path),
            "--name",
            SHARED_PM2_NAME,
            "--interpreter",
            node,
            "--",
            "--port",
            str(self._actual_port),
            "--data-dir",
            str(SHARED_DATA_DIR),
        ]

        logger.info("Starting shared PM2 web server: %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"PM2 fallback failed: {exc}"

        if result.returncode == 0 and self._wait_for_port(timeout=10.0):
            return None
        stderr = _safe_tail(result.stderr or result.stdout)
        return f"PM2 fallback exited {result.returncode}: {stderr}"

    def _write_discussion_json(self) -> None:
        """Write current state to discussion.json with atomic file lock."""
        token_hash = _hash_token(self._token) if self._token else None
        data = {
            "schema_version": 3,
            "discussion_id": self._discussion_id,
            "topic": self._topic,
            "status": self._status,
            "token_hash": token_hash,
            "password_hash": self._password_hash,
            "owner_secret_hash": self._owner_secret_hash,
            "participants": self._participants,
            "speeches": self._speeches,
            "round_summaries": self._round_summaries,
            "stream": {
                "seq": self._event_seq,
                "events": self._stream_events[-100:],
            },
            "latest_event": self._stream_events[-1] if self._stream_events else None,
            "conclusion": self._conclusion,
            "final_summary": self._final_summary,
            "revoked_token_hashes": [token_hash] if self._revoked and token_hash else [],
            "expires_at": self._expires_at,
            "updated_at": time.time(),
        }
        self._write_discussion_json_raw(data)

    def _display_name_for_participant(self, participant: str) -> str:
        return get_display_name_for_participant(participant, self._participants)

    def _role_for_participant(self, participant: str) -> str:
        return get_role_for_participant(participant, self._participants)

    def _title_for_participant(self, participant: str) -> str:
        for item in self._participants:
            if item.get("profile") == participant or item.get("participant") == participant:
                return str(item.get("title") or "")
        return ""

    def _description_for_participant(self, participant: str) -> str:
        for item in self._participants:
            if item.get("profile") == participant or item.get("participant") == participant:
                return str(item.get("description") or "")
        return ""

    def _avatar_for_participant(self, participant: str) -> str:
        return get_avatar_for_participant(participant, self._participants)

    def _append_stream_event(
        self,
        event_or_type: dict[str, Any] | str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an ordered event and mirror PRD-shaped events to token_stream.jsonl."""
        self._event_seq += 1
        if isinstance(event_or_type, dict):
            jsonl_event = dict(event_or_type)
            event = dict(event_or_type)
            event["seq"] = self._event_seq
            self._append_token_stream_jsonl(jsonl_event)
        else:
            event = {
                "seq": self._event_seq,
                "type": event_or_type,
                "created_at": time.time(),
                "payload": payload or {},
            }
        self._stream_events.append(event)
        return event

    def _append_token_stream_jsonl(self, event: dict[str, Any]) -> None:
        """Append one event to token_stream.jsonl for SSE tailing/replay."""
        target = self._discussion_dir / "token_stream.jsonl"
        with open(target, "a") as f, _lock_ex(f):
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

    def _write_discussion_json_raw(self, data: dict[str, Any]) -> None:
        """Atomic write: flock lock file → read/merge existing disk state → write .tmp → fsync → rename."""
        target = self._discussion_dir / "discussion.json"
        lock_path = target.with_suffix(".json.lock")
        tmp = target.with_suffix(".json.tmp")

        with open(lock_path, "a") as lock_file, _lock_ex(lock_file):
            # Read existing data to merge and prevent overwriting cross-process changes
            existing = None
            if target.exists():
                try:
                    with open(target, encoding="utf-8") as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError):
                    pass

            if existing:
                # 1. Merge speeches by id
                existing_speeches = existing.get("speeches", [])
                speech_map = {s["id"]: s for s in existing_speeches}
                for s in data.get("speeches", []):
                    speech_map[s["id"]] = s
                data["speeches"] = sorted(speech_map.values(), key=lambda s: s["id"])
                self._speeches = data["speeches"]

                # 2. Merge round_summaries by round
                existing_summaries = existing.get("round_summaries", [])
                summary_map = {s["round"]: s for s in existing_summaries if "round" in s}
                for s in data.get("round_summaries", []):
                    r_num = s.get("round")
                    if r_num is not None:
                        if r_num in summary_map:
                            existing_s = summary_map[r_num]
                            existing_ts = existing_s.get("timestamp", 0.0)
                            data_ts = s.get("timestamp", 0.0)
                            if data_ts < existing_ts:
                                # Existing on disk is newer; keep it.
                                pass
                            elif data_ts > existing_ts:
                                # Live memory version is newer; use it.
                                summary_map[r_num] = s
                            else:
                                # Timestamps are equal, resolve by completeness
                                ex_has_score = "convergence_score" in existing_s
                                new_has_score = "convergence_score" in s
                                if ex_has_score and not new_has_score:
                                    # Existing has score, keep existing
                                    pass
                                elif not ex_has_score and new_has_score:
                                    summary_map[r_num] = s
                                else:
                                    # Compare information quantity (consensus + disagreement items count)
                                    ex_items = len(existing_s.get("consensus", [])) + len(
                                        existing_s.get("disagreement", [])
                                    )
                                    new_items = len(s.get("consensus", [])) + len(s.get("disagreement", []))
                                    if new_items > ex_items:
                                        summary_map[r_num] = s
                        else:
                            summary_map[r_num] = s
                data["round_summaries"] = sorted(summary_map.values(), key=lambda s: s.get("round", 0))
                self._round_summaries = data["round_summaries"]

                # 3. Merge final_summary
                existing_fs = existing.get("final_summary")
                data_fs = data.get("final_summary")
                existing_ts = existing_fs.get("timestamp", 0) if existing_fs else 0
                data_ts = data_fs.get("timestamp", 0) if data_fs else 0

                if existing_fs and not data_fs:
                    data["final_summary"] = existing_fs
                    self._final_summary = existing_fs
                elif existing_fs and data_fs:
                    if data_ts < existing_ts:
                        data["final_summary"] = existing_fs
                        self._final_summary = existing_fs
                    elif data_ts > existing_ts:
                        self._final_summary = data_fs
                    else:
                        # Equal timestamps, merge based on completeness/verdict
                        ex_verdict = existing_fs.get("verdict", "")
                        new_verdict = data_fs.get("verdict", "")
                        ex_items = len(existing_fs.get("consensus", [])) + len(existing_fs.get("disagreement", []))
                        new_items = len(data_fs.get("consensus", [])) + len(data_fs.get("disagreement", []))
                        verdict_changed = new_verdict != ex_verdict
                        has_more_items = new_items > ex_items
                        if not verdict_changed and not has_more_items:
                            data["final_summary"] = existing_fs
                            self._final_summary = existing_fs
                        else:
                            self._final_summary = data_fs

                # 4. Merge status & conclusion
                if existing.get("status") == "concluded" and data.get("status") != "concluded":
                    data["status"] = "concluded"
                    self._status = "concluded"
                elif existing.get("status") == "active" and data.get("status") == "assembling":
                    data["status"] = "active"
                    self._status = "active"
                elif existing.get("status") == "cancelled" and data.get("status") in {"assembling", "active"}:
                    data["status"] = "cancelled"
                    self._status = "cancelled"

                existing_conclusion = existing.get("conclusion")
                new_conclusion = data.get("conclusion")
                if existing_conclusion:
                    if not new_conclusion:
                        data["conclusion"] = existing_conclusion
                        self._conclusion = existing_conclusion
                    elif new_conclusion != existing_conclusion:
                        if data_ts < existing_ts:
                            data["conclusion"] = existing_conclusion
                            self._conclusion = existing_conclusion
                        else:
                            self._conclusion = new_conclusion

                # 5. Merge root events (e.g. speech_delta, status_delta from fallback sync)
                existing_events = existing.get("events", [])
                new_events = data.get("events", [])
                if existing_events:
                    seen_events = set()
                    merged_events = []

                    def get_event_sig(ev: dict[str, Any]) -> Any:
                        ev_type = ev.get("type")
                        if ev_type == "speech_delta":
                            return ("speech_delta", ev.get("speech", {}).get("id"))
                        elif ev_type == "status_delta":
                            return ("status_delta", ev.get("status"), ev.get("conclusion"))
                        elif ev_type == "round_summary":
                            return ("round_summary", ev.get("round"))
                        elif ev_type == "final_summary":
                            return ("final_summary", ev.get("verdict"))
                        else:
                            return json.dumps(ev, sort_keys=True)

                    for ev in existing_events + new_events:
                        sig = get_event_sig(ev)
                        if sig not in seen_events:
                            seen_events.add(sig)
                            merged_events.append(ev)
                    data["events"] = merged_events

                existing_revoked = list(existing.get("revoked_token_hashes", []))
                for old_token in existing.get("revoked_tokens", []):
                    existing_revoked.append(_hash_token(old_token))
                new_revoked = data.get("revoked_token_hashes", [])
                merged_revoked = list(set(existing_revoked + new_revoked))
                data["revoked_token_hashes"] = merged_revoked
                data.pop("revoked_tokens", None)
                if self._token and _hash_token(self._token) in merged_revoked:
                    self._revoked = True

                # 7. Preserve password_hash from disk if memory doesn't have one
                if existing.get("password_hash") and not data.get("password_hash"):
                    data["password_hash"] = existing["password_hash"]
                if existing.get("owner_secret_hash") and not data.get("owner_secret_hash"):
                    data["owner_secret_hash"] = existing["owner_secret_hash"]

                # 8. Preserve cross-process dispatch snapshots and joiners.
                # The in-memory publisher may have been created before summoned
                # agents accepted. Avoid reverting DB-backed sync fields.
                for key in ("dispatches", "dispatch_summary"):
                    if key in existing and key not in data:
                        data[key] = existing[key]

                existing_participants = existing.get("participants", [])
                new_participants = data.get("participants", [])
                if existing_participants:
                    participant_map = {
                        p.get("profile") or p.get("participant"): p
                        for p in existing_participants
                        if p.get("profile") or p.get("participant")
                    }
                    for p in new_participants:
                        key = p.get("profile") or p.get("participant")
                        if key:
                            participant_map[key] = p
                    data["participants"] = list(participant_map.values())
                    self._participants = data["participants"]

            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.rename(str(tmp), str(target))

    def _read_discussion_json(self) -> dict[str, Any] | None:
        """Read discussion.json with shared lock on lock file."""
        target = self._discussion_dir / "discussion.json"
        if not target.exists():
            return None

        lock_path = target.with_suffix(".json.lock")
        with open(lock_path, "a") as lock_file, _lock_sh(lock_file):
            try:
                with open(target) as f:
                    result: dict[str, Any] | None = json.load(f)
                    return result
            except (json.JSONDecodeError, FileNotFoundError):
                return None
        return None
