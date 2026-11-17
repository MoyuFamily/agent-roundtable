"""A coordinator's extracted evidence must survive revision, reporting, and restart."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from roundtable.adapters import hermes
from roundtable.adapters.generic import Roundtable
from roundtable.core import RoundtableCore
from roundtable.db import RoundtableDB
from roundtable.evidence import render_report
from roundtable.exceptions import DiscussionNotActiveError
from roundtable.mcp.prompts import handle_prompt_call
from roundtable.mcp.resources import handle_resource_read
from roundtable.mcp.tools import handle_tool_call


@pytest.fixture
def evidence():
    return {
        "sources": [{"id": "S1", "title": "Synthetic team plan", "version": "1"}],
        "items": [
            {
                "id": "F1",
                "statement": "A pilot requires two engineering weeks.",
                "kind": "fact",
                "verification": "verified",
                "citations": [{"source_id": "S1", "locator": "section 2"}],
            },
            {
                "id": "U1",
                "statement": "Customer demand is not measured.",
                "kind": "unknown",
                "verification": "unverified",
                "citations": [],
            },
        ],
    }


@pytest.fixture
def report():
    return {
        "recommendation": "Run a bounded team pilot.",
        "status": "proposed",
        "rationale": [{"text": "Scope fits current capacity.", "evidence_ids": ["F1", "U1"]}],
        "tradeoffs": ["Two engineering weeks are unavailable for other work."],
        "uncertainties": ["Customer demand remains unknown."],
        "revisit_conditions": ["The estimate exceeds available capacity."],
        "next_actions": ["Measure demand before committing implementation work."],
    }


@pytest.fixture
def review(tmp_path):
    db = RoundtableDB(tmp_path / "review.db")
    core = RoundtableCore(db=db)
    did = core.create_discussion(
        "Team pilot",
        [{"profile": "a"}, {"profile": "b"}],
        context="Decide whether to pilot a team edition.",
        web=False,
        output_path=str(tmp_path / "report.md"),
        max_rounds=1,
    )["discussion_id"]
    return core, db, did


def update(review, evidence, revision=0):
    core, db, did = review
    result = handle_tool_call(
        core,
        db,
        "roundtable_update_context",
        {
            "discussion_id": did,
            "context": "Decide whether to pilot; demand remains unknown.",
            "source": "coordinator",
            "expected_revision": revision,
            "evidence": evidence,
        },
    )
    assert "error" not in result, result
    return result


def test_evidence_reaches_roles_and_one_conclusion_reaches_every_reader(review, evidence, report, tmp_path):
    core, db, did = review
    saved = update(review, evidence)
    core.speak(did, "coordinator", "Opening")
    core.speak(did, "a", "PEER_PRIVATE_FIRST_PASS")
    prompt = handle_prompt_call(core, db, "participant_turn", {"discussion_id": did, "role": "Engineering"})
    assert "two engineering weeks" in prompt["text"]
    assert "Customer demand" in prompt["text"]
    assert "PEER_PRIVATE_FIRST_PASS" not in prompt["text"]
    core.speak(did, "b", "Independent assessment")
    assert core.status(did)["status"] == "concluded"
    result = handle_tool_call(
        core,
        db,
        "roundtable_end",
        {
            "discussion_id": did,
            "report": report,
            "expected_revision": 1,
        },
    )
    assert "error" not in result, result
    canonical = result["conclusion"]
    assert canonical == render_report(report, saved["evidence"], 1)
    reopened_db = RoundtableDB(db.db_path)
    reopened = RoundtableCore(db=reopened_db)
    for reader in (reopened.read, reopened.status, reopened.summarize):
        data = reader(did)
        assert data["conclusion"] == canonical
        assert data["evidence"] == saved["evidence"]
        assert data["decision_report"] == {"context_revision": 1, "report": report}
    transcript = handle_resource_read(reopened, reopened_db, f"roundtable://discussions/{did}/transcript")
    assert transcript["conclusion"] == canonical
    assert canonical in transcript["transcript"]
    assert canonical in (tmp_path / "report.md").read_text(encoding="utf-8")
    summary = reopened.summarize(did)["structured_summary"]
    assert summary.index(canonical) < summary.index("PEER_PRIVATE_FIRST_PASS")


def test_bad_evidence_and_repointed_source_do_not_modify_brief(review, evidence):
    core, _, did = review
    saved = update(review, evidence)
    bad = copy.deepcopy(evidence)
    bad["items"][0]["citations"][0]["source_id"] = "missing"
    changed_source = copy.deepcopy(evidence)
    changed_source["sources"][0]["version"] = "2"
    for invalid in (bad, changed_source):
        before = core.read(did)
        with pytest.raises(ValueError):
            core.update_context(did, "Invalid replacement", source="coordinator", expected_revision=1, evidence=invalid)
        assert core.read(did) == before
    # Narrative-only corrections carry evidence forward; empty evidence is an explicit replacement.
    core.update_context(did, "Different priority", source="user", expected_revision=1)
    assert core.read(did)["evidence"] == saved["evidence"]
    update(review, {"sources": [], "items": []}, revision=2)
    with pytest.raises(ValueError, match="Source ID"):
        core.update_context(
            did, "Reintroduced source", source="coordinator", expected_revision=3, evidence=changed_source
        )
    assert core.read(did)["context_history"][1]["evidence"] == saved["evidence"]


def test_stale_or_dangling_report_cannot_conclude_or_replace_output(review, evidence, report, tmp_path):
    core, _, did = review
    update(review, evidence)
    invalid = copy.deepcopy(report)
    invalid["rationale"][0]["evidence_ids"] = ["missing"]
    before = core.read(did)
    for kwargs in (
        {"report": report},
        {"report": report, "expected_revision": 0},
        {"report": invalid, "expected_revision": 1},
        {"report": report, "conclusion": "Different conclusion", "expected_revision": 1},
        {"report": report, "force": True, "expected_revision": 1},
    ):
        with pytest.raises(ValueError):
            core.end_discussion(did, **kwargs)
        assert core.read(did) == before
        assert not (tmp_path / "report.md").exists()
    core.end_discussion(did, report=report, expected_revision=1)
    canonical = core.read(did)["conclusion"]
    with pytest.raises(ValueError):
        core.end_discussion(did, report=invalid, expected_revision=1)
    assert core.read(did)["conclusion"] == canonical
    core.end_discussion(did, conclusion="Replaced with an explicit free-text report.")
    assert core.read(did)["decision_report"] is None


def test_competing_context_update_and_report_never_mix_revisions(review, evidence, report):
    core, db, did = review
    update(review, evidence)
    barrier = Barrier(2)

    def race(finish):
        contender = RoundtableCore(db=RoundtableDB(db.db_path))
        barrier.wait(timeout=5)
        try:
            if finish:
                contender.end_discussion(did, report=report, expected_revision=1)
            else:
                contender.update_context(did, "Corrected constraint", source="user", expected_revision=1)
            return True
        except (ValueError, DiscussionNotActiveError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(race, [True, False]))
    assert sum(outcomes) == 1
    result = core.read(did)
    if outcomes[0]:
        assert result["status"] == "concluded"
        assert result["context_revision"] == result["decision_report"]["context_revision"] == 1
    else:
        assert result["status"] == "active" and result["context_revision"] == 2
        assert result["decision_report"] is None and result["conclusion"] is None


def test_late_export_does_not_replace_a_newer_report(review, evidence, report, tmp_path, monkeypatch):
    core, db, did = review
    update(review, evidence)
    web_dir = tmp_path / "viewer"
    web_dir.mkdir()
    (web_dir / "discussion.json").write_text(json.dumps({"status": "active", "events": []}), encoding="utf-8")
    monkeypatch.setattr(RoundtableCore, "_get_web_dir", lambda *args: web_dir)
    newer = {**report, "recommendation": "Revised recommendation after the final check"}
    other = RoundtableCore(db=RoundtableDB(db.db_path))

    def publish_newer_report(*args):
        # Interleave a second coordinator after the first DB commit, before its export.
        other.end_discussion(did, report=newer, expected_revision=1)

    monkeypatch.setattr(core, "_notify_concluded", publish_newer_report)
    core.end_discussion(did, report=report, expected_revision=1)
    current = core.read(did)["conclusion"]
    assert newer["recommendation"] in current
    assert current in (tmp_path / "report.md").read_text(encoding="utf-8")
    viewer = json.loads((web_dir / "discussion.json").read_text(encoding="utf-8"))
    assert viewer["conclusion"] == viewer["final_summary"]["verdict"] == current
    assert [event for event in viewer["events"] if event["type"] == "status_delta"][-1]["conclusion"] == current


def test_v5_upgrade_retains_existing_context_history_and_plain_conclusion(review):
    core, db, did = review
    core.update_context(did, "Existing shared brief", source="user", expected_revision=0)
    core.end_discussion(did, conclusion="Existing conclusion")
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DROP TABLE decision_reports")
        conn.execute("ALTER TABLE context_revisions DROP COLUMN evidence")
        conn.execute("PRAGMA user_version=5")
    result = RoundtableCore(db=RoundtableDB(db.db_path)).read(did)
    assert result["conclusion"] == "Existing conclusion"
    assert result["context"] == "Existing shared brief"
    assert result["context_revision"] == 1
    assert result["evidence"] is None
    assert result["decision_report"] is None


@pytest.mark.parametrize("adapter", ["generic", "hermes", "core"])
def test_public_adapters_can_save_evidence_and_submit_report(review, evidence, report, monkeypatch, adapter):
    core, db, did = review
    if adapter == "core":
        submit_evidence, submit_report = core.update_context, core.end
    elif adapter == "generic":
        facade = Roundtable(db_path=str(db.db_path))
        submit_evidence, submit_report = facade.update_context, facade.end
    else:
        monkeypatch.setattr(hermes, "_core", core)
        registered = {}

        class Registry:
            def register(self, **kwargs):
                registered[kwargs["name"]] = kwargs["handler"]

        hermes.register_roundtable_tools(Registry())

        def submit_evidence(discussion_id, context, **kwargs):
            return json.loads(
                registered["roundtable_update_context"](
                    {
                        "discussion_id": discussion_id,
                        "context": context,
                        **kwargs,
                    }
                )
            )

        def submit_report(discussion_id, **kwargs):
            return json.loads(registered["roundtable_end"]({"discussion_id": discussion_id, **kwargs}))

    updated = submit_evidence(did, "Shared evidence", source="coordinator", expected_revision=0, evidence=evidence)
    assert updated["context_revision"] == 1
    result = submit_report(did, report=report, expected_revision=1)
    assert "error" not in result, result
    assert core.read(did)["decision_report"]["report"] == report
