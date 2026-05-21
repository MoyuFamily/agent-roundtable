"""Tests for WebPublisher — web viewer manager.

Tests the Python-side lifecycle: start → on_speech → conclude → revoke → stop.
Express subprocess is mocked to keep tests fast (no real PM2).
File I/O uses real tmp_path for integration confidence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from roundtable.web_publisher import WebPublisher, _generate_token


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------


class TestTokenGeneration:
    def test_generate_token_default_length(self):
        token = _generate_token()
        assert len(token) == 21

    def test_generate_token_custom_length(self):
        token = _generate_token(size=10)
        assert len(token) == 10

    def test_generate_token_unique(self):
        tokens = {_generate_token() for _ in range(100)}
        assert len(tokens) == 100  # all unique

    def test_generate_token_url_safe(self):
        """Token should only contain URL-safe characters."""
        token = _generate_token()
        # nanoid uses A-Za-z0-9_- by default
        import re
        assert re.match(r'^[A-Za-z0-9_-]+$', token)


# ---------------------------------------------------------------------------
# WebPublisher construction
# ---------------------------------------------------------------------------


class TestWebPublisherInit:
    def test_creates_discussion_dir(self, tmp_path):
        d = tmp_path / "new_dir"
        assert not d.exists()
        pub = WebPublisher(str(d))
        assert d.exists()

    def test_defaults(self, tmp_path):
        pub = WebPublisher(str(tmp_path))
        assert pub._port == 8199
        assert pub._host == "0.0.0.0"
        assert pub._token is None
        assert pub.url is None
        assert pub.port is None
        assert pub.token is None


# ---------------------------------------------------------------------------
# Port finding
# ---------------------------------------------------------------------------


class TestPortFinding:
    def test_finds_available_port(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=18199)
        port = pub._find_available_port(18199)
        assert port >= 18199
        assert port < 18209  # within 10 attempts

    def test_skips_busy_port(self, tmp_path):
        """If the preferred port is busy, finds the next one."""
        import socket
        pub = WebPublisher(str(tmp_path), port=18299)

        # Block the first port
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            blocker.bind(("", 18299))
            port = pub._find_available_port(18299)
            assert port == 18300  # next one
        finally:
            blocker.close()

    def test_raises_if_no_port_available(self, tmp_path):
        """Raises RuntimeError when all 10 ports are busy."""
        import socket
        pub = WebPublisher(str(tmp_path), port=18399)

        blockers = []
        try:
            for i in range(10):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("", 18399 + i))
                blockers.append(s)

            with pytest.raises(RuntimeError, match="No available port"):
                pub._find_available_port(18399)
        finally:
            for s in blockers:
                s.close()


# ---------------------------------------------------------------------------
# File I/O (atomic write + read)
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_write_and_read_discussion_json(self, tmp_path):
        pub = WebPublisher(str(tmp_path))
        pub._discussion_id = "rt_test01"
        pub._token = "testtoken123"
        pub._topic = "Test Topic"

        pub._write_discussion_json()

        data = pub._read_discussion_json()
        assert data is not None
        assert data["discussion_id"] == "rt_test01"
        assert data["token"] == "testtoken123"
        assert data["topic"] == "Test Topic"
        assert data["status"] == "active"
        assert data["speeches"] == []

    def test_write_creates_json_file(self, tmp_path):
        pub = WebPublisher(str(tmp_path))
        pub._discussion_id = "rt_test02"
        pub._write_discussion_json()

        json_path = tmp_path / "discussion.json"
        assert json_path.exists()

        with open(json_path) as f:
            data = json.load(f)
        assert data["discussion_id"] == "rt_test02"

    def test_read_nonexistent_returns_none(self, tmp_path):
        pub = WebPublisher(str(tmp_path))
        assert pub._read_discussion_json() is None

    def test_atomic_write_no_tmp_file_left(self, tmp_path):
        """After write, .tmp file should be renamed away."""
        pub = WebPublisher(str(tmp_path))
        pub._discussion_id = "rt_test03"
        pub._write_discussion_json()

        tmp_file = tmp_path / "discussion.json.tmp"
        assert not tmp_file.exists()
        assert (tmp_path / "discussion.json").exists()

    def test_write_discussion_json_raw_preserves_extra_fields(self, tmp_path):
        """Raw write allows extra fields like revoked_tokens."""
        pub = WebPublisher(str(tmp_path))
        custom_data = {
            "discussion_id": "rt_custom",
            "extra_field": "hello",
            "revoked_tokens": ["abc"],
        }
        pub._write_discussion_json_raw(custom_data)

        data = pub._read_discussion_json()
        assert data["extra_field"] == "hello"
        assert data["revoked_tokens"] == ["abc"]


# ---------------------------------------------------------------------------
# Lifecycle: start → on_speech → conclude → stop
# ---------------------------------------------------------------------------


class TestWebPublisherLifecycle:
    @patch("roundtable.web_publisher.subprocess.run")
    @patch("roundtable.web_publisher.time.sleep", return_value=None)
    def test_start_returns_url(self, mock_sleep, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)

        pub = WebPublisher(str(tmp_path), port=19001)

        # Mock port probe to succeed immediately
        with patch.object(pub, "_start_pm2"):
            url = pub.start("rt_lifecycle01", topic="Test Topic")

        assert url is not None
        assert "/r/" in url
        assert pub.token is not None
        assert pub.port is not None

    def test_start_writes_initial_json(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19002)

        with patch.object(pub, "_start_pm2"):
            pub.start(
                "rt_init",
                topic="AI Ethics",
                participants=[
                    {"profile": "alice", "display_name": "Alice"},
                    {"profile": "bob", "display_name": "Bob"},
                ],
            )

        data = pub._read_discussion_json()
        assert data["discussion_id"] == "rt_init"
        assert data["topic"] == "AI Ethics"
        assert len(data["participants"]) == 2
        assert data["speeches"] == []
        assert data["status"] == "active"

    def test_start_with_custom_token(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19003)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_tok", token="my-custom-token")

        assert pub.token == "my-custom-token"

    def test_on_speech_appends_and_updates_json(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19004)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_speech", topic="Test")

        pub.on_speech({
            "participant": "alice",
            "display_name": "Alice",
            "content": "Hello everyone!",
            "round": 1,
        })

        data = pub._read_discussion_json()
        assert len(data["speeches"]) == 1
        assert data["speeches"][0]["participant"] == "alice"
        assert data["speeches"][0]["content"] == "Hello everyone!"
        assert data["speeches"][0]["round"] == 1

    def test_on_speech_multiple(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19005)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_multi", topic="Test")

        for i in range(5):
            pub.on_speech({
                "participant": f"speaker_{i}",
                "content": f"Speech {i}",
            })

        data = pub._read_discussion_json()
        assert len(data["speeches"]) == 5

    def test_on_speech_after_revoke_is_noop(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19006)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_revoke_speech", topic="Test")

        pub.on_speech({"participant": "alice", "content": "Before revoke"})
        pub.revoke()
        pub.on_speech({"participant": "bob", "content": "After revoke"})

        data = pub._read_discussion_json()
        assert len(data["speeches"]) == 1  # only the first one

    def test_conclude_sets_status_and_conclusion(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19007)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_conclude", topic="Test")

        pub.on_speech({"participant": "alice", "content": "I think..."})
        pub.conclude("We agreed on X.")

        data = pub._read_discussion_json()
        assert data["status"] == "concluded"
        assert data["conclusion"] == "We agreed on X."

    def test_revoke_marks_token(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19008)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_revoke", topic="Test")

        token = pub.token
        pub.revoke()

        data = pub._read_discussion_json()
        assert token in data["revoked_tokens"]

    def test_revoke_sets_internal_flag(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19009)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_revoke2", topic="Test")

        assert not pub._revoked
        pub.revoke()
        assert pub._revoked


# ---------------------------------------------------------------------------
# stop() — PM2 process cleanup
# ---------------------------------------------------------------------------


class TestStop:
    @patch("roundtable.web_publisher.subprocess.run")
    def test_stop_calls_pm2_delete(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)

        pub = WebPublisher(str(tmp_path), port=19010)
        with patch.object(pub, "_start_pm2"):
            pub.start("rt_stop")

        pub.stop()
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "pm2" in cmd
        assert "delete" in cmd
        assert pub._pm2_process_name is None

    def test_stop_when_not_started(self, tmp_path):
        """stop() on a publisher that never started should be a no-op."""
        pub = WebPublisher(str(tmp_path))
        pub.stop()  # should not raise


# ---------------------------------------------------------------------------
# start() — PM2 integration
# ---------------------------------------------------------------------------


class TestPM2Start:
    @patch("roundtable.web_publisher.subprocess.run")
    @patch("roundtable.web_publisher.time.sleep", return_value=None)
    def test_start_pm2_builds_correct_command(self, mock_sleep, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)

        pub = WebPublisher(str(tmp_path), port=19011)

        # Patch socket connect to succeed immediately (port is ready)
        with patch("roundtable.web_publisher.socket.socket") as mock_sock:
            mock_sock.return_value.__enter__ = lambda s: s
            mock_sock.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.return_value.connect = MagicMock()

            pub.start("rt_pm2_cmd")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "pm2"
        assert cmd[1] == "start"
        assert "server.mjs" in cmd[2]
        assert "--name" in cmd
        assert "--interpreter" in cmd
        assert "node" in cmd

    @patch("roundtable.web_publisher.subprocess.run")
    def test_start_pm2_failure_raises(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stderr="PM2 error")

        pub = WebPublisher(str(tmp_path), port=19012)
        with pytest.raises(RuntimeError, match="PM2 start failed"):
            pub.start("rt_pm2_fail")


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    def test_url_before_start(self, tmp_path):
        pub = WebPublisher(str(tmp_path))
        assert pub.url is None

    def test_url_after_start(self, tmp_path):
        pub = WebPublisher(str(tmp_path), port=19013)
        with patch.object(pub, "_start_pm2"):
            url = pub.start("rt_props")
        assert pub.url == url
        assert pub.port is not None
        assert pub.token is not None


# ---------------------------------------------------------------------------
# Integration: full lifecycle with real file I/O
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_lifecycle_json_state(self, tmp_path):
        """Simulate a full discussion lifecycle and verify JSON state."""
        pub = WebPublisher(str(tmp_path), port=19020)
        with patch.object(pub, "_start_pm2"):
            pub.start(
                "rt_integration",
                topic="Should we use SSE or WebSocket?",
                participants=[
                    {"profile": "tech_lead", "display_name": "Tech Lead"},
                    {"profile": "pm", "display_name": "PM"},
                ],
            )

        # Initial state
        data = pub._read_discussion_json()
        assert data["status"] == "active"
        assert data["speeches"] == []

        # Speeches
        pub.on_speech({
            "participant": "tech_lead",
            "display_name": "Tech Lead",
            "content": "SSE is simpler for one-way push.",
            "round": 1,
        })
        pub.on_speech({
            "participant": "pm",
            "display_name": "PM",
            "content": "What about WeChat browser compatibility?",
            "round": 1,
        })

        data = pub._read_discussion_json()
        assert len(data["speeches"]) == 2
        assert data["speeches"][0]["participant"] == "tech_lead"
        assert data["speeches"][1]["content"] == "What about WeChat browser compatibility?"

        # Conclude
        pub.conclude("Use SSE with long-polling fallback for WeChat.")

        data = pub._read_discussion_json()
        assert data["status"] == "concluded"
        assert "long-polling" in data["conclusion"]

        # Revoke
        pub.revoke()
        data = pub._read_discussion_json()
        assert pub.token in data["revoked_tokens"]
