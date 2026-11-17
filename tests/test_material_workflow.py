"""Material provenance must survive tool calls without leaking unselected text into output."""

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
from roundtable.exceptions import DiscussionNotActiveError
from roundtable.materials import prepare_material
from roundtable.mcp.prompts import handle_prompt_call
from roundtable.mcp.resources import handle_resource_read
from roundtable.mcp.tools import handle_tool_call


@pytest.fixture
def review(tmp_path):
    db = RoundtableDB(tmp_path / "review.db")
    core = RoundtableCore(db=db)
    did = core.create_discussion(
        "Synthetic capacity review",
        [{"profile": "engineer"}, {"profile": "product"}],
        web=False,
        context="Assess a pilot against the available capacity.",
        output_path=str(tmp_path / "report.md"),
    )["discussion_id"]
    return core, db, did


def packet():
    return {
        "source": {"id": "S1", "title": "Synthetic estimate"},
        "format": "pdf",
        "segments": [
            {
                "id": "p1",
                "locator": "page 1",
                "text": "Pilot takes two weeks. RAW_ONLY_MARKER",
                "status": "needs_review",
                "note": "Check table alignment visually.",
            },
            {
                "id": "p2",
                "locator": "page 2",
                "text": "",
                "status": "unreadable",
                "note": "No text extracted; content may be an image.",
            },
        ],
    }


def evidence(material, *, verified=False):
    segment = material["segments"][0]
    return {
        "sources": [material["source"]],
        "items": [
            {
                "id": "F1",
                "statement": "Pilot estimate is two weeks.",
                "kind": "fact",
                "verification": "verified" if verified else "unverified",
                "citations": [
                    {"source_id": material["source"]["id"], "segment_id": segment["id"], "locator": segment["locator"]}
                ],
            }
        ],
    }


def test_local_material_to_report_retains_locations_and_excludes_raw_text(review, tmp_path):
    core, db, did = review
    path = tmp_path / "raw-source-with-private-name.md"
    content = "Pilot takes two weeks.\n" + "RAW_ONLY_MARKER\n" * 103
    path.write_bytes(content.encode("utf-8"))
    material = prepare_material(path, source_id="S1", title="Synthetic estimate")
    saved = handle_tool_call(
        core,
        db,
        "roundtable_add_material",
        {
            "discussion_id": did,
            "material": material,
            "source": "coordinator",
            "expected_revision": 0,
        },
    )
    assert saved.get("ok"), saved
    assert saved["created"] and saved["context_revision"] == 1
    selected = []
    offset = 0
    while True:
        page = handle_tool_call(
            core,
            db,
            "roundtable_read_material",
            {
                "discussion_id": did,
                "source_id": "S1",
                "offset": offset,
                "limit": 1,
            },
        )
        selected.extend(page["segments"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert selected == material["segments"]
    assert "".join(segment["text"] for segment in selected) == content
    prompt = handle_prompt_call(core, db, "participant_turn", {"discussion_id": did, "role": "Engineer"})
    assert "Synthetic estimate" in prompt["text"] and "roundtable_read_material" in prompt["text"]
    assert "RAW_ONLY_MARKER" not in prompt["text"]
    core.update_context(
        did,
        "Estimate extracted; demand not measured.",
        source="coordinator",
        expected_revision=1,
        evidence=evidence(material, verified=True),
    )
    ended = core.end_discussion(
        did,
        expected_revision=2,
        report={
            "recommendation": "Measure demand before committing to a pilot.",
            "status": "proposed",
            "rationale": [{"text": "The work consumes available capacity.", "evidence_ids": ["F1"]}],
            "tradeoffs": [],
            "uncertainties": ["Demand has not been measured."],
            "revisit_conditions": [],
            "next_actions": ["Run a demand survey."],
        },
    )
    reopened = RoundtableCore(db=RoundtableDB(db.db_path))
    assert reopened.read_material(did, "S1")["segments"] == material["segments"]
    outputs = [reader(did) for reader in (reopened.read, reopened.status, reopened.summarize)]
    outputs.append(handle_resource_read(reopened, reopened.db, f"roundtable://discussions/{did}/transcript"))
    exported = (tmp_path / "report.md").read_text(encoding="utf-8")
    for output in [*outputs, ended, exported]:
        serialized = json.dumps(output, ensure_ascii=False)
        assert "RAW_ONLY_MARKER" not in serialized
        assert path.name not in serialized
    assert selected[0]["locator"].replace("-", "\\-") in ended["conclusion"]
    assert ended["conclusion"] in exported
    assert outputs[0]["context_history"][0]["evidence"] is None
    assert outputs[0]["context_history"][1]["evidence"]["items"] == []


def test_invalid_or_unchecked_material_citations_are_atomic_and_review_notes_visible(review):
    core, _, did = review
    material = packet()
    core.add_material(did, material, source="coordinator", expected_revision=0)
    original = evidence(material, verified=True)
    for field, value in (("segment_id", "missing"), ("locator", "page 9"), ("segment_id", None)):
        invalid = copy.deepcopy(original)
        citation = invalid["items"][0]["citations"][0]
        if value is None:
            del citation[field]
        else:
            citation[field] = value
        before = core.read(did)
        with pytest.raises(ValueError):
            core.update_context(did, "Bad citation", source="coordinator", expected_revision=1, evidence=invalid)
        assert core.read(did) == before
    with pytest.raises(ValueError, match="review_note"):
        core.update_context(did, "Unchecked table", source="coordinator", expected_revision=1, evidence=original)
    original["items"][0]["citations"][0]["review_note"] = "Inspected page 1 visually and checked the estimate row."
    core.update_context(
        did, "Table checked; page 2 remains unreadable.", source="coordinator", expected_revision=1, evidence=original
    )
    result = core.end_discussion(
        did,
        expected_revision=2,
        report={
            "recommendation": "Review the missing page first.",
            "status": "deferred",
            "rationale": [{"text": "Known cost is provisional.", "evidence_ids": ["F1"]}],
            "tradeoffs": [],
            "uncertainties": [],
            "revisit_conditions": [],
            "next_actions": ["Read page 2."],
        },
    )
    assert "Inspected page 1 visually" in result["conclusion"]
    assert "page 2" in result["conclusion"] and "未能读取" in result["conclusion"]
    assert "RAW_ONLY_MARKER" not in result["conclusion"]


def test_import_retries_versions_and_stale_revisions_do_not_repoint_history(review):
    core, _, did = review
    material = packet()
    saved = core.add_material(did, material, source="coordinator", expected_revision=0)
    before = core.read(did)
    retry = core.add_material(did, material, source="coordinator", expected_revision=0)
    assert not retry["created"] and retry["material"] == saved["material"]
    assert core.read(did) == before
    changed = copy.deepcopy(material)
    changed["segments"][0]["text"] = "Changed content"
    with pytest.raises(ValueError, match="immutable"):
        core.add_material(did, changed, source="coordinator", expected_revision=1)
    changed["source"]["id"] = "S2"
    with pytest.raises(ValueError, match="revision conflict"):
        core.add_material(did, changed, source="coordinator", expected_revision=0)
    assert core.read(did) == before
    saved = core.add_material(did, changed, source="coordinator", expected_revision=1)
    assert saved["context_revision"] == 2
    assert core.read_material(did, "S1")["segments"] == material["segments"]
    core.update_context(
        did,
        "Temporary empty register",
        source="coordinator",
        expected_revision=2,
        evidence={"sources": [], "items": []},
    )
    changed["source"]["id"] = "S1"
    with pytest.raises(ValueError, match="immutable"):
        core.add_material(did, changed, source="coordinator", expected_revision=3)
    core.end_discussion(did, conclusion="Deferred")
    with pytest.raises(DiscussionNotActiveError):
        core.add_material(did, material, source="coordinator", expected_revision=3)


def test_concurrent_imports_have_one_atomic_winner_and_upgrade_preserves_brief(review):
    core, db, did = review
    core.update_context(did, "Existing brief", source="user", expected_revision=0)
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DROP TABLE materials")
        conn.execute("PRAGMA user_version=6")
    barrier = Barrier(2)

    def contender(source_id):
        material = packet()
        material["source"]["id"] = source_id
        other = RoundtableCore(db=RoundtableDB(db.db_path))
        barrier.wait(timeout=5)
        try:
            other.add_material(did, material, source="coordinator", expected_revision=1)
            return source_id
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(contender, ["S1", "S2"]))
    winners = [source_id for source_id in outcomes if source_id is not None]
    assert len(winners) == 1
    result = core.read(did)
    assert result["context"] == "Existing brief" and result["context_revision"] == 2
    assert [m["source"]["id"] for m in result["materials"]] == winners
    assert [s["id"] for s in result["evidence"]["sources"]] == winners
    assert result["speech_count"] == 0


@pytest.mark.parametrize("adapter", ["generic", "hermes"])
def test_adapter_import_and_read_share_the_same_material(review, monkeypatch, adapter):
    core, db, did = review
    material = packet()
    if adapter == "generic":
        facade = Roundtable(db_path=str(db.db_path))
        add, read = facade.add_material, facade.read_material
    else:
        monkeypatch.setattr(hermes, "_core", core)
        handlers = {}

        class Registry:
            def register(self, **kwargs):
                handlers[kwargs["name"]] = kwargs["handler"]

        hermes.register_roundtable_tools(Registry())

        def add(did, material, **kwargs):
            return json.loads(
                handlers["roundtable_add_material"]({"discussion_id": did, "material": material, **kwargs})
            )

        def read(did, source_id, **kwargs):
            return json.loads(
                handlers["roundtable_read_material"]({"discussion_id": did, "source_id": source_id, **kwargs})
            )

    result = add(did, material, source="coordinator", expected_revision=0)
    assert result["created"]
    selection = read(did, "S1", query="PILOT")
    assert selection["segments"] == [material["segments"][0]]
