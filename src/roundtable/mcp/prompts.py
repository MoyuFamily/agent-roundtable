"""MCP Prompt definitions for Roundtable.

Prompt specs are plain dicts so this module is importable without the
optional `mcp` SDK.
"""

from __future__ import annotations

from typing import Any

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB

PROMPT_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "coordinator_kickoff",
        "description": "Prepare a decision brief, assign professional roles, and start a review",
        "arguments": [
            {"name": "topic", "description": "Discussion topic", "required": True},
            {"name": "participants", "description": "Comma-separated participant names", "required": True},
            {"name": "max_rounds", "description": "Maximum rounds", "required": False},
            {
                "name": "decision_brief",
                "description": "Goals, constraints, options, evidence, and budget",
                "required": False,
            },
        ],
    },
    {
        "name": "participant_turn",
        "description": "Prepare an independent role analysis or respond to cross-role trade-offs",
        "arguments": [
            {"name": "discussion_id", "description": "Discussion ID", "required": True},
            {"name": "role", "description": "Your role in the discussion", "required": True},
            {"name": "perspective", "description": "Your perspective/focus area", "required": False},
            {
                "name": "phase",
                "description": "independent or response; defaults to independent through round 1, then response",
                "required": False,
            },
        ],
    },
    {
        "name": "coordinator_summarize",
        "description": "Compare options, retain dissent, and prepare a decision brief for the user",
        "arguments": [
            {"name": "discussion_id", "description": "Discussion ID", "required": True},
        ],
    },
]


def handle_prompt_call(core: RoundtableCore, db: RoundtableDB, name: str, arguments: dict[str, str]) -> dict[str, str]:
    """Render a prompt template. Returns {description, text}."""
    if name == "coordinator_kickoff":
        return _coordinator_kickoff(arguments)
    elif name == "participant_turn":
        return _participant_turn(db, arguments)
    elif name == "coordinator_summarize":
        return _coordinator_summarize(arguments)
    else:
        return {"description": f"Unknown prompt: {name}", "text": f"Unknown prompt: {name}"}


def _coordinator_kickoff(arguments: dict[str, str]) -> dict[str, str]:
    topic = arguments.get("topic", "")
    participants = arguments.get("participants", "")
    max_rounds = arguments.get("max_rounds", "3")
    decision_brief = arguments.get("decision_brief", "Not supplied; establish it from the user's context.")
    text = f"""You coordinate a professional team helping the user make an important decision.

## Prepare the Review
Clarify the decision owner, goals, constraints, options, evidence gaps, and time/cost budget.
Ask only for missing information that could change the choice. Check which professional
roles are needed; explain missing coverage and avoid adding redundant participants.
Give each role a responsibility, required materials, concrete questions, and deliverables.
Agents supply context and tools; the host chooses models for the actual tasks. Record
known assignments and reasons. Do not invent model identities or fixed model-to-role rankings.

## Discussion Setup
- Topic: {topic}
- Available participants: {participants}
- Max Rounds: {max_rounds}

## User-provided Decision Brief
{decision_brief}

## Workflow
1. Map available agents to roles and create the discussion with roundtable_create.
   Store the brief in context and each role's task in participant perspective. Invite
   additional agents only as needed and arrange their execution through the host.
2. Speak as coordinator in round 0 with the shared brief, role tasks, and review budget.
3. Have each role prepare its initial analysis from the shared materials. When independent
   analysis is needed, give it a fresh context without peer conclusions. The independent
   participant prompt omits peer speeches; it is not an access-control boundary.
4. Record speeches in turn. The engine advances completed rounds automatically; inspect
   status rather than calling roundtable_advance after each completed round.
5. Focus subsequent turns on conflicts that change the choice. Ask for evidence, revised
   options, phased alternatives, and explicit trade-offs between professional constraints.
   When new user facts arrive, read the current context_revision and use roundtable_update_context
   with a complete revised brief, the actual source, reason, and expected_revision. Preserve
   unaffected constraints and distinguish confirmed facts from assumptions. Refresh participant
   prompts before their next turn. Do not leave corrections only in a speech.
6. Stop when the important questions are covered, further discussion adds little, or the
   agreed budget is exhausted. Consensus score is a ratio of supplied annotations, not
   decision quality, and may be null. Preserve unresolved disagreement.
7. Use coordinator_summarize to prepare an evidence-linked decision brief, then record
   the recommendation with roundtable_end. Distinguish it from a user-approved decision.
   Reaching max_rounds ends the meeting automatically; the conclusion can then be updated.

## For Code Review
Establish expected behavior, base/head or a specific diff, code context, checks already run,
and repository constraints. Choose correctness, architecture/maintainability, security, and
testing/reliability roles according to the change. The host supplies repository access and tools.
Require actionable findings with location, trigger, impact, evidence, suggested fix, and
validation status. Deduplicate by root cause; separate blockers, suggestions, and unverified areas.
"""
    return {"description": f"Coordinator kickoff for: {topic}", "text": text}


def _participant_turn(db: RoundtableDB, arguments: dict[str, str]) -> dict[str, str]:
    discussion_id = arguments.get("discussion_id", "")
    role = arguments.get("role", "participant")
    perspective = arguments.get("perspective", "")

    requested_phase = arguments.get("phase")
    if requested_phase is not None and requested_phase not in {"independent", "response"}:
        raise ValueError("phase must be independent or response")

    try:
        conn = db.connect()
        try:
            conn.execute("BEGIN")
            discussion = db.get_discussion(conn, discussion_id)
            if discussion is None:
                return {
                    "description": "Discussion unavailable",
                    "text": "Discussion not found; check the ID before speaking.",
                }
            phase = requested_phase or ("independent" if discussion.current_round <= 1 else "response")
            context_history = db.get_context_history(conn, discussion_id)
            current_context = context_history[-1]
            if phase == "independent":
                speeches = [
                    speech
                    for speech in db.get_speeches(conn, discussion_id, participant="coordinator")
                    if speech.round == 0 and current_context["revision"] == 0
                ]
            else:
                speeches = db.get_speeches(conn, discussion_id)[-10:]
        finally:
            conn.close()
    except Exception:
        return {
            "description": "Discussion unavailable",
            "text": "Unable to load the decision context. Resolve access before preparing or recording an analysis.",
        }

    history_text = (
        "\n\n".join(
            f"[Speech #{s.id}, round {s.round}, {s.participant}]\n"
            + (s.content if phase == "independent" else s.content[:600])
            + (
                " [excerpt; read the full speech before relying on it]"
                if phase == "response" and len(s.content) > 600
                else ""
            )
            for s in speeches
        )
        or "(No speeches available for this phase.)"
    )
    phase_guidance = (
        "Prepare your own assessment from the brief and source materials before reading peer opinions. "
        "Peer speeches are omitted from this prompt; the host must provide a separate context if isolation is needed."
        if phase == "independent"
        else "Respond to constraints from other roles, cite speech IDs, and explain what changed in your view. "
        "This is only the latest 10 speeches; use roundtable_read to inspect earlier or excerpted evidence."
    )

    text = f"""You contribute professional analysis to a decision review.

## Your Role: {role}
## Your Perspective: {perspective or "General"}
## Phase: {phase}

## Decision: {discussion.topic}
## Current shared brief (revision {current_context["revision"]}, source: {current_context["source"]})
{discussion.context or "No decision brief supplied; identify the missing information instead of guessing."}
This current brief supersedes conflicting assumptions in earlier speeches. The source is
reported provenance, not independent verification. Historical views may predate a user correction.

## Discussion Materials
{history_text}

## Instructions
{phase_guidance}
- Address your assigned professional questions with concrete options, benefits, costs, and constraints.
- Separate observed facts and sources from assumptions, predictions, and preferences.
- Explain the implications for other roles and offer alternatives when requirements conflict.
- State missing evidence, remaining uncertainty, and what would change your recommendation.
- Use the host's actual tools and context; do not claim verification or expertise you did not exercise.
- Use enough detail for the decision without padding or repeating other contributions.
- Check roundtable_wait_for_turn before recording. Only the coordinator opens round 0.

## For Code Review
Inspect the actual diff and relevant callers supplied by the host. For each finding provide
file/line or symbol, triggering conditions, impact, evidence or reproduction, priority and
rationale, suggested fix, and validation status. Mark hypotheses as unverified. Do not
invent tests or defects, and distinguish optional refactoring from blocking regressions.

Call: roundtable_speak(discussion_id="{discussion_id}", participant="<your_profile>", content="<your speech>")
"""
    return {"description": f"Participant turn ({role})", "text": text}


def _coordinator_summarize(arguments: dict[str, str]) -> dict[str, str]:
    discussion_id = arguments.get("discussion_id", "")
    text = f"""Synthesize the professional analyses into a decision brief for the user.

1. Call roundtable_summarize(discussion_id="{discussion_id}", compact=true) for an overview.
   It formats recorded material and may truncate speeches; it does not perform semantic synthesis.
2. Use roundtable_read(discussion_id="{discussion_id}") to verify consequential statements
   against the full speeches and source material. Empty findings do not prove agreement;
   the current tool set does not extract findings automatically. Use roundtable_record_finding
   for material consensus, disagreement, or new points, citing actual speech IDs. Do not
   turn a tentative view into consensus or count agreement as evidence of correctness.
3. Explain the decision, objectives, constraints, professional coverage, and any missing roles.
4. Compare feasible options by benefits, costs, risks, dependencies, and conditions of use.
   Include keeping the current approach or deferring when relevant.
5. Recommend a choice with evidence and speech references, explain cross-role trade-offs,
   and retain the strongest dissent, unverified assumptions, and unresolved questions.
   Agreement counts and convergence scores do not establish correctness.
6. Propose validation steps or actions with suggested owners and conditions for revisiting.
   When evidence is insufficient, recommend what to learn next rather than forcing a choice.
7. Distinguish recommendation pending user decision, user-confirmed decision, and deferred
   decision. Do not present a recommendation as approved or authorize its implementation.
8. Call roundtable_end(discussion_id="{discussion_id}", conclusion="<decision brief>")
   to persist the result, including after automatic conclusion at the round limit.
   Read it back with roundtable_read or roundtable_summarize; both return the full conclusion.
   Save a separate full document only when requested or needed in the existing workflow.

For Code Review, deduplicate findings by root cause and separate blockers, non-blocking
suggestions, and unverified areas. Preserve code locations, triggers, impact, evidence,
severity rationale, suggested fixes, and actual check results. Give a reasoned merge,
changes-required, or insufficient-information recommendation. No findings does not prove
safety, and a recommendation does not authorize merging or modifying code.
"""
    return {"description": "Coordinator summarize and conclude", "text": text}
