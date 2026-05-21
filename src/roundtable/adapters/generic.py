"""Generic Python API adapter for Roundtable.

For use outside any specific agent framework. Provides a simple,
importable interface that works in any Python script.

Usage::

    from roundtable.adapters.generic import Roundtable

    rt = Roundtable()
    result = rt.init(topic="...", participants=[...])
    result = rt.speak(discussion_id, "alice", "Hello!")

With notifications::

    def my_send(platform, chat_id, message):
        print(f"[{platform}:{chat_id}] {message}")

    rt = Roundtable(send_fn=my_send)
    result = rt.init(
        topic="...",
        participants=[...],
        notifications={
            "enabled": True,
            "channels": [{"platform": "console", "chat_id": "default"}],
        },
    )
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB


class Roundtable:
    """Simple facade over RoundtableCore.

    All methods return dicts (JSON-serializable). Errors are returned
    as ``{"error": "message"}`` dicts instead of raising exceptions,
    making it safe for untrusted callers.

    Args:
        db_path: Optional path to the SQLite database file.
        send_fn: Optional callback(platform, chat_id, message) for notifications.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        send_fn: Optional[Callable[[str, str, str], None]] = None,
    ):
        db = RoundtableDB(db_path) if db_path else RoundtableDB()
        self._core = RoundtableCore(db, send_fn=send_fn)

    def init(
        self,
        topic: str,
        participants: List[Dict[str, Any]],
        *,
        notifications: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Create a new discussion.

        Args:
            topic: Discussion topic.
            participants: List of participant dicts (min 2).
            notifications: Optional notification config dict.
            **kwargs: Additional arguments passed to create_discussion.
        """
        try:
            return self._core.create_discussion(
                topic, participants, notifications=notifications, **kwargs
            )
        except (ValueError, Exception) as e:
            return {"error": str(e)}

    def speak(
        self,
        discussion_id: str,
        participant: str,
        content: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Record a speech."""
        try:
            return self._core.speak(discussion_id, participant, content, **kwargs)
        except Exception as e:
            return {"error": str(e)}

    def read(self, discussion_id: str, **kwargs) -> Dict[str, Any]:
        """Read discussion history."""
        try:
            return self._core.read(discussion_id, **kwargs)
        except Exception as e:
            return {"error": str(e)}

    def get_status(self, discussion_id: str) -> Dict[str, Any]:
        """Get discussion status."""
        try:
            return self._core.status(discussion_id)
        except Exception as e:
            return {"error": str(e)}

    def summarize(self, discussion_id: str, *, compact: bool = False) -> Dict[str, Any]:
        """Get summary data."""
        try:
            return self._core.summarize(discussion_id, compact=compact)
        except Exception as e:
            return {"error": str(e)}

    def end(
        self,
        discussion_id: str,
        *,
        force: bool = False,
        conclusion: Optional[str] = None,
    ) -> Dict[str, Any]:
        """End a discussion."""
        try:
            return self._core.end_discussion(discussion_id, force=force, conclusion=conclusion)
        except Exception as e:
            return {"error": str(e)}

    def list(self, **kwargs) -> Dict[str, Any]:
        """List discussions."""
        try:
            return self._core.list_discussions(**kwargs)
        except Exception as e:
            return {"error": str(e)}

    def advance(self, discussion_id: str) -> Dict[str, Any]:
        """Explicitly advance to the next round.

        Use when auto-advance doesn't trigger. If max_rounds is exceeded,
        the discussion is automatically concluded.
        """
        try:
            return self._core.advance(discussion_id)
        except Exception as e:
            return {"error": str(e)}

    def run_demo(
        self,
        *,
        topic: Optional[str] = None,
        participants: Optional[List[Dict[str, Any]]] = None,
        max_rounds: int = 3,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """Run a complete demo discussion with pre-scripted content.

        Simulates a realistic multi-round discussion. Prints formatted
        output to terminal when verbose=True.

        Args:
            topic: Custom topic (uses default demo topic if None).
            participants: Custom participants (uses default if None).
            max_rounds: Number of rounds (default 3).
            verbose: Print formatted output to stdout.
        """
        try:
            return self._core.run_demo(
                topic=topic,
                participants=participants,
                max_rounds=max_rounds,
                verbose=verbose,
            )
        except Exception as e:
            return {"error": str(e)}

    def notify(
        self,
        discussion_id: str,
        event: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Manually trigger a notification for a discussion event.

        Valid events: round_start, speech, round_end, concluded.
        """
        try:
            return self._core.notify(discussion_id, event, **kwargs)
        except Exception as e:
            return {"error": str(e)}
