"""Generic Python API adapter for Roundtable.

For use outside any specific agent framework. Provides a simple,
importable interface that works in any Python script.

Usage::

    from roundtable.adapters.generic import Roundtable

    rt = Roundtable()
    result = rt.init(topic="...", participants=[...])
    result = rt.speak(discussion_id, "alice", "Hello!")
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB


class Roundtable:
    """Simple facade over RoundtableCore.

    All methods return dicts (JSON-serializable). Errors are returned
    as ``{"error": "message"}`` dicts instead of raising exceptions,
    making it safe for untrusted callers.
    """

    def __init__(self, db_path: Optional[str] = None):
        db = RoundtableDB(db_path) if db_path else RoundtableDB()
        self._core = RoundtableCore(db)

    def init(
        self,
        topic: str,
        participants: List[Dict[str, Any]],
        **kwargs,
    ) -> Dict[str, Any]:
        """Create a new discussion."""
        try:
            return self._core.create_discussion(topic, participants, **kwargs)
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
