"""WebPublisher — manages a live web viewer for a roundtable discussion.

Uses PM2 to manage the Express subprocess, fcntl for atomic file locking,
and nanoid for token generation. Discussion data flows one-way through
a JSON file that Express reads via shared lock + fs.watch.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from roundtable.web_helpers import (
    get_avatar_for_participant,
    get_display_name_for_participant,
    get_role_for_participant,
)

logger = logging.getLogger(__name__)

SHARED_PM2_NAME = "roundtable-web"
SHARED_DATA_DIR = Path(tempfile.gettempdir()) / "roundtable_web"

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
        self._password_hash: str | None = None
        if password:
            import bcrypt  # type: ignore[import-not-found,unused-ignore]

            self._password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        self._token: str | None = None
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
        expires_at: float | None = None,
    ) -> str:
        """Start the web viewer service and return the full URL.

        1. Generate token (nanoid 21) if not provided
        2. Write initial discussion.json (includes password_hash if set)
        3. Ensure the shared Express PM2 process is running on the configured port
        4. Return URL: ``http://<host>:<port>/r/<token>``
        """
        self._discussion_id = discussion_id
        self._token = token or _generate_token()
        self._topic = topic or f"Discussion {discussion_id}"
        self._participants = participants or []
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

    def _ensure_shared_server_running(self) -> None:
        """Start the shared PM2 process on demand. No-op if already online."""
        if self._is_shared_running():
            self._wait_for_port(timeout=3.0)
            return

        server_path = Path(__file__).parent / "web" / "server.mjs"
        if not server_path.exists():
            raise FileNotFoundError(f"Express server not found: {server_path}")

        SHARED_DATA_DIR.mkdir(parents=True, exist_ok=True)

        cmd = [
            "pm2",
            "start",
            str(server_path),
            "--name",
            SHARED_PM2_NAME,
            "--interpreter",
            "node",
            "--",
            "--port",
            str(self._port),
            "--data-dir",
            str(SHARED_DATA_DIR),
        ]

        logger.info("Starting shared PM2: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            if self._is_shared_running():
                self._wait_for_port(timeout=10.0)
                return
            raise RuntimeError(f"PM2 start failed (exit {result.returncode}): {result.stderr}")

        self._wait_for_port(timeout=10.0)

    def _is_shared_running(self) -> bool:
        """Check whether the shared PM2 process is online."""
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

    def _wait_for_port(self, timeout: float = 10.0) -> None:
        """Block until the shared server accepts TCP connections on self._port."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.settimeout(0.5)
                    s.connect(("127.0.0.1", self._port))
                    logger.info("Shared web server ready on port %d", self._port)
                    return
                except OSError:
                    time.sleep(0.25)
        logger.warning("Shared web server not reachable on port %d after %.1fs", self._port, timeout)

    def _write_discussion_json(self) -> None:
        """Write current state to discussion.json with atomic file lock."""
        token_hash = _hash_token(self._token) if self._token else None
        data = {
            "schema_version": 2,
            "discussion_id": self._discussion_id,
            "topic": self._topic,
            "status": self._status,
            "token_hash": token_hash,
            "password_hash": self._password_hash,
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
        with open(target, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _write_discussion_json_raw(self, data: dict[str, Any]) -> None:
        """Atomic write: flock lock file → read/merge existing disk state → write .tmp → fsync → rename."""
        target = self._discussion_dir / "discussion.json"
        lock_path = target.with_suffix(".json.lock")
        tmp = target.with_suffix(".json.tmp")

        with open(lock_path, "a") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
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

                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.rename(str(tmp), str(target))
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_discussion_json(self) -> dict[str, Any] | None:
        """Read discussion.json with shared lock on lock file."""
        target = self._discussion_dir / "discussion.json"
        if not target.exists():
            return None

        lock_path = target.with_suffix(".json.lock")
        with open(lock_path, "a") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
            try:
                with open(target) as f:
                    result: dict[str, Any] | None = json.load(f)
                    return result
            except (json.JSONDecodeError, FileNotFoundError):
                return None
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
