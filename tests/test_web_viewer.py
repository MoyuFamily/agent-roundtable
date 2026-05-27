"""Integration tests for the Roundtable Web Viewer server.

Tests cover:
- Password protection flow (bcrypt + HMAC cookie)
- Export endpoints (Markdown, PDF)
- i18n and language switching
- Basic server lifecycle (startup, token validation)
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "roundtable" / "web" / "server.mjs"


def _can_generate_pdf() -> bool:
    """Check if md-to-pdf can generate a PDF (needs Chromium/Puppeteer).

    CI runners have Chrome installed but Puppeteer's bundled Chromium
    often fails due to missing system libs / sandbox.  Skip there.
    """
    import os
    import shutil

    if os.environ.get("CI"):
        return False
    return shutil.which("npx") is not None


_has_pdf_support = _can_generate_pdf()


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def discussion_dir(tmp_path):
    """Create a temporary discussion directory with test data."""
    disc = {
        "token": "test_token_abc123",
        "topic": "Test Discussion Topic",
        "status": "completed",
        "schema_version": 2,
        "participants": [
            {"id": "alice", "name": "Alice", "role": "Engineer", "display_name": "Alice"},
            {"id": "bob", "name": "Bob", "role": "Designer", "display_name": "Bob"},
        ],
        "speeches": [
            {
                "seq": 1,
                "round": 0,
                "agent_id": "alice",
                "display_name": "Alice",
                "participant": "alice",
                "content": "Hello, I think we should focus on performance.",
            },
            {
                "seq": 2,
                "round": 0,
                "agent_id": "bob",
                "display_name": "Bob",
                "participant": "bob",
                "content": "I agree, but UX is also important.",
            },
            {
                "seq": 3,
                "round": 1,
                "agent_id": "alice",
                "display_name": "Alice",
                "participant": "alice",
                "content": "Let's optimize the rendering pipeline first.",
            },
        ],
        "round_summaries": [
            {
                "round": 0,
                "consensus_points": ["Performance matters"],
                "disagreement_points": ["UX priority"],
                "convergence_score": 0.5,
            }
        ],
        "final_summary": {
            "consensus_points": ["Both agree on performance", "UX is secondary"],
            "disagreement_points": ["Order of implementation"],
            "verdict": "Start with performance, then UX.",
        },
        "conclusion": "The team agrees to prioritize performance optimization.",
        "consensus_score": 0.75,
        "revoked_tokens": [],
        "stream": {"seq": 3, "events": []},
        "updated_at": int(time.time()),
    }
    disc_path = tmp_path / "discussion.json"
    disc_path.write_text(json.dumps(disc, indent=2))
    return tmp_path


@pytest.fixture
def server(discussion_dir):
    """Start the web server and yield the base URL."""
    port = _find_free_port()
    proc = subprocess.Popen(
        ["node", str(SERVER_SCRIPT), "--port", str(port), "--discussion-dir", str(discussion_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to start
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            requests.get(f"{base}/api/test_token_abc123/data", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.3)
    else:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(f"Server failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}")

    yield base, port, discussion_dir
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
def pw_server(tmp_path):
    """Start a server WITH password protection."""
    disc = {
        "token": "pw_token_456",
        "topic": "Secret Discussion",
        "status": "completed",
        "schema_version": 2,
        "participants": [
            {"id": "alice", "name": "Alice", "role": "Engineer", "display_name": "Alice"},
        ],
        "speeches": [
            {
                "seq": 1,
                "round": 0,
                "agent_id": "alice",
                "display_name": "Alice",
                "participant": "alice",
                "content": "This is a secret speech.",
            },
        ],
        "round_summaries": [],
        "final_summary": None,
        "conclusion": None,
        "revoked_tokens": [],
        "stream": {"seq": 1, "events": []},
        "updated_at": int(time.time()),
    }
    disc_path = tmp_path / "discussion.json"
    disc_path.write_text(json.dumps(disc, indent=2))

    # Pre-computed bcrypt hash of "testpassword123"
    import subprocess as sp

    result = sp.run(
        ["node", "-e", "import('bcryptjs').then(b => b.hash('testpassword123', 10).then(h => console.log(h)))"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    pw_hash = result.stdout.strip()
    if not pw_hash:
        pytest.skip("bcryptjs not available for password hash generation")

    port = _find_free_port()
    proc = subprocess.Popen(
        [
            "node",
            str(SERVER_SCRIPT),
            "--port",
            str(port),
            "--discussion-dir",
            str(tmp_path),
            "--password-hash",
            pw_hash,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            requests.get(f"{base}/api/pw_token_456/data", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.3)
    else:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(f"Password server failed to start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}")

    yield base, port, tmp_path
    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Basic server & token tests
# ---------------------------------------------------------------------------


class TestServerLifecycle:
    def test_server_starts(self, server):
        base, _port, _ = server
        resp = requests.get(f"{base}/api/test_token_abc123/data", timeout=5)
        assert resp.status_code == 200

    def test_invalid_token_returns_403(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/invalid_token/data", timeout=5)
        assert resp.status_code == 403

    def test_404_for_unknown_route(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/test_token_abc123/nonexistent", timeout=5)
        assert resp.status_code == 404

    def test_data_endpoint_returns_discussion(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/test_token_abc123/data", timeout=5)
        data = resp.json()
        assert data["topic"] == "Test Discussion Topic"
        assert len(data["participants"]) == 2
        # Token should NOT be in the response
        assert "token" not in data


# ---------------------------------------------------------------------------
# Password protection tests
# ---------------------------------------------------------------------------


class TestPasswordProtection:
    def test_no_password_allows_access(self, server):
        """Server started without --password-hash should allow free access."""
        base, _, _ = server
        resp = requests.get(f"{base}/r/test_token_abc123", timeout=5)
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "").lower()

    def test_password_page_shown(self, pw_server):
        """Server with password should show the password verification page."""
        base, _, _ = pw_server
        resp = requests.get(f"{base}/r/pw_token_456", timeout=5)
        assert resp.status_code == 200
        text = resp.text
        # Should contain the password form, not the discussion
        assert "Access Verification" in text
        assert "password" in text.lower()

    def test_wrong_password_returns_401(self, pw_server):
        base, _, _ = pw_server
        resp = requests.post(
            f"{base}/api/validate-password",
            json={"password": "wrong_password"},
            timeout=5,
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["ok"] is False

    def test_correct_password_sets_cookie(self, pw_server):
        base, _, _ = pw_server
        resp = requests.post(
            f"{base}/api/validate-password",
            json={"password": "testpassword123"},
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        # Should set rt_pw cookie
        assert "rt_pw" in resp.cookies

    def test_password_cookie_grants_access(self, pw_server):
        """After authenticating, the cookie should allow direct access."""
        base, _, _ = pw_server
        session = requests.Session()
        # First, authenticate
        resp = session.post(
            f"{base}/api/validate-password",
            json={"password": "testpassword123"},
            timeout=5,
        )
        assert resp.status_code == 200
        # Now access the SPA — should get the viewer, not the password page
        resp = session.get(f"{base}/r/pw_token_456", timeout=5)
        assert resp.status_code == 200
        # The viewer page should contain __RT_CONFIG__, not "Access Verification"
        assert "__RT_CONFIG__" in resp.text

    def test_password_protected_api_requires_auth(self, pw_server):
        base, _, _ = pw_server
        # Without cookie, API should return 401
        resp = requests.get(f"{base}/api/pw_token_456/data", timeout=5)
        assert resp.status_code == 401
        data = resp.json()
        assert "Password required" in data.get("error", "")

    def test_password_protected_api_with_cookie(self, pw_server):
        base, _, _ = pw_server
        session = requests.Session()
        # Authenticate
        session.post(
            f"{base}/api/validate-password",
            json={"password": "testpassword123"},
            timeout=5,
        )
        # Access API with cookie
        resp = session.get(f"{base}/api/pw_token_456/data", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "Secret Discussion"


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExportMarkdown:
    def test_export_markdown_success(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/test_token_abc123/export/markdown", timeout=10)
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "markdown" in ct
        # Check content
        md = resp.text
        assert "Test Discussion Topic" in md
        assert "Alice" in md
        assert "Bob" in md
        assert "performance" in md.lower()

    def test_export_markdown_has_all_sections(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/test_token_abc123/export/markdown", timeout=10)
        md = resp.text
        assert "# Test Discussion Topic" in md
        assert "## Participants" in md
        assert "## Round" in md
        assert "## Round Summaries" in md
        assert "## Final Summary" in md
        assert "## Conclusion" in md

    def test_export_markdown_invalid_token(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/bad_token/export/markdown", timeout=5)
        assert resp.status_code == 403

    def test_export_markdown_password_protected(self, pw_server):
        base, _, _ = pw_server
        # Without auth, should get 401
        resp = requests.get(f"{base}/api/pw_token_456/export/markdown", timeout=5)
        assert resp.status_code == 401

    def test_export_markdown_with_password_auth(self, pw_server):
        base, _, _ = pw_server
        session = requests.Session()
        session.post(
            f"{base}/api/validate-password",
            json={"password": "testpassword123"},
            timeout=5,
        )
        resp = session.get(f"{base}/api/pw_token_456/export/markdown", timeout=10)
        assert resp.status_code == 200
        md = resp.text
        assert "Secret Discussion" in md


class TestExportPDF:
    @pytest.mark.skipif(not _has_pdf_support, reason="md-to-pdf not available (needs Chromium)")
    def test_export_pdf_success(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/test_token_abc123/export/pdf", timeout=90)
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "pdf" in ct
        # PDF should start with %PDF
        assert resp.content[:4] == b"%PDF"

    @pytest.mark.skipif(not _has_pdf_support, reason="md-to-pdf not available (needs Chromium)")
    def test_export_pdf_filename(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/test_token_abc123/export/pdf", timeout=90)
        cd = resp.headers.get("content-disposition", "")
        assert "Test_Discussion_Topic" in cd or "discussion" in cd

    def test_export_pdf_invalid_token(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/bad_token/export/pdf", timeout=5)
        assert resp.status_code == 403

    def test_export_pdf_password_protected(self, pw_server):
        base, _, _ = pw_server
        resp = requests.get(f"{base}/api/pw_token_456/export/pdf", timeout=5)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# i18n tests
# ---------------------------------------------------------------------------


class TestI18n:
    def test_i18n_js_served(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/i18n.js", timeout=5)
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "javascript" in ct
        assert "__RT_I18N__" in resp.text

    def test_viewer_js_served(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/viewer.js", timeout=5)
        assert resp.status_code == 200
        # Should contain i18n initialization
        assert "__RT_I18N__" in resp.text

    def test_index_html_contains_lang_elements(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/r/test_token_abc123", timeout=5)
        html = resp.text
        assert "data-i18n" in html
        assert "langSwitchBtn" in html
        assert "exportBtn" in html
