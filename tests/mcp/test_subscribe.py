"""Session cleanup must not remove another client's exact subscriptions.

Protocol registration, notifications and restart are exercised by test_cli_runtime.
"""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from roundtable.mcp.server import SubscriptionManager


def test_unsubscribe_and_disconnect_keep_other_sessions_subscribed():
    subs = SubscriptionManager()
    session = object()
    other = object()
    base = "roundtable://discussions/rt_abc"
    transcript = base + "/transcript"
    subs.subscribe(base, session)
    subs.subscribe(base, session)
    subs.subscribe(transcript, session)
    subs.subscribe(base, other)
    assert subs.uris_for(session) == {base, transcript}
    subs.unsubscribe(base, session)
    assert subs.uris_for(session) == {transcript}
    assert subs.uris_for(other) == {base}
    subs.remove_session(session)
    subs.remove_session(session)
    assert subs.uris_for(session) == set()
    assert subs.uris_for(other) == {base}
