"""Decision prompts must preserve shared context without leaking peer first passes."""

import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.prompts import handle_prompt_call
from roundtable.template import apply_template


@pytest.fixture
def review(tmp_path):
    db = RoundtableDB(tmp_path / "review.db")
    core = RoundtableCore(db=db)
    created = core.create_discussion(
        topic="Enterprise edition choice",
        context="Two-person team; customer evidence not yet available.",
        participants=[
            {"profile": "a_product", "role": "Product"},
            {"profile": "b_engineering", "role": "Engineering"},
        ],
        max_rounds=3,
        web=False,
    )
    did = created["discussion_id"]
    core.speak(did, "coordinator", "Shared opening: compare full edition, pilot, and defer.")
    peer = core.speak(did, "a_product", "PEER_FIRST_PASS: choose a team pilot.")
    return core, db, did, peer["speech_id"]


def test_first_pass_preserves_brief_and_omits_peer_opinion(review):
    core, db, did, _ = review
    before = core.read(did)
    text = handle_prompt_call(
        core, db, "participant_turn", {"discussion_id": did, "role": "Engineering", "perspective": "Migration cost"}
    )["text"]

    assert "Enterprise edition choice" in text
    assert "Two-person team; customer evidence not yet available." in text
    assert "Shared opening: compare full edition, pilot, and defer." in text
    assert "Migration cost" in text
    assert "PEER_FIRST_PASS" not in text
    assert core.read(did) == before


def test_response_can_be_requested_in_first_round(review):
    core, db, did, peer_id = review
    text = handle_prompt_call(
        core, db, "participant_turn", {"discussion_id": did, "role": "Engineering", "phase": "response"}
    )["text"]
    assert "PEER_FIRST_PASS" in text
    assert f"Speech #{peer_id}" in text


def test_later_round_defaults_to_response_but_can_remain_independent(review):
    core, db, did, peer_id = review
    core.speak(did, "b_engineering", "Engineering comparison")
    core.speak(did, "coordinator", "LATER_SYNTHESIS: pilot looks feasible")
    args = {"discussion_id": did, "role": "Product"}
    response = handle_prompt_call(core, db, "participant_turn", args)["text"]
    assert "PEER_FIRST_PASS" in response
    assert f"Speech #{peer_id}" in response
    assert "LATER_SYNTHESIS" in response

    independent = handle_prompt_call(core, db, "participant_turn", {**args, "phase": "independent"})["text"]
    assert "Shared opening" in independent
    assert "PEER_FIRST_PASS" not in independent
    assert "LATER_SYNTHESIS" not in independent


def test_response_marks_truncated_evidence_and_preserves_reference(review):
    core, db, did, _ = review
    speech = core.speak(did, "b_engineering", "A" * 650 + "EVIDENCE_AT_END")
    text = handle_prompt_call(core, db, "participant_turn", {"discussion_id": did, "role": "Product"})["text"]
    assert f"Speech #{speech['speech_id']}" in text
    assert "[excerpt; read the full speech before relying on it]" in text
    assert "EVIDENCE_AT_END" not in text
    assert "EVIDENCE_AT_END" in core.read(did)["speeches"][-1]["content"]


def test_invalid_phase_does_not_change_meeting(review):
    core, db, did, _ = review
    before = core.read(did)
    with pytest.raises(ValueError, match="phase"):
        handle_prompt_call(core, db, "participant_turn", {"discussion_id": did, "phase": "unknown"})
    assert core.read(did) == before


def test_missing_discussion_does_not_offer_fabricated_context(review):
    core, db, _, _ = review
    result = handle_prompt_call(core, db, "participant_turn", {"discussion_id": "missing", "role": "Engineering"})
    assert result["description"] == "Discussion unavailable"
    assert "roundtable_speak(" not in result["text"]


@pytest.mark.parametrize("template_id", ["decision-support", "code-review"])
def test_review_templates_support_recording_and_post_round_conclusion(tmp_path, template_id):
    db = RoundtableDB(tmp_path / "template.db")
    core = RoundtableCore(db=db)
    params = apply_template(template_id, subject="A concrete review", overrides={"max_rounds": 1})
    assert params is not None
    assert "A concrete review" in params["topic"]
    assert "A concrete review" in params["context"]
    created = core.create_discussion(**params, web=False)
    did = created["discussion_id"]
    core.speak(did, "coordinator", params["context"])
    tasks = {p["profile"]: p["perspective"] for p in params["participants"]}
    for _ in tasks:
        next_speaker = core.status(did)["next_speaker"]
        core.speak(did, next_speaker, f"Recorded host analysis: {tasks[next_speaker]}")
    assert core.status(did)["status"] == "concluded"
    recommendation = "Recommendation pending user decision; unresolved assumptions retained."
    core.end_discussion(did, conclusion=recommendation)
    conn = db.connect()
    try:
        assert db.get_discussion(conn, did).conclusion == recommendation
        stored = db.get_participants(conn, did)
        assert {p.participant: p.perspective for p in stored} == {
            p["profile"]: p["perspective"] for p in params["participants"]
        }
    finally:
        conn.close()
