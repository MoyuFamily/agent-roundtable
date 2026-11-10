"""Base adapter interface for Roundtable.

Defines the ``RoundtableAdapter`` abstract base class that all agent
framework adapters must implement. The host manages the lifecycle and records
returned speeches through ``RoundtableCore`` or platform tools. Registering an
adapter does not connect it to an automatic Core execution loop.

Usage::

    from roundtable.adapters.base import RoundtableAdapter

    class MyAdapter(RoundtableAdapter):
        def get_persona(self):
            return {"name": "Alice", "role": "engineer", "avatar": "👩‍💻"}

        async def speak(self, context):
            return "My opinion on " + context["topic"]

        async def listen(self, speech):
            return None  # no special reaction
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class RoundtableAdapter(ABC):
    """Abstract base class for Roundtable agent adapters.

    Each adapter wraps one agent framework (Hermes, LangChain, custom, etc.)
    and exposes a uniform interface for the roundtable discussion engine.

    Lifecycle (implemented by the host):
        1. ``__init__`` — adapter is instantiated once per discussion
        2. ``get_persona`` — called before first turn to get agent metadata
        3. ``speak`` / ``listen`` — called per turn in round-robin order

    Error handling is a host responsibility:
        - Handle failed speech/reaction calls and choose retry, replacement, or stop.
        - Apply the review's time and cost budget.
        - Core does not enforce adapter timeouts or automatically skip participants.
    """

    @abstractmethod
    def get_persona(self) -> dict[str, Any]:
        """Return agent personality metadata.

        Returns:
            dict with keys:
                - ``name`` (str, required): Display name
                - ``role`` (str, required): Role identifier (e.g. "engineer")
                - ``avatar`` (str, optional): Emoji or image URL
                - ``title`` (str, optional): Role title (e.g. "技术总监")
                - ``description`` (str, optional): Role description
        """
        ...

    @abstractmethod
    async def speak(self, context: dict[str, Any]) -> str:
        """Generate a speech for the current turn.

        Args:
            context: Discussion context dict with keys:
                - ``topic`` (str): Discussion topic
                - ``history`` (list[dict]): All speeches so far
                - ``round`` (int): Current round number (1-indexed)
                - ``findings`` (list[dict]): Consensus/disagreement points
                - ``participants`` (list[dict]): All participant personas

        Returns:
            Speech content as a Markdown string.
        """
        ...

    @abstractmethod
    async def listen(self, speech: dict[str, Any]) -> dict[str, Any] | None:
        """React to another agent's speech.

        Called for every speech that isn't the current agent's own.
        Return ``None`` for no reaction, or a dict with metadata.

        Args:
            speech: Dict with keys:
                - ``speaker`` (str): Speaker agent name
                - ``content`` (str): Speech content
                - ``round`` (int): Round number

        Returns:
            ``None`` or ``{"reaction": "agree|disagree|question", "note": str}``
        """
        ...

    def on_round_start(self, round_num: int) -> None:
        """Hook called at the start of each round.

        Override to implement per-round setup logic (e.g. fetch new context).
        Default is a no-op.
        """

    def on_discussion_end(self, conclusion: str) -> None:
        """Hook called when the discussion concludes.

        Override for cleanup or summary logic. Default is a no-op.
        """
