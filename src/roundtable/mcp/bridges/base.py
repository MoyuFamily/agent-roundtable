"""Base class for platform bridges that connect non-MCP agents to Roundtable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AgentBridge(ABC):
    """Abstract bridge for platforms that don't natively support MCP.

    A bridge runs as a local process that:
    1. Registers itself as an agent
    2. Listens for invitations (via inbox polling or webhook)
    3. Translates roundtable tool calls into platform-native API calls
    """

    @abstractmethod
    def start(self) -> None:
        """Start the bridge (register agent, begin listening)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the bridge gracefully."""

    @abstractmethod
    async def on_invitation(self, invitation: dict[str, Any]) -> bool:
        """Handle an incoming invitation. Return True to accept, False to decline."""

    @abstractmethod
    async def generate_speech(self, context: dict[str, Any]) -> str:
        """Generate a speech given discussion context. Platform-specific implementation."""

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """The agent's unique identifier."""

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform name (e.g. 'codex', 'workbuddy')."""
