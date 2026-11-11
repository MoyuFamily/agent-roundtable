"""Base class for platform bridges that connect non-MCP agents to Roundtable."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AgentBridge(ABC):
    """Abstract bridge for platforms that don't natively support MCP.

    A bridge runs as a local process that:
    1. Registers itself as an agent
    2. Receives invitations and tool calls from a host
    3. Records host-generated speeches in the shared discussion

    Model execution and inbox consumption belong to the host.
    """

    @abstractmethod
    def start(self) -> None:
        """Start the bridge (register agent, begin listening)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the bridge gracefully."""

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """The agent's unique identifier."""

    @property
    @abstractmethod
    def platform(self) -> str:
        """Platform name (e.g. 'codex', 'workbuddy')."""
