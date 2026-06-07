"""Tests for managed and federated dispatch orchestration modes."""

from __future__ import annotations

from roundtable.db import RoundtableDB
from roundtable.mcp.tools import handle_tool_call
from roundtable.orchestrator import FederatedOrchestrator, ManagedOrchestrator


def test_managed_orchestrator_starts_active_discussion(tmp_path):
    db = RoundtableDB(tmp_path / "managed.db")
    orchestrator = ManagedOrchestrator(db=db)

    result = orchestrator.start_discussion(
        topic="Managed meeting",
        coordinator_agent_id="coord",
        participants=[
            {"profile": "coord", "role": "Coordinator"},
            {"profile": "local-agent", "role": "Reviewer"},
        ],
    )

    assert result["ok"] is True
    assert result["mode"] == "managed"
    assert result["dispatch"]["mode"] == "managed"
    assert result["dispatch"]["status"] == "active"
    assert result["discussion"]["status"] == "active"


def test_federated_orchestrator_uses_registry_summon(tmp_path):
    db = RoundtableDB(tmp_path / "federated.db")
    orchestrator = FederatedOrchestrator(db=db)
    handle_tool_call(
        orchestrator.core,
        db,
        "roundtable_register_agent",
        {"agent_id": "coord", "platform": "claude-code"},
    )
    handle_tool_call(
        orchestrator.core,
        db,
        "roundtable_register_agent",
        {
            "agent_id": "federated-agent",
            "platform": "codex",
            "skills": ["agent-roundtable"],
            "availability": "idle",
        },
    )

    result = orchestrator.summon(
        topic="Federated meeting",
        coordinator_agent_id="coord",
        agent_ids=["federated-agent"],
        required_skill="agent-roundtable",
    )

    assert result["ok"] is True
    assert result["dispatch"]["mode"] == "federated"
    assert result["summons"][0]["agent_id"] == "federated-agent"
