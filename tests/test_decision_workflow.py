"""Regression cases from a review with a mid-meeting user clarification."""

import sqlite3

import pytest

from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.mcp.resources import handle_resource_read
from roundtable.mcp.tools import handle_tool_call


@pytest.fixture
def review(tmp_path):
    db = RoundtableDB(tmp_path / "review.db")
    core = RoundtableCore(db=db)
    did = core.create_discussion(
        "Choose a preparation plan",
        [{"profile": "a", "role": "Engineering"}, {"profile": "b", "role": "Hiring"}],
        context="Location UNKNOWN; available time UNKNOWN.",
        max_rounds=2,
        output_path=str(tmp_path / "report.md"),
        web=False,
    )["discussion_id"]
    return core, db, did


def call(review, tool_name, **kwargs):
    core, db, did = review
    result = handle_tool_call(core, db, tool_name, {"discussion_id": did, **kwargs})
    assert "error" not in result, result
    return result


def test_end_to_end_revision_findings_conclusion_and_restart(review, tmp_path):
    core, db, did = review
    assert call(review, "roundtable_status")["total_rounds"] == 0
    call(review, "roundtable_speak", participant="coordinator", content="Original opening; location UNKNOWN.")
    a1 = call(review, "roundtable_speak", participant="a", content="Technical evidence is needed.")["speech_id"]
    updated = call(
        review,
        "roundtable_update_context",
        context="Location CONFIRMED; available time UNKNOWN.",
        source="user",
        expected_revision=0,
        reason="User clarified the location.",
    )
    assert updated["context_revision"] == 1
    # A late first-pass participant gets the updated facts, without old opening or peer opinion.
    prompt = call(
        review,
        "roundtable_get_prompt",
        name="participant_turn",
        arguments={
            "discussion_id": did,
            "role": "Hiring",
            "phase": "independent",
        },
    )["text"]
    assert "Location CONFIRMED" in prompt
    assert "available time UNKNOWN" in prompt
    assert "location UNKNOWN" not in prompt
    assert "Technical evidence is needed." not in prompt
    b1 = call(review, "roundtable_speak", participant="b", content="Get early market feedback.")["speech_id"]
    finding = call(
        review,
        "roundtable_record_finding",
        finding_type="disagreement",
        content="How much evidence is needed before applications?",
        related_speeches=[a1, b1],
    )
    assert finding["basis"] == "recorded_annotation"
    assert finding["created"] is True
    assert call(review, "roundtable_status")["completed_rounds"] == 1
    call(review, "roundtable_speak", participant="coordinator", content="Respond to this trade-off.")
    call(review, "roundtable_speak", participant="a", content="Verify one claim.")
    call(review, "roundtable_speak", participant="b", content="Apply with honest boundaries.")
    # The engine cursor is 3, but there were only two substantive review rounds.
    status = call(review, "roundtable_status")
    assert status["current_round"] == 3
    assert status["total_rounds"] == status["completed_rounds"] == 2
    assert status["status"] == "concluded"
    assert status["conclusion"] is None
    conclusion = "Recommendation pending user decision.\n" + "Evidence and limits. " * 100 + "END_OF_CONCLUSION"
    assert call(review, "roundtable_end", conclusion=conclusion)["conclusion"] == conclusion
    # A new core/connection uses only the public tools to verify persistence.
    restarted = (RoundtableCore(db=RoundtableDB(db.db_path)), RoundtableDB(db.db_path), did)
    for tool in ["roundtable_read", "roundtable_status", "roundtable_summarize"]:
        result = call(restarted, tool)
        assert result["conclusion"] == conclusion
        assert result["total_rounds"] == result["completed_rounds"] == 2
        assert result["context_revision"] == 1
        assert result["context"] == updated["context"]
    summary = call(restarted, "roundtable_summarize")
    assert conclusion in summary["structured_summary"]
    assert summary["structured_summary"].count("## 最终结论") == 1
    assert f"#{a1}" in summary["structured_summary"]
    assert summary["findings"][0]["related_speeches"] == [a1, b1]
    assert summary["final_convergence_score"] == 0.0
    assert summary["context_history"][0]["context"] == "Location UNKNOWN; available time UNKNOWN."
    assert conclusion in (tmp_path / "report.md").read_text(encoding="utf-8")
    exported = handle_resource_read(core, db, f"roundtable://discussions/{did}/transcript")
    assert exported["conclusion"] == conclusion
    assert conclusion in exported["transcript"]
    assert call(restarted, "roundtable_read", participant="nobody")["total_rounds"] == 2


def test_context_conflict_is_atomic_and_does_not_consume_turn(review):
    core, db, did = review
    call(review, "roundtable_speak", participant="coordinator", content="Opening")
    before = call(review, "roundtable_status")
    call(review, "roundtable_update_context", context="Confirmed facts", source="user", expected_revision=0)
    after = call(review, "roundtable_status")
    assert after["speech_count"] == before["speech_count"]
    assert after["current_round"] == before["current_round"]
    assert after["next_speaker"] == before["next_speaker"]
    failed = handle_tool_call(
        core,
        db,
        "roundtable_update_context",
        {
            "discussion_id": did,
            "context": "Stale overwrite",
            "source": "coordinator",
            "expected_revision": 0,
        },
    )
    assert "conflict" in failed["error"]
    read = call(review, "roundtable_read")
    assert read["context"] == "Confirmed facts"
    assert len(read["context_history"]) == 2
    call(review, "roundtable_update_context", context="Another correction", source="user", expected_revision=1)
    assert len(call(review, "roundtable_read")["context_history"]) == 3
    call(review, "roundtable_end", conclusion="Final recommendation")
    failed = handle_tool_call(
        core,
        db,
        "roundtable_update_context",
        {
            "discussion_id": did,
            "context": "New facts",
            "source": "user",
            "expected_revision": 2,
        },
    )
    assert "follow-up" in failed["error"]
    assert call(review, "roundtable_read")["context_revision"] == 2


def test_context_migration_preserves_legacy_discussion(review):
    core, db, did = review
    core.end(did, conclusion="Legacy conclusion")
    # Simulate a v4 database. New schema must not alter existing evidence.
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DROP TABLE context_revisions")
        conn.execute("PRAGMA user_version=4")
    read = call(review, "roundtable_read")
    assert read["conclusion"] == "Legacy conclusion"
    assert read["context_revision"] == 0
    assert read["context_history"][0]["context"] == read["context"]


def test_no_phantom_rounds_when_skipping_or_ending_early(review):
    call(review, "roundtable_advance")
    call(review, "roundtable_advance")
    assert call(review, "roundtable_summarize")["total_rounds"] == 0
    call(review, "roundtable_speak", participant="a", content="Partial review")
    call(review, "roundtable_end", conclusion="Insufficient evidence")
    summary = call(review, "roundtable_summarize")
    assert summary["total_rounds"] == 1
    assert summary["completed_rounds"] == 0


def test_finding_retries_do_not_inflate_counts_and_cross_review_refs_are_rejected(review):
    core, db, did = review
    opening = core.speak(did, "coordinator", "Opening")["speech_id"]
    a = core.speak(did, "a", "A view")["speech_id"]
    args = {"finding_type": "new_point", "content": "New evidence needed", "related_speeches": [opening, a]}
    first = call(review, "roundtable_record_finding", **args)
    second = call(review, "roundtable_record_finding", **{**args, "related_speeches": [a, opening, a]})
    assert first["finding_id"] == second["finding_id"]
    assert second["created"] is False
    other = core.create_discussion("Other", [{"profile": "a"}, {"profile": "b"}], web=False)["discussion_id"]
    foreign_id = core.speak(other, "coordinator", "Other opening")["speech_id"]
    invalid = [[], [foreign_id], [999999], [True], [str(a)]]
    for refs in invalid:
        result = handle_tool_call(
            core,
            db,
            "roundtable_record_finding",
            {
                "discussion_id": did,
                **args,
                "related_speeches": refs,
            },
        )
        assert "error" in result
    assert len(call(review, "roundtable_summarize")["findings"]) == 1


def test_summary_labels_excerpts_and_retains_full_evidence(review):
    call(review, "roundtable_speak", participant="coordinator", content="Shared brief")
    speech = "X" * 400 + "IMPORTANT_END"
    sid = call(review, "roundtable_speak", participant="a", content=speech)["speech_id"]
    summary = call(review, "roundtable_summarize")["structured_summary"]
    assert f"[#{sid}]" in summary and "摘录" in summary
    assert "IMPORTANT_END" not in summary
    assert "空列表不表示没有分歧" in summary
    assert call(review, "roundtable_read")["speeches"][-1]["content"] == speech


def test_context_and_revision_are_a_consistent_snapshot(review, monkeypatch):
    core, db, did = review
    other = db.connect()
    original = db.get_context_history
    updated = False

    def update_between_reads(conn, discussion_id):
        nonlocal updated
        if not updated and conn is not other:
            updated = True
            db.update_context(other, did, "New concurrent facts", source="user", expected_revision=0)
        return original(conn, discussion_id)

    monkeypatch.setattr(db, "get_context_history", update_between_reads)
    try:
        read = core.read(did)
        # A read must not combine the old context with the new revision token.
        assert read["context"] == "Location UNKNOWN; available time UNKNOWN."
        assert read["context_revision"] == 0
        latest = core.read(did)
        assert latest["context"] == "New concurrent facts"
        assert latest["context_revision"] == 1
    finally:
        other.close()


def test_post_limit_conclusion_update_emits_resource_event(review):
    _, db, did = review
    events = []
    core = RoundtableCore(db=db, on_event=lambda name, payload: events.append((name, payload)))
    core.speak(did, "coordinator", "Opening")
    for _ in range(2):
        core.speak(did, "a", "First contribution")
        core.speak(did, "b", "Second contribution")
    events.clear()
    core.end(did, conclusion="New recommendation")
    assert events == [("conclusion_updated", {"discussion_id": did})]
