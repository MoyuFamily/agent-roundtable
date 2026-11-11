"""Integration tests for the Roundtable Web Viewer server.

Tests cover:
- Password protection flow (bcrypt + HMAC cookie)
- Export endpoints (Markdown, PDF)
- i18n and language switching
- Basic server lifecycle (startup, token validation)
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "roundtable" / "web" / "server.mjs"


@pytest.fixture
def pdf_support():
    """Only skip missing prerequisites; runtime export failures are test failures."""
    result = subprocess.run(
        ["node", str(SERVER_SCRIPT.with_name("pdf-worker.mjs")), "--check"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        if os.environ.get("ROUNDTABLE_REQUIRE_PDF") == "1":
            pytest.fail(f"Required PDF dependency unavailable: {result.stderr}")
        pytest.skip(f"PDF dependency unavailable: {result.stderr.strip()}")


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def discussion_dir(tmp_path):
    """Create a temporary discussion directory with test data.

    The server expects --data-dir pointing to a parent directory.
    Each discussion lives in a subdirectory: <data-dir>/<id>/discussion.json
    """
    disc_subdir = tmp_path / "test_disc"
    disc_subdir.mkdir()
    disc = {
        "token_hash": hashlib.sha256(b"test_token_abc123").hexdigest(),
        "owner_secret_hash": hashlib.sha256(b"owner_secret_123").hexdigest(),
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
        "revoked_token_hashes": [],
        "stream": {"seq": 3, "events": []},
        "updated_at": int(time.time()),
    }
    disc_path = disc_subdir / "discussion.json"
    disc_path.write_text(json.dumps(disc, indent=2))
    return tmp_path  # return the parent (data-dir)


@pytest.fixture
def server(discussion_dir, request):
    """Start the web server and yield the base URL."""
    options = dict(getattr(request, "param", {}))
    script = SERVER_SCRIPT
    if options.pop("without_dependencies", False):
        script = discussion_dir / "server.mjs"
        script.write_bytes(SERVER_SCRIPT.read_bytes())
    port = _find_free_port()
    proc = subprocess.Popen(
        ["node", str(script), "--port", str(port), "--data-dir", str(discussion_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "TMPDIR": str(discussion_dir), **options},
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
    """Start a server WITH password protection (password_hash in discussion.json)."""
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

    disc_subdir = tmp_path / "pw_disc"
    disc_subdir.mkdir()
    disc = {
        "token_hash": hashlib.sha256(b"pw_token_456").hexdigest(),
        "topic": "Secret Discussion",
        "status": "completed",
        "schema_version": 2,
        "password_hash": pw_hash,
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
        "revoked_token_hashes": [],
        "stream": {"seq": 1, "events": []},
        "updated_at": int(time.time()),
    }
    disc_path = disc_subdir / "discussion.json"
    disc_path.write_text(json.dumps(disc, indent=2))

    port = _find_free_port()
    proc = subprocess.Popen(
        [
            "node",
            str(SERVER_SCRIPT),
            "--port",
            str(port),
            "--data-dir",
            str(tmp_path),
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
        assert "token_hash" not in data
        assert "owner_secret_hash" not in data

    def test_healthz_identifies_roundtable_server(self, server):
        base, _, discussion_dir = server
        resp = requests.get(f"{base}/healthz", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["service"] == "roundtable-web"
        assert data["data_dir"] == str(discussion_dir)


# ---------------------------------------------------------------------------
# Password protection tests
# ---------------------------------------------------------------------------


class TestPasswordProtection:
    def test_login_protects_content_and_issues_only_hashed_token_cookie(self, pw_server):
        base, _, _ = pw_server
        session = requests.Session()
        page = session.get(f"{base}/r/pw_token_456", timeout=5)
        assert "Access Verification" in page.text
        assert session.get(f"{base}/api/pw_token_456/data", timeout=5).status_code == 401
        login = f"{base}/api/pw_token_456/validate-password"
        wrong = session.post(login, json={"password": "wrong"}, timeout=5)
        assert wrong.status_code == 401
        assert not session.cookies
        response = session.post(login, json={"password": "testpassword123"}, timeout=5)
        assert response.status_code == 200
        token_hash = hashlib.sha256(b"pw_token_456").hexdigest()
        assert set(session.cookies.keys()) == {f"rt_pw_{token_hash}"}
        assert "pw_token_456" not in response.headers["Set-Cookie"]
        page = session.get(f"{base}/r/pw_token_456", timeout=5)
        assert page.status_code == 200
        assert "__RT_CONFIG__" in page.text
        data = session.get(f"{base}/api/pw_token_456/data", timeout=5)
        assert data.status_code == 200
        assert data.json()["topic"] == "Secret Discussion"
        markdown = session.get(f"{base}/api/pw_token_456/export/markdown", timeout=5)
        assert markdown.status_code == 200
        assert "secret speech" in markdown.text


@pytest.mark.parametrize("server", [{}, {"without_dependencies": True}], indirect=True, ids=["express", "builtin"])
def test_route_failures_return_errors_and_leave_server_running(server):
    base, _, directory = server
    response = requests.get(f"{base}/api/%FF/data", timeout=5)
    assert response.status_code == 400
    assert "error" in response.json()
    if (directory / "server.mjs").exists():
        assert "X-Powered-By" not in response.headers
    path = directory / "test_disc" / "discussion.json"
    data = json.loads(path.read_text())
    data["topic"] = 123  # A malformed imported snapshot fails inside an async export route.
    path.write_text(json.dumps(data))
    response = requests.get(f"{base}/api/test_token_abc123/export/markdown", timeout=5)
    assert response.status_code == 500
    assert response.json() == {"error": "Request failed"}
    assert requests.get(f"{base}/healthz", timeout=5).status_code == 200
    data["topic"] = "Recovered discussion"
    path.write_text(json.dumps(data))
    response = requests.get(f"{base}/api/test_token_abc123/export/markdown", timeout=5)
    assert response.status_code == 200
    assert "Recovered discussion" in response.text


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


class TestExportPDF:
    def test_export_pdf_invalid_token(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/api/bad_token/export/pdf", timeout=5)
        assert resp.status_code == 403

    def test_export_pdf_password_protected(self, pw_server):
        base, _, _ = pw_server
        resp = requests.get(f"{base}/api/pw_token_456/export/pdf", timeout=5)
        assert resp.status_code == 401

    def test_concurrent_exports_use_separate_files_and_cleanup(self, server, pdf_support):
        base, _, directory = server
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda _: requests.get(f"{base}/api/test_token_abc123/export/pdf", timeout=90), range(2))
            )
        for response in results:
            assert response.status_code == 200, response.text
            assert response.headers["content-type"] == "application/pdf"
            assert response.headers["content-disposition"] == 'attachment; filename="Test_Discussion_Topic.pdf"'
            assert int(response.headers["content-length"]) == len(response.content)
            assert response.content.startswith(b"%PDF")
        assert not list(directory.glob("roundtable-pdf-*"))
        assert not list((directory / "test_disc").glob("*.tmp.*"))

    def test_pdf_treats_html_and_remote_images_as_untrusted_text(self, server, pdf_support):
        base, _, directory = server
        hits = []

        class Probe(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        probe = ThreadingHTTPServer(("127.0.0.1", 0), Probe)
        thread = threading.Thread(target=probe.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{probe.server_port}/unexpected"
            path = directory / "test_disc" / "discussion.json"
            data = json.loads(path.read_text())
            data["speeches"][0]["content"] = (
                f"![remote image]({url})\n<img src='{url}'>\n"
                f"<script>fetch('{url}')</script>\n<iframe src='{url}'></iframe>"
            )
            path.write_text(json.dumps(data))
            response = requests.get(f"{base}/api/test_token_abc123/export/pdf", timeout=90)
            assert response.status_code == 200, response.text
            assert hits == []
        finally:
            probe.shutdown()
            probe.server_close()
            thread.join(timeout=2)

    @pytest.mark.parametrize("server", [{"ROUNDTABLE_PDF_TIMEOUT_MS": "1"}], indirect=True)
    def test_pdf_timeout_cleans_worker_and_files(self, server):
        base, _, directory = server
        response = requests.get(f"{base}/api/test_token_abc123/export/pdf", timeout=10)
        assert response.status_code == 503
        assert "timed out" in response.json()["detail"]
        assert not list(directory.glob("roundtable-pdf-*"))
        assert requests.get(f"{base}/api/test_token_abc123/export/markdown", timeout=5).status_code == 200

    def test_aborted_export_cleans_temporary_directory(self, server, pdf_support):
        base, port, directory = server
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(
                b"GET /api/test_token_abc123/export/pdf HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            deadline = time.monotonic() + 5
            while not list(directory.glob("roundtable-pdf-*")) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert list(directory.glob("roundtable-pdf-*"))
        deadline = time.monotonic() + 5
        while list(directory.glob("roundtable-pdf-*")) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not list(directory.glob("roundtable-pdf-*"))
        assert requests.get(f"{base}/api/test_token_abc123/export/markdown", timeout=5).status_code == 200

    @pytest.mark.parametrize("server", [{"PUPPETEER_EXECUTABLE_PATH": "/missing/roundtable/chromium"}], indirect=True)
    def test_missing_browser_reports_unavailable_without_hiding_other_failures(self, server):
        base, _, directory = server
        response = requests.get(f"{base}/api/test_token_abc123/export/pdf", timeout=10)
        assert response.status_code == 503
        assert response.json()["error"] == "PDF export unavailable"
        assert not list(directory.glob("roundtable-pdf-*"))


# ---------------------------------------------------------------------------
# Owner-only revoke tests
# ---------------------------------------------------------------------------


class TestRevokeAuthorization:
    def test_revoke_without_owner_secret_returns_403(self, server):
        base, _, _ = server
        resp = requests.post(f"{base}/api/test_token_abc123/revoke", json={}, timeout=5)
        assert resp.status_code == 403
        assert "Owner authorization" in resp.json()["error"]

    def test_revoke_with_wrong_owner_secret_returns_403(self, server):
        base, _, _ = server
        resp = requests.post(
            f"{base}/api/test_token_abc123/revoke",
            json={"owner_secret": "wrong"},
            timeout=5,
        )
        assert resp.status_code == 403

    def test_revoke_with_owner_secret_succeeds(self, server):
        base, _, discussion_dir = server
        resp = requests.post(
            f"{base}/api/test_token_abc123/revoke",
            json={"owner_secret": "owner_secret_123"},
            timeout=5,
        )
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True

        disc_path = discussion_dir / "test_disc" / "discussion.json"
        data = json.loads(disc_path.read_text())
        token_hash = hashlib.sha256(b"test_token_abc123").hexdigest()
        assert token_hash in data["revoked_token_hashes"]

    def test_revoke_preserves_cross_process_disk_updates(self, server):
        base, _, discussion_dir = server
        disc_path = discussion_dir / "test_disc" / "discussion.json"
        data = json.loads(disc_path.read_text())
        data["dispatch_summary"] = {"accepted": 2, "pending": 0}
        data["speeches"].append(
            {
                "seq": 4,
                "round": 1,
                "agent_id": "carol",
                "display_name": "Carol",
                "participant": "carol",
                "content": "A cross-process update that Node must preserve.",
            }
        )
        disc_path.write_text(json.dumps(data, indent=2))

        resp = requests.post(
            f"{base}/api/test_token_abc123/revoke",
            json={"owner_secret": "owner_secret_123"},
            timeout=5,
        )
        assert resp.status_code == 200

        result = json.loads(disc_path.read_text())
        token_hash = hashlib.sha256(b"test_token_abc123").hexdigest()
        assert token_hash in result["revoked_token_hashes"]
        assert result["dispatch_summary"] == {"accepted": 2, "pending": 0}
        assert any(s["agent_id"] == "carol" for s in result["speeches"])

    def test_owner_viewer_config_contains_owner_capability(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/r/test_token_abc123?owner=owner_secret_123", timeout=5)
        assert resp.status_code == 200
        assert '"canRevoke":true' in resp.text
        assert '"ownerSecret":"owner_secret_123"' in resp.text

    def test_public_viewer_config_hides_owner_secret(self, server):
        base, _, _ = server
        resp = requests.get(f"{base}/r/test_token_abc123", timeout=5)
        assert resp.status_code == 200
        assert '"canRevoke":false' in resp.text
        assert "owner_secret_123" not in resp.text


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
