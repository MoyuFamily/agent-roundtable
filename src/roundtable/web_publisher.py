"""WebPublisher — manages a live web viewer for a roundtable discussion.

Uses PM2 to manage the Express subprocess, fcntl for atomic file locking,
and nanoid for token generation. Discussion data flows one-way through
a JSON file that Express reads via shared lock + fs.watch.
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
    ) -> None:
        self._discussion_dir = Path(discussion_dir)
        self._discussion_dir.mkdir(parents=True, exist_ok=True)
        self._port = port
        self._host = host
        self._url_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
        self._token: str | None = None
        self._discussion_id: str | None = None
        self._pm2_process_name: str | None = None
        self._revoked: bool = False
        self._speeches: list[dict[str, Any]] = []
        self._participants: list[dict[str, Any]] = []
        self._topic: str | None = None
        self._conclusion: str | None = None
        self._status: str = "active"
        self._actual_port: int | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        discussion_id: str,
        token: str | None = None,
        topic: str | None = None,
        participants: list[dict[str, Any]] | None = None,
    ) -> str:
        """Start the web viewer service and return the full URL.

        1. Generate token (nanoid 21) if not provided
        2. Write initial discussion.json with file lock
        3. Port probe → PM2 start Express
        4. Return URL: ``http://<host>:<port>/r/<token>``
        """
        self._discussion_id = discussion_id
        self._token = token or _generate_token()
        self._topic = topic or f"Discussion {discussion_id}"
        self._participants = participants or []

        # Write initial discussion.json
        self._write_discussion_json()

        # Find available port
        self._actual_port = self._find_available_port(self._port)

        # Start Express via PM2
        self._start_pm2(self._actual_port)

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

        self._speeches.append(
            {
                "id": speech.get("id", len(self._speeches) + 1),
                "round": speech.get("round", 0),
                "participant": speech.get("participant", ""),
                "display_name": speech.get("display_name", ""),
                "content": speech.get("content", ""),
                "created_at": speech.get("created_at", int(time.time())),
            }
        )
        self._write_discussion_json()

    def conclude(self, conclusion: str) -> None:
        """Hook: called when the discussion concludes.

        Appends the conclusion and sets status to 'concluded'.
        """
        self._conclusion = conclusion
        self._status = "concluded"
        self._write_discussion_json()
        logger.info("Discussion %s concluded", self._discussion_id)

    def revoke(self) -> None:
        """L1 link revocation. Marks the token as revoked."""
        self._revoked = True
        data = self._read_discussion_json()
        if data:
            revoked = data.get("revoked_tokens", [])
            if self._token and self._token not in revoked:
                revoked.append(self._token)
            data["revoked_tokens"] = revoked
            data["updated_at"] = int(time.time())
            self._write_discussion_json_raw(data)
        logger.info("Token revoked for discussion %s", self._discussion_id)

    def stop(self) -> None:
        """PM2 stops the Express process."""
        if self._pm2_process_name:
            try:
                result = subprocess.run(
                    ["pm2", "delete", self._pm2_process_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    logger.warning(
                        "PM2 delete failed for %s (exit %s): %s",
                        self._pm2_process_name,
                        result.returncode,
                        result.stderr,
                    )
                else:
                    logger.info("PM2 process %s stopped", self._pm2_process_name)
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                logger.warning("Failed to stop PM2 process: %s", exc)
            finally:
                self._pm2_process_name = None

    @property
    def url(self) -> str | None:
        """Current web page URL, or None if not started."""
        if self._actual_port and self._token:
            return f"http://{self._url_host}:{self._actual_port}/r/{self._token}"
        return None

    @property
    def port(self) -> int | None:
        """Actual port the Express server is listening on."""
        return self._actual_port

    @property
    def token(self) -> str | None:
        """The access token."""
        return self._token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_available_port(self, preferred: int) -> int:
        """Find an available port starting from *preferred*, +1 on conflict."""
        for offset in range(10):
            port = preferred + offset
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("", port))
                    return port
                except OSError as exc:
                    if exc.errno == errno.EADDRINUSE:
                        continue
                    if exc.errno in (errno.EACCES, errno.EPERM):
                        raise PermissionError(
                            f"Cannot bind web viewer to port {port}: {exc.strerror or exc}"
                        ) from exc
                    raise RuntimeError(f"Cannot probe web viewer port {port}: {exc}") from exc
        raise RuntimeError(
            f"No available port in range {preferred}-{preferred + 9}: all probed ports are already in use"
        )

    def _start_pm2(self, port: int) -> None:
        """Start the Express server via PM2."""
        server_path = Path(__file__).parent / "web" / "server.mjs"
        if not server_path.exists():
            raise FileNotFoundError(f"Express server not found: {server_path}")

        self._pm2_process_name = f"roundtable-web-{self._discussion_id}"

        cmd = [
            "pm2",
            "start",
            str(server_path),
            "--name",
            self._pm2_process_name,
            "--interpreter",
            "node",
            "--",
            "--port",
            str(port),
            "--discussion-dir",
            str(self._discussion_dir),
        ]

        logger.info("Starting PM2: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            raise RuntimeError(f"PM2 start failed (exit {result.returncode}): {result.stderr}")

        # Wait for Express to be ready (probe the port)
        for _ in range(20):  # up to 10 seconds
            time.sleep(0.5)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.settimeout(1)
                    s.connect(("127.0.0.1", port))
                    logger.info("Express ready on port %d", port)
                    return
                except (OSError, ConnectionRefusedError):
                    continue

        logger.warning(
            "Express may not be ready on port %d after 10s, proceeding anyway",
            port,
        )

    def _write_discussion_json(self) -> None:
        """Write current state to discussion.json with atomic file lock."""
        data = {
            "discussion_id": self._discussion_id,
            "topic": self._topic,
            "status": self._status,
            "token": self._token,
            "participants": self._participants,
            "speeches": self._speeches,
            "conclusion": self._conclusion,
            "revoked_tokens": [self._token] if self._revoked else [],
            "updated_at": int(time.time()),
        }
        self._write_discussion_json_raw(data)

    def _write_discussion_json_raw(self, data: dict[str, Any]) -> None:
        """Atomic write: flock → write .tmp → fsync → rename."""
        target = self._discussion_dir / "discussion.json"
        tmp = target.with_suffix(".json.tmp")

        with open(tmp, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        os.rename(str(tmp), str(target))

    def _read_discussion_json(self) -> dict[str, Any] | None:
        """Read discussion.json with shared lock."""
        target = self._discussion_dir / "discussion.json"
        if not target.exists():
            return None

        with open(target) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                result: dict[str, Any] | None = json.load(f)
                return result
            except json.JSONDecodeError:
                return None
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
