"""Protocol acceptance against actual CLI processes, not in-process MCP mocks."""

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")


@pytest.mark.parametrize("transport", ["stdio", "sse"])
def test_two_clients_and_reader_restart(transport):
    if transport == "sse":
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("Loopback binding is unavailable")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/check_mcp_runtime.py"),
            "--source-root",
            str(root),
            "--transport",
            transport,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    checks = json.loads(result.stdout)
    assert checks["two_clients"] and checks["reader_restart"]
    assert checks["exact_subscription_uris"] and checks["unsubscribe"]
    assert checks["inbox_ack"] and checks["conclusion"]
