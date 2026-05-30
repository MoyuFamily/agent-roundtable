"""Bridges for non-MCP platforms (Codex, WorkBuddy, etc)."""

from roundtable.mcp.bridges.base import AgentBridge
from roundtable.mcp.bridges.generic import GenericBridge

__all__ = ["AgentBridge", "GenericBridge"]
