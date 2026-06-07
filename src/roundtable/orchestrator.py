"""Dispatch orchestration modes for Roundtable.

Managed mode is for agents controlled inside one host/platform. Federated mode
uses the runtime registry, heartbeats, inbox, and HTTP bridge delivery.
"""

from __future__ import annotations

from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.tools import handle_tool_call


class ManagedOrchestrator:
    """Start same-platform meetings without runtime registry delivery."""

    def __init__(self, db: RoundtableDB | None = None):
        self.db = db or RoundtableDB()
        self.core = RoundtableCore(db=self.db)

    def start_discussion(
        self,
        *,
        topic: str,
        participants: list[dict[str, Any]],
        coordinator_agent_id: str = "coordinator",
        context: str | None = None,
        max_rounds: int = 3,
        speech_order: str = "fixed",
        web: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        discussion = self.core.create_discussion(
            topic=topic,
            participants=participants,
            context=context,
            max_rounds=max_rounds,
            speech_order=speech_order,
            created_by=coordinator_agent_id,
            status="active",
            web=web,
        )
        conn = self.db.connect()
        try:
            dispatch = self.db.create_dispatch(
                conn,
                discussion["discussion_id"],
                coordinator_agent_id,
                mode="managed",
                start_policy="immediate",
                min_accepts=0,
                timeout_seconds=0,
                metadata=metadata,
            )
            readiness = self.db.apply_dispatch_readiness(conn, dispatch["id"])
        finally:
            conn.close()
        return {"ok": True, "mode": "managed", "discussion": discussion, **readiness}


class FederatedOrchestrator:
    """Summon registered agents through registry/inbox/HTTP delivery."""

    def __init__(self, db: RoundtableDB | None = None):
        self.db = db or RoundtableDB()
        self.core = RoundtableCore(db=self.db)

    def summon(
        self,
        *,
        coordinator_agent_id: str,
        topic: str | None = None,
        discussion_id: str | None = None,
        agent_ids: list[str] | None = None,
        required_skill: str | None = "agent-roundtable",
        availability: str | None = None,
        min_accepts: int = 1,
        start_policy: str = "quorum",
        dispatch_timeout_seconds: int = 60,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "coordinator_agent_id": coordinator_agent_id,
            "required_skill": required_skill,
            "availability": availability,
            "min_accepts": min_accepts,
            "start_policy": start_policy,
            "dispatch_timeout_seconds": dispatch_timeout_seconds,
            "metadata": metadata,
            **kwargs,
        }
        if topic is not None:
            arguments["topic"] = topic
        if discussion_id is not None:
            arguments["discussion_id"] = discussion_id
        if agent_ids is not None:
            arguments["agent_ids"] = agent_ids
        return handle_tool_call(self.core, self.db, "roundtable_summon_agents", arguments)
