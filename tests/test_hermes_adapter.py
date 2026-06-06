"""Tests for Hermes adapter robustness helpers."""

from __future__ import annotations

import json

from roundtable.adapters import hermes


def test_handle_status_coerces_discussion_id(monkeypatch):
    calls = []

    def fake_handle(args, method, **extra):
        calls.append((args, method, extra))
        return json.dumps({"ok": True})

    monkeypatch.setattr(hermes, "_handle", fake_handle)

    result = json.loads(hermes._handle_status({"discussion_id": 123}))

    assert result["ok"] is True
    assert calls == [({"discussion_id": "123"}, "status", {})]


def test_handle_notify_handles_none_values():
    result = json.loads(hermes._handle_notify({"discussion_id": None, "event": None}))

    assert result["error"] == "discussion_id is required"


def test_hermes_send_fn_submits_notification(monkeypatch):
    calls = []

    class FakeExecutor:
        def submit(self, fn, *args):
            calls.append((fn, args))

    monkeypatch.setattr(hermes, "_notification_executor", FakeExecutor())

    hermes._hermes_send_fn("feishu", "oc_test", "hello")

    assert calls == [(hermes._send_notification_sync, ("feishu", "oc_test", "hello"))]


def test_hermes_send_fn_swallows_executor_shutdown(monkeypatch):
    class ClosedExecutor:
        def submit(self, fn, *args):
            raise RuntimeError("shutdown")

    monkeypatch.setattr(hermes, "_notification_executor", ClosedExecutor())

    hermes._hermes_send_fn("feishu", "oc_test", "hello")


def test_open_web_viewer_uses_webbrowser(monkeypatch):
    opened_urls = []

    def fake_open(url):
        opened_urls.append(url)
        return True

    monkeypatch.setattr(hermes.webbrowser, "open", fake_open)

    opened, error = hermes._open_web_viewer("http://127.0.0.1:8199/r/test")

    assert opened is True
    assert error is None
    assert opened_urls == ["http://127.0.0.1:8199/r/test"]
