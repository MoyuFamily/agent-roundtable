"""Behavioral regressions for submitted evidence and deterministic reports."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from itertools import product
from typing import Any

import pytest

from roundtable import evidence as ev

Payload = dict[str, Any]


@pytest.fixture
def evidence() -> Payload:
    source = dict(id="s1", title="容量记录", version="第二版", date="2026年11月")
    item: Payload = dict(id="e1", statement="容量 120 人", kind="fact", verification="verified")
    item["citations"] = [{"source_id": "s1", "locator": "第 3 页"}]
    return {"sources": [source], "items": [item]}


@pytest.fixture
def report() -> Payload:
    reason = {"text": "容量约束", "evidence_ids": ["e1"]}
    value: Payload = dict(recommendation="先试点 7 天", status="proposed", rationale=[reason])
    value.update(tradeoffs=["投入 2 人天"], uncertainties=["需求待核实"], revisit_conditions=["需求超过 120 人"])
    value["next_actions"] = ["安排访谈"]
    return value


def test_schema_matches_runtime_state_requirements(evidence: Payload, report: Payload) -> None:
    # Optional validator is supplied by MCP installations; no new dependency.
    validator = pytest.importorskip("jsonschema").Draft202012Validator
    for schema, value in ((ev.EVIDENCE_SCHEMA, evidence), (ev.REPORT_SCHEMA, report)):
        validator.check_schema(schema)
        validator(schema).validate(value)
    for kind, state, cited, derivation in product(
        ("fact", "calculation", "unknown", "assumption", "user_report"),
        ("verified", "unverified", "conflicting"),
        (False, True),
        (None, "", "输入 3 和 4，公式 3 + 4"),
    ):
        value = deepcopy(evidence)
        item = value["items"][0]
        item.update(kind=kind, verification=state)
        if not cited:
            item["citations"] = []
        if derivation is not None:
            item["derivation"] = derivation
        try:
            ev.normalize_evidence(value)
            accepted = True
        except ValueError:
            accepted = False
        assert validator(ev.EVIDENCE_SCHEMA).is_valid(value) == accepted, (kind, state, cited, derivation)


def test_bad_source_references_and_duplicate_ids(evidence: Payload) -> None:
    for collection in ("sources", "items"):
        value = deepcopy(evidence)
        duplicate = deepcopy(value[collection][0])
        duplicate["title" if collection == "sources" else "statement"] = "不同内容"
        value[collection].append(duplicate)
        with pytest.raises(ValueError, match=rf"^evidence\.{collection}\[1\]\.id:"):
            ev.normalize_evidence(value)
    for citation in (
        {"source_id": "missing", "locator": "第 3 页"},
        {"source_id": True, "locator": "第 3 页"},
        {"source_id": "s1"},
        {"source_id": "s1", "locator": ""},
    ):
        value = deepcopy(evidence)
        value["items"][0]["citations"] = [citation]
        with pytest.raises(ValueError, match=r"^evidence\.items\[0\]\.citations\[0\]\."):
            ev.normalize_evidence(value)
    for identifier in ("bad\n", "x" * 65):
        evidence["items"][0]["id"] = identifier
        with pytest.raises(ValueError, match=r"^evidence\.items\[0\]\.id:"):
            ev.normalize_evidence(evidence)


def test_reports_require_real_typed_references_and_actions(evidence: Payload, report: Payload) -> None:
    for references in (["missing"], [True], "e1", []):
        value = deepcopy(report)
        value["rationale"][0]["evidence_ids"] = references
        with pytest.raises(ValueError, match=r"^report\.rationale\[0\]\.evidence_ids"):
            ev.normalize_report(value, evidence)
    bundles: list[Payload | None] = [None, {"sources": [], "items": []}]
    for bundle in bundles:
        with pytest.raises(ValueError, match=r"^report\.rationale\[0\]\.evidence_ids"):
            ev.render_report(report, bundle, 0)
    changes: list[Payload] = [{"rationale": []}, {"next_actions": []}, {"recommendation": " "}, {"status": "automatic"}]
    for change in changes:
        with pytest.raises(ValueError, match=r"^report\."):
            ev.normalize_report(report | change, evidence)


def test_verification_rules_and_calculations_do_not_infer_facts(evidence: Payload) -> None:
    item = evidence["items"][0]
    for kind in ("unknown", "assumption", "user_report"):
        item["kind"] = kind
        with pytest.raises(ValueError, match=r"^evidence\.items\[0\]\.verification:"):
            ev.normalize_evidence(evidence)
    for kind in ("fact", "calculation"):
        item.update(kind=kind, citations=[])
        with pytest.raises(ValueError, match=r"^evidence\.items\[0\]\.citations:"):
            ev.normalize_evidence(evidence)
    item["citations"] = [{"source_id": "s1", "locator": "第 3 页"}]
    with pytest.raises(ValueError, match=r"^evidence\.items\[0\]\.derivation:"):
        ev.normalize_evidence(evidence)
    item.update(statement="提交结果 99", derivation="输入 3 和 4，公式 3 + 4")
    assert ev.normalize_evidence(evidence) == evidence
    rendered = ev.render_evidence(evidence)
    assert "提交结果 99" in rendered and "输入 3 和 4" in rendered and "第 3 页" in rendered


def test_normalization_copies_and_deduplicates_without_mutation(evidence: Payload, report: Payload) -> None:
    evidence["items"][0]["citations"] *= 2
    evidence["items"][0]["citations"].append({"source_id": "s1", "locator": "附录第 8 页"})
    report["rationale"][0]["evidence_ids"] *= 2
    before = deepcopy((evidence, report))
    bundle, decision = ev.normalize_evidence(evidence), ev.normalize_report(report, evidence)
    assert len(bundle["items"][0]["citations"]) == 2
    assert decision["rationale"][0]["evidence_ids"] == ["e1"]
    bundle["items"][0]["citations"][0]["locator"] = "新定位"
    bundle["sources"][0]["title"] = "新标题"
    decision["rationale"][0]["evidence_ids"].clear()
    assert (evidence, report) == before


def test_unknown_keys_and_invalid_values_never_echo_content(evidence: Payload, report: Payload) -> None:
    marker = "synthetic-marker-8273"
    targets = [evidence, *evidence["sources"], *evidence["items"], *evidence["items"][0]["citations"]]
    for target in [*targets, report, *report["rationale"]]:
        target[marker] = marker
        with pytest.raises(ValueError) as error:
            ev.normalize_report(report, evidence)
        assert str(error.value).startswith(("evidence:", "evidence.", "report:", "report."))
        assert marker not in str(error.value)
        del target[marker]
    report["rationale"][0]["evidence_ids"] = [marker]
    with pytest.raises(ValueError, match=r"^report\.rationale\[0\]\.evidence_ids\[0\]:") as error:
        ev.normalize_report(report, evidence)
    assert marker not in str(error.value)


def test_missing_metadata_and_empty_sections_stay_unknown(evidence: Payload, report: Payload) -> None:
    evidence["sources"][0] = {"id": "s1", "title": "用户自述记录"}
    evidence["items"][0].update(kind="user_report", verification="unverified")
    report.update(tradeoffs=[], uncertainties=[], revisit_conditions=[])
    rendered = ev.render_report(report, evidence, 0)
    assert rendered.count("未知") >= 5 and rendered.count("未记录") == 3
    assert "未核实" in rendered and "已核实" not in rendered
    assert "未提供" in ev.render_evidence(None)
    assert "未记录" in ev.render_evidence({"sources": [], "items": []})


def test_deterministic_output_retains_complete_cited_material(evidence: Payload, report: Payload) -> None:
    text = "完整中文证据 12345，" * 2000 + "末尾仍然保留"
    evidence["items"][0].update(statement=text, applicability="上海试点", derivation="逐项汇总")
    evidence["sources"][0]["date"] += "  "
    assert evidence["sources"][0]["date"] + "\n" in ev.render_evidence(evidence)
    evidence["sources"].append({"id": "unused", "title": "未引用来源"})
    report["recommendation"] = "完整推荐 67890，" * 1500 + "推荐末尾"
    rendered = ev.render_report(report, evidence, 17)
    assert rendered == ev.render_report(json.loads(json.dumps(report, sort_keys=True)), evidence, 17)
    for value in (text, report["recommendation"], "第二版", "2026年11月", "第 3 页", "上海试点", "逐项汇总"):
        assert value in rendered
    assert rendered.index(report["recommendation"]) < rendered.index("安排访谈") < rendered.index(text)
    assert rendered.endswith("\n17\n") and "未引用来源" not in rendered
    assert "未引用来源" in ev.render_evidence(evidence)


def test_literal_multiline_markdown_and_html_cannot_inject_structure(evidence: Payload, report: Payload) -> None:
    payload = (
        "中文 123\n# forged\r\n[link](https://example.invalid)\n<script>x</script>\n\n    # indented\n- fake\n尾行 456"
    )
    baseline = ev.render_report(report, evidence, 1)
    for field in ("title", "reference", "version", "date"):
        evidence["sources"][0][field] = payload
    for field in ("statement", "applicability", "derivation"):
        evidence["items"][0][field] = payload
    evidence["items"][0]["citations"][0]["locator"] = payload
    report["recommendation"] = report["rationale"][0]["text"] = payload
    for field in ("tradeoffs", "uncertainties", "revisit_conditions", "next_actions"):
        report[field] = [payload]
    rendered = ev.render_report(report, evidence, 1)
    structure = re.compile(r"^(?:#+ |[-*] |[0-9]+\. )", re.M)
    assert structure.findall(rendered) == structure.findall(baseline)
    assert "<" not in rendered and "[link](" not in rendered and "https://" not in rendered
    assert "&lt;script&gt;" in rendered and "中文 123" in rendered and "尾行 456" in rendered
    assert "  \n  \\# forged" in rendered and "  \n   \\# forged" in rendered
    assert ev.normalize_report(report, evidence) == report and ev.normalize_evidence(evidence) == evidence


def test_overview_exposes_each_evidence_state_without_promoting_status(evidence: Payload, report: Payload) -> None:
    cases = [
        ("fact", "verified", "事实，已核实"),
        ("assumption", "unverified", "假设，未核实"),
        ("calculation", "conflicting", "计算，存在冲突"),
        ("user_report", "unverified", "用户自述，未核实"),
        ("unknown", "unverified", "未知，未核实"),
    ]
    evidence["items"] = [
        dict(deepcopy(evidence["items"][0]), id=f"e{i}", kind=kind, verification=state, derivation="提交的输入与公式")
        for i, (kind, state, _) in enumerate(cases)
    ]
    report["rationale"][0]["evidence_ids"] = [item["id"] for item in evidence["items"]]
    for status, label in (("proposed", "待确认"), ("confirmed", "已确认"), ("deferred", "已暂缓")):
        report["status"] = status
        rendered = ev.render_report(report, evidence, 0)
        reason = next(line for line in rendered.splitlines() if "容量约束" in line)
        for _, _, state_label in cases:
            assert state_label in reason
        assert ev.normalize_report(report, evidence)["status"] == status and label in rendered
        assert "核实状态由提交方标注" in rendered and "unverified" not in rendered
