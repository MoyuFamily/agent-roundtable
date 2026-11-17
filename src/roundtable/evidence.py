"""Validate submitted evidence and render deterministic, literal Markdown.

No facts, verification states, decisions, or calculations are inferred here.
References are inert text: this module performs no I/O. Normalization copies
containers, preserves text and order, and removes only duplicate references.
"""

from __future__ import annotations

import re
import string
from typing import Any

__all__ = [
    "EVIDENCE_SCHEMA",
    "REPORT_SCHEMA",
    "normalize_evidence",
    "normalize_report",
    "render_evidence",
    "render_report",
]

_KIND_LABELS = {
    "fact": "事实",
    "user_report": "用户自述",
    "assumption": "假设",
    "calculation": "计算",
    "unknown": "未知",
}
_VERIFICATION_LABELS = {
    "verified": "已核实",
    "unverified": "未核实",
    "conflicting": "存在冲突",
}
_STATUS_LABELS = {
    "proposed": "待确认",
    "confirmed": "已确认",
    "deferred": "已暂缓",
}
_MARKDOWN_ESCAPES = str.maketrans(
    {char: f"\\{char}" for char in string.punctuation} | {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
)
_CONTROL_PATTERN = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"
_TEXT_SCHEMA: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "pattern": r"\S",
    "not": {"pattern": _CONTROL_PATTERN},
}
_ID_SCHEMA: dict[str, Any] = {
    "type": "string",
    "minLength": 1,
    "maxLength": 64,
    # Unlike $, this end assertion also rejects a trailing newline.
    "pattern": r"^[a-zA-Z0-9_-]{1,64}(?![\s\S])",
}

EVIDENCE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["sources", "items"],
    "description": "Submitted evidence; source/item ID uniqueness and reference integrity are validated at runtime.",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "title"],
                "properties": {
                    "id": _ID_SCHEMA,
                    "title": _TEXT_SCHEMA,
                    "reference": {**_TEXT_SCHEMA, "description": "Literal source text or URL; never accessed."},
                    "version": _TEXT_SCHEMA,
                    "date": _TEXT_SCHEMA,
                },
            },
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "statement", "kind", "verification", "citations"],
                "properties": {
                    "id": _ID_SCHEMA,
                    "statement": _TEXT_SCHEMA,
                    "kind": {"type": "string", "enum": list(_KIND_LABELS)},
                    "verification": {"type": "string", "enum": list(_VERIFICATION_LABELS)},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["source_id", "locator"],
                            "properties": {"source_id": _ID_SCHEMA, "locator": _TEXT_SCHEMA},
                        },
                    },
                    "applicability": _TEXT_SCHEMA,
                    "derivation": _TEXT_SCHEMA,
                },
                "allOf": [
                    {
                        "if": {"properties": {"verification": {"const": "verified"}}},
                        "then": {
                            "properties": {
                                "kind": {"enum": ["fact", "calculation"]},
                                "citations": {"minItems": 1},
                            },
                        },
                    },
                    {
                        "if": {"properties": {"kind": {"const": "calculation"}}},
                        "then": {"required": ["derivation"]},
                    },
                ],
            },
        },
    },
}

REPORT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "recommendation",
        "status",
        "rationale",
        "tradeoffs",
        "uncertainties",
        "revisit_conditions",
        "next_actions",
    ],
    "description": "Submitted decision report; evidence item references are validated at runtime.",
    "properties": {
        "recommendation": _TEXT_SCHEMA,
        "status": {"type": "string", "enum": list(_STATUS_LABELS)},
        "rationale": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence_ids"],
                "properties": {
                    "text": _TEXT_SCHEMA,
                    "evidence_ids": {"type": "array", "minItems": 1, "items": _ID_SCHEMA},
                },
            },
        },
        "tradeoffs": {"type": "array", "items": _TEXT_SCHEMA},
        "uncertainties": {"type": "array", "items": _TEXT_SCHEMA},
        "revisit_conditions": {"type": "array", "items": _TEXT_SCHEMA},
        "next_actions": {"type": "array", "minItems": 1, "items": _TEXT_SCHEMA},
    },
}


def _object(value: object, path: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    if any(key not in required + optional for key in value):
        # Unknown keys are user content too; report only the known parent path.
        raise ValueError(f"{path}: unknown fields are not allowed")
    for key in required:
        if key not in value:
            raise ValueError(f"{path}.{key}: required field")
    return value


def _array(value: object, path: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected an array")
    if nonempty and not value:
        raise ValueError(f"{path}: expected at least one entry")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: expected text")
    if not value.strip():
        raise ValueError(f"{path}: expected nonempty text")
    if re.search(_CONTROL_PATTERN, value):
        raise ValueError(f"{path}: unsupported control character")
    return value


def _identifier(value: object, path: str) -> str:
    identifier = _text(value, path)
    if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identifier) is None:
        raise ValueError(f"{path}: expected 1-64 ASCII letters, digits, underscores or hyphens")
    return identifier


def _choice(value: object, path: str, choices: dict[str, str]) -> str:
    result = _text(value, path)
    if result not in choices:
        raise ValueError(f"{path}: unsupported value")
    return result


def normalize_evidence(value: dict[str, Any]) -> dict[str, Any]:
    """Copy and validate evidence, without resolving references or verifying claims.

    IDs are unique within their respective source/item collections. Missing
    optional metadata stays absent; renderers display it as unknown. Errors
    contain contract field paths, never submitted values or unknown keys.
    """
    data = _object(value, "evidence", ("sources", "items"))
    sources: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for index, entry in enumerate(_array(data["sources"], "evidence.sources")):
        path = f"evidence.sources[{index}]"
        source = _object(entry, path, ("id", "title"), ("reference", "version", "date"))
        identifier = _identifier(source["id"], f"{path}.id")
        if identifier in source_ids:
            raise ValueError(f"{path}.id: duplicate source ID")
        source_ids.add(identifier)
        normalized_source = {"id": identifier, "title": _text(source["title"], f"{path}.title")}
        for field in ("reference", "version", "date"):
            if field in source:
                normalized_source[field] = _text(source[field], f"{path}.{field}")
        sources.append(normalized_source)

    items: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    for index, entry in enumerate(_array(data["items"], "evidence.items")):
        path = f"evidence.items[{index}]"
        item = _object(
            entry, path, ("id", "statement", "kind", "verification", "citations"), ("applicability", "derivation")
        )
        identifier = _identifier(item["id"], f"{path}.id")
        if identifier in item_ids:
            raise ValueError(f"{path}.id: duplicate evidence ID")
        item_ids.add(identifier)
        normalized_item: dict[str, Any] = {
            "id": identifier,
            "statement": _text(item["statement"], f"{path}.statement"),
            "kind": _choice(item["kind"], f"{path}.kind", _KIND_LABELS),
            "verification": _choice(item["verification"], f"{path}.verification", _VERIFICATION_LABELS),
        }
        citations: list[dict[str, str]] = []
        seen_citations: set[tuple[str, str]] = set()
        for citation_index, entry in enumerate(_array(item["citations"], f"{path}.citations")):
            citation_path = f"{path}.citations[{citation_index}]"
            citation = _object(entry, citation_path, ("source_id", "locator"))
            source_id = _identifier(citation["source_id"], f"{citation_path}.source_id")
            if source_id not in source_ids:
                raise ValueError(f"{citation_path}.source_id: unknown source reference")
            locator = _text(citation["locator"], f"{citation_path}.locator")
            if (source_id, locator) not in seen_citations:
                citations.append({"source_id": source_id, "locator": locator})
                seen_citations.add((source_id, locator))
        normalized_item["citations"] = citations
        for field in ("applicability", "derivation"):
            if field in item:
                normalized_item[field] = _text(item[field], f"{path}.{field}")
        if normalized_item["verification"] == "verified":
            if normalized_item["kind"] not in ("fact", "calculation"):
                raise ValueError(f"{path}.verification: verified is only allowed for facts or calculations")
            if not citations:
                raise ValueError(f"{path}.citations: verified evidence requires a citation")
        if normalized_item["kind"] == "calculation" and "derivation" not in normalized_item:
            raise ValueError(f"{path}.derivation: calculations require submitted inputs and formula text")
        items.append(normalized_item)
    return {"sources": sources, "items": items}


def _normalize_report(value: dict[str, Any], evidence_ids: set[str]) -> dict[str, Any]:
    data = _object(
        value,
        "report",
        ("recommendation", "status", "rationale", "tradeoffs", "uncertainties", "revisit_conditions", "next_actions"),
    )
    result: dict[str, Any] = {
        "recommendation": _text(data["recommendation"], "report.recommendation"),
        "status": _choice(data["status"], "report.status", _STATUS_LABELS),
    }
    rationale: list[dict[str, Any]] = []
    for index, entry in enumerate(_array(data["rationale"], "report.rationale", nonempty=True)):
        path = f"report.rationale[{index}]"
        reason = _object(entry, path, ("text", "evidence_ids"))
        text = _text(reason["text"], f"{path}.text")
        references: list[str] = []
        seen: set[str] = set()
        for ref_index, entry in enumerate(_array(reason["evidence_ids"], f"{path}.evidence_ids", nonempty=True)):
            ref_path = f"{path}.evidence_ids[{ref_index}]"
            identifier = _identifier(entry, ref_path)
            if identifier not in evidence_ids:
                raise ValueError(f"{ref_path}: unknown evidence reference")
            if identifier not in seen:
                references.append(identifier)
                seen.add(identifier)
        rationale.append({"text": text, "evidence_ids": references})
    result["rationale"] = rationale
    for field in ("tradeoffs", "uncertainties", "revisit_conditions", "next_actions"):
        path = f"report.{field}"
        result[field] = [
            _text(entry, f"{path}[{index}]")
            for index, entry in enumerate(_array(data[field], path, nonempty=field == "next_actions"))
        ]
    return result


def normalize_report(value: dict[str, Any], evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the submitted decision and its links to validated evidence.

    A missing evidence bundle cannot support a report's required rationale.
    Status is explicit and is never promoted based on the cited evidence.
    """
    bundle = normalize_evidence(evidence) if evidence is not None else {"sources": [], "items": []}
    return _normalize_report(value, {item["id"] for item in bundle["items"]})


def _markdown(text: str, *, indent: int = 0) -> str:
    # Punctuation escapes prevent links, headings, lists and raw HTML. Leading
    # whitespace and empty lines use character references so they cannot open
    # code blocks or break out of a list. Hard breaks require no raw HTML.
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        prefix_length = len(line) - len(line.lstrip(" \t"))
        prefix = "".join("&#32;" if char == " " else "&#9;" for char in line[:prefix_length])
        literal = prefix + line[prefix_length:].translate(_MARKDOWN_ESCAPES)
        lines.append(literal or "&#32;")
    return ("  \n" + " " * indent).join(lines)


def _evidence_lines(bundle: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not bundle["items"]:
        lines.extend(["", "未记录。"])
    for item in bundle["items"]:
        kind = item["kind"]
        verification = item["verification"]
        lines.extend(
            [
                "",
                f"### 证据 `{item['id']}`",
                "",
                f"- 陈述：{_markdown(item['statement'], indent=2)}",
                f"- 类型：{_KIND_LABELS[kind]}",
                f"- 核实状态：{_VERIFICATION_LABELS[verification]}",
                f"- 适用范围：{_markdown(item.get('applicability', '未知'), indent=2)}",
                f"- 推导：{_markdown(item.get('derivation', '未知'), indent=2)}",
            ]
        )
        if item["citations"]:
            for citation in item["citations"]:
                lines.append(f"- 来源：`{citation['source_id']}`；定位：{_markdown(citation['locator'], indent=2)}")
        else:
            lines.append("- 来源定位：未知（未提交引用）")
    lines.extend(["", "## 来源", ""])
    if not bundle["sources"]:
        lines.append("未记录。")
    for source in bundle["sources"]:
        lines.extend(
            [
                f"### 来源 `{source['id']}`",
                "",
                f"- 标题：{_markdown(source['title'], indent=2)}",
                f"- 参考：{_markdown(source.get('reference', '未知'), indent=2)}",
                f"- 版本：{_markdown(source.get('version', '未知'), indent=2)}",
                f"- 日期：{_markdown(source.get('date', '未知'), indent=2)}",
                "",
            ]
        )
    return lines


def render_evidence(evidence: dict[str, Any] | None) -> str:
    """Render all submitted evidence and sources as escaped, non-linking text."""
    if evidence is None:
        return "## 共同证据\n\n未提供。\n"
    bundle = normalize_evidence(evidence)
    lines = ["## 共同证据", "", "核实状态由提交方标注。", *_evidence_lines(bundle)]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_report(report: dict[str, Any], evidence: dict[str, Any] | None, context_revision: int) -> str:
    """Render the decision first, followed by cited evidence and brief revision.

    Evidence and source appendices retain submission order, including every
    locator and all metadata for the cited items. No text is truncated.
    """
    if type(context_revision) is not int or context_revision < 0:
        raise ValueError("context_revision: expected a nonnegative integer")
    bundle = normalize_evidence(evidence) if evidence is not None else {"sources": [], "items": []}
    decision = _normalize_report(report, {item["id"] for item in bundle["items"]})
    status = decision["status"]
    lines = [
        "# 决策报告",
        "",
        f"状态：{_STATUS_LABELS[status]}",
        "",
        "## 推荐",
        "",
        _markdown(decision["recommendation"]),
        "",
        "## 依据",
        "",
        "核实状态由提交方标注。",
        "",
    ]
    items_by_id = {item["id"]: item for item in bundle["items"]}
    cited_ids: set[str] = set()
    for index, reason in enumerate(decision["rationale"], start=1):
        cited_ids.update(reason["evidence_ids"])
        references = []
        for identifier in reason["evidence_ids"]:
            item = items_by_id[identifier]
            kind, verification = item["kind"], item["verification"]
            references.append(f"`{identifier}`：{_KIND_LABELS[kind]}，{_VERIFICATION_LABELS[verification]}")
        text = _markdown(reason["text"], indent=len(str(index)) + 2)
        lines.append(f"{index}. {text}（证据标注：{'；'.join(references)}）")
    for field, heading in (
        ("tradeoffs", "代价"),
        ("uncertainties", "不确定性"),
        ("revisit_conditions", "改变条件"),
        ("next_actions", "下一步"),
    ):
        lines.extend(["", f"## {heading}", ""])
        lines.extend(f"- {_markdown(text, indent=2)}" for text in decision[field])
        if not decision[field]:
            lines.append("未记录。")
    cited_items = [item for item in bundle["items"] if item["id"] in cited_ids]
    source_ids = {citation["source_id"] for item in cited_items for citation in item["citations"]}
    cited_sources = [source for source in bundle["sources"] if source["id"] in source_ids]
    lines.extend(["", "## 被引用证据", "", *_evidence_lines({"sources": cited_sources, "items": cited_items})])
    lines.extend(["", "## 输入简报版本", "", str(context_revision)])
    return "\n".join(lines).rstrip("\n") + "\n"
