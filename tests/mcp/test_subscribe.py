"""Tests for MCP resource subscribe/unsubscribe."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp")

from roundtable.mcp.server import SubscriptionManager  # noqa: E402


def test_subscription_manager_basic():
    subs = SubscriptionManager()
    session_a = MagicMock()
    session_b = MagicMock()

    uri = "roundtable://discussions/rt_abc"
    subs.subscribe(uri, session_a)
    subs.subscribe(uri, session_b)

    assert set(subs.sessions_for(uri)) == {session_a, session_b}


def test_subscription_manager_unsubscribe():
    subs = SubscriptionManager()
    session = MagicMock()
    uri = "roundtable://discussions/rt_abc"

    subs.subscribe(uri, session)
    assert subs.sessions_for(uri) == [session]

    subs.unsubscribe(uri, session)
    assert subs.sessions_for(uri) == []


def test_subscription_manager_idempotent_subscribe():
    subs = SubscriptionManager()
    session = MagicMock()
    uri = "roundtable://discussions/rt_abc"

    subs.subscribe(uri, session)
    subs.subscribe(uri, session)
    assert subs.sessions_for(uri) == [session]


def test_transcript_subscribers_get_discussion_updates():
    """A subscriber to /transcript should also receive updates for the parent
    discussion URI, and vice versa."""
    subs = SubscriptionManager()
    discussion_session = MagicMock()
    transcript_session = MagicMock()

    base = "roundtable://discussions/rt_abc"
    subs.subscribe(base, discussion_session)
    subs.subscribe(f"{base}/transcript", transcript_session)

    # An event on the base URI should reach both subscribers.
    sessions = set(subs.sessions_for(base))
    assert discussion_session in sessions
    assert transcript_session in sessions

    # An event on the transcript URI should reach both as well.
    sessions = set(subs.sessions_for(f"{base}/transcript"))
    assert discussion_session in sessions
    assert transcript_session in sessions


def test_unsubscribe_removes_uri_when_empty():
    subs = SubscriptionManager()
    session = MagicMock()
    uri = "roundtable://discussions/rt_abc"

    subs.subscribe(uri, session)
    subs.unsubscribe(uri, session)

    assert subs.sessions_for(uri) == []
    assert uri not in subs._subs


def test_create_server_registers_subscribe_handler(tmp_path):
    """create_server should register subscribe/unsubscribe handlers and
    advertise the subscribe capability."""
    from mcp.types import SubscribeRequest, UnsubscribeRequest

    from roundtable.mcp.server import build_initialization_options, create_server

    server = create_server(db_path=str(tmp_path / "test.db"))

    assert SubscribeRequest in server.request_handlers
    assert UnsubscribeRequest in server.request_handlers

    opts = build_initialization_options(server)
    assert opts.capabilities.resources is not None
    assert opts.capabilities.resources.subscribe is True
