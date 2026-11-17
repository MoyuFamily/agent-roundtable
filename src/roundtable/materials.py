"""Read explicitly supplied local materials into bounded, locatable packets.

``ready`` describes readable text, never verified facts. References are inert
metadata. There is no network access, OCR, directory discovery or LLM here.
Normalization preserves submitted text, metadata, segment order and statuses.
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import json
import logging
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path
from threading import RLock
from typing import Any

from roundtable.evidence import EVIDENCE_SCHEMA, normalize_evidence

__all__ = [
    "MATERIAL_SCHEMA",
    "material_digest",
    "material_summary",
    "normalize_material",
    "prepare_material",
    "select_segments",
]

_MAX_SEGMENTS = 1000
_MAX_SEGMENT_CHARS = 100_000
_MAX_TOTAL_CHARS = 500_000
_MAX_FILE_BYTES = 10 * 1024 * 1024
_LINES_PER_SEGMENT = 50
_PDF_LOCK = RLock()
_FORMATS = ("text", "markdown", "csv", "pdf", "image", "web", "other")
_STATUSES = ("ready", "needs_review", "unreadable")
_SUFFIX_FORMATS = {".txt": "text", ".md": "markdown", ".markdown": "markdown", ".csv": "csv", ".pdf": "pdf"}
_SOURCE_SCHEMA = deepcopy(EVIDENCE_SCHEMA["properties"]["sources"]["items"])
_METADATA_TEXT_SCHEMA = deepcopy(_SOURCE_SCHEMA["properties"]["title"])
_NONEMPTY_TEXT_SCHEMA = {"type": "string", "minLength": 1, "pattern": r"\S"}

MATERIAL_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["source", "format", "segments"],
    "description": (
        "Readiness is not factual verification. Unique segment IDs and the 500000-character "
        "aggregate text limit are validated at runtime; text is never truncated."
    ),
    "properties": {
        "source": _SOURCE_SCHEMA,
        "format": {"type": "string", "enum": list(_FORMATS)},
        "segments": {
            "type": "array",
            "minItems": 1,
            "maxItems": _MAX_SEGMENTS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "locator", "text", "status"],
                "properties": {
                    "id": deepcopy(_SOURCE_SCHEMA["properties"]["id"]),
                    "locator": deepcopy(_METADATA_TEXT_SCHEMA),
                    "text": {"type": "string", "maxLength": _MAX_SEGMENT_CHARS},
                    "status": {"type": "string", "enum": list(_STATUSES)},
                    "note": deepcopy(_METADATA_TEXT_SCHEMA),
                },
                "allOf": [
                    {
                        "if": {"properties": {"status": {"enum": ["ready", "needs_review"]}}},
                        "then": {"properties": {"text": deepcopy(_NONEMPTY_TEXT_SCHEMA)}},
                    },
                    {
                        "if": {"properties": {"status": {"enum": ["needs_review", "unreadable"]}}},
                        "then": {"required": ["note"]},
                    },
                ],
            },
        },
    },
}


def _object(value: object, path: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    if any(key not in required + optional for key in value):
        raise ValueError(f"{path}: unknown fields are not allowed")
    for key in required:
        if key not in value:
            raise ValueError(f"{path}.{key}: required field")
    return value


def _text(value: object, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path}: expected text")
    if nonempty and not value.strip():
        raise ValueError(f"{path}: expected nonempty text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{path}: expected valid Unicode text") from None
    return value


def _source(value: object) -> dict[str, Any]:
    try:
        source: dict[str, Any] = normalize_evidence({"sources": [value], "items": []})["sources"][0]
    except ValueError as error:
        # The evidence validator already reports only known contract paths.
        raise ValueError(str(error).replace("evidence.sources[0]", "material.source")) from None
    for field, value in source.items():
        _text(value, f"material.source.{field}")
    return source


def _metadata_text(value: object, path: str) -> str:
    text = _text(value, path)
    if re.search(_METADATA_TEXT_SCHEMA["not"]["pattern"], text):
        raise ValueError(f"{path}: unsupported control character")
    return text


def _segment_count(count: int) -> None:
    if count > _MAX_SEGMENTS:
        raise ValueError("material.segments: at most 1000 segments are allowed")


def _text_size(text: str, index: int, total: int) -> int:
    if len(text) > _MAX_SEGMENT_CHARS:
        raise ValueError(f"material.segments[{index}].text: at most 100000 characters are allowed")
    total += len(text)
    if total > _MAX_TOTAL_CHARS:
        raise ValueError("material.segments: total text exceeds 500000 characters")
    return total


def normalize_material(value: object) -> dict[str, Any]:
    """Validate and copy a packet; errors never echo values or unknown keys."""
    data = _object(value, "material", ("source", "format", "segments"))
    source = _source(data["source"])
    material_format = _text(data["format"], "material.format")
    if material_format not in _FORMATS:
        raise ValueError("material.format: unsupported value")
    entries = data["segments"]
    if not isinstance(entries, list):
        raise ValueError("material.segments: expected an array")
    if not entries:
        raise ValueError("material.segments: expected at least one segment")
    _segment_count(len(entries))
    segments: list[dict[str, str]] = []
    identifiers: set[str] = set()
    total = 0
    for index, entry in enumerate(entries):
        path = f"material.segments[{index}]"
        segment = _object(entry, path, ("id", "locator", "text", "status"), ("note",))
        identifier = _text(segment["id"], f"{path}.id")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) is None:
            raise ValueError(f"{path}.id: expected 1-64 ASCII letters, digits, underscores or hyphens")
        if identifier in identifiers:
            raise ValueError(f"{path}.id: duplicate segment ID")
        identifiers.add(identifier)
        status = _text(segment["status"], f"{path}.status")
        if status not in _STATUSES:
            raise ValueError(f"{path}.status: unsupported value")
        text = _text(segment["text"], f"{path}.text", nonempty=status != "unreadable")
        total = _text_size(text, index, total)
        normalized = {
            "id": identifier,
            "locator": _metadata_text(segment["locator"], f"{path}.locator"),
            "text": text,
            "status": status,
        }
        if "note" in segment:
            normalized["note"] = _metadata_text(segment["note"], f"{path}.note")
        elif status != "ready":
            raise ValueError(f"{path}.note: required for non-ready segments")
        segments.append(normalized)
    return {"source": source, "format": material_format, "segments": segments}


def _digest(packet: dict[str, Any]) -> str:
    canonical = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def material_digest(material: object) -> str:
    """SHA-256 of validated JSON: sorted keys, compact separators, UTF-8."""
    return _digest(normalize_material(material))


def material_summary(material: object) -> dict[str, Any]:
    """Return metadata and non-ready segment issues, without segment text."""
    packet = normalize_material(material)
    return {
        "source": packet["source"],
        "format": packet["format"],
        "digest": _digest(packet),
        "segment_count": len(packet["segments"]),
        "issues": [
            {"segment_id": segment["id"], **{field: segment[field] for field in ("locator", "status", "note")}}
            for segment in packet["segments"]
            if segment["status"] != "ready"
        ],
    }


def select_segments(material: object, *, offset: int = 0, limit: int = 10, query: str | None = None) -> dict[str, Any]:
    """Copy complete matching segments in order; offsets address filtered results.

    ``total`` counts all matches. ``next_offset`` is None when exhausted. The
    digest identifies the entire packet, independent of the requested page.
    Searching casefolds text and query without stripping or changing either.
    """
    if type(offset) is not int or offset < 0:
        raise ValueError("offset: expected a nonnegative integer")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit: expected an integer from 1 to 50")
    folded_query = _text(query, "query").casefold() if query is not None else None
    packet = normalize_material(material)
    matching = [
        segment for segment in packet["segments"] if folded_query is None or folded_query in segment["text"].casefold()
    ]
    end = offset + limit
    return {
        "source": packet["source"],
        "format": packet["format"],
        "digest": _digest(packet),
        "segments": matching[offset:end],
        "offset": offset,
        "limit": limit,
        "total": len(matching),
        "next_offset": end if end < len(matching) else None,
    }


class _Segments:
    """Enforce limits while extracting, before a partial packet can escape."""

    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []
        self.total = 0

    def add(self, text: str, locator: str, status: str, note: str | None = None) -> None:
        index = len(self.entries)
        _segment_count(index + 1)
        self.total = _text_size(text, index, self.total)
        segment = {"id": f"segment-{index + 1}", "locator": locator, "text": text, "status": status}
        if note is not None:
            segment["note"] = note
        self.entries.append(segment)


def _local_path(value: str | os.PathLike[str]) -> Path:
    try:
        raw = os.fspath(value)
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ValueError
        raw.encode("utf-8")
        return Path(raw)
    except (TypeError, ValueError, OSError):
        raise ValueError("path: expected a local file path") from None


def _read_file(path: Path) -> bytes:
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("path: expected a local regular file")
        if info.st_size > _MAX_FILE_BYTES:
            raise ValueError("path: file exceeds 10 MiB")
        with path.open("rb") as stream:
            contents = stream.read(_MAX_FILE_BYTES + 1)
    except OSError:
        raise ValueError("path: unable to read local file") from None
    if len(contents) > _MAX_FILE_BYTES:
        raise ValueError("path: file exceeds 10 MiB")
    return contents


def _text_segments(text: str) -> list[dict[str, str]]:
    segments = _Segments()
    lines: list[str] = []
    start, end = 1, 0
    # newline="" recognizes CR, LF and CRLF physical lines without translating.
    for end, line in enumerate(StringIO(text, newline=""), start=1):
        lines.append(line)
        if len(lines) == _LINES_PER_SEGMENT:
            _add_text_segment(segments, "".join(lines), start, end)
            lines = []
            start = end + 1
    if lines or not segments.entries:
        _add_text_segment(segments, "".join(lines), start, max(end, 1))
    return segments.entries


def _add_text_segment(segments: _Segments, text: str, start: int, end: int) -> None:
    readable = bool(text.strip())
    segments.add(
        text,
        f"lines {start}-{end}",
        "ready" if readable else "unreadable",
        None if readable else "No non-whitespace text in these lines.",
    )


def _csv_segments(text: str) -> list[dict[str, str]]:
    segments = _Segments()
    reader = csv.reader(StringIO(text, newline=""), strict=True)
    previous_line = 0
    try:
        for row, cells in enumerate(reader, start=1):
            readable = any(cell.strip() for cell in cells)
            segments.add(
                json.dumps(cells, ensure_ascii=False, separators=(",", ":")),
                f"row {row} (lines {previous_line + 1}-{reader.line_num})",
                "ready" if readable else "unreadable",
                None if readable else "No non-whitespace cell text in this CSV row.",
            )
            previous_line = reader.line_num
    except csv.Error:
        raise ValueError("path: invalid CSV or CSV field exceeds the parser limit") from None
    if not segments.entries:
        segments.add("", "row 1 (lines 1-1)", "unreadable", "No CSV rows were read.")
    return segments.entries


@contextmanager
def _quiet_pdf_diagnostics() -> Iterator[None]:
    # pypdf diagnostics can include document bytes. Suppress its namespace
    # while reading, leaving application/root logging configuration intact.
    with _PDF_LOCK:
        parent = logging.getLogger("pypdf")
        loggers = [parent] + [
            logger
            for name, logger in list(parent.manager.loggerDict.items())
            if name.startswith("pypdf.") and isinstance(logger, logging.Logger)
        ]
        state = [(logger, logger.handlers, logger.propagate) for logger in loggers]
        for logger in loggers:
            logger.handlers, logger.propagate = [logging.NullHandler()], False
        try:
            yield
        finally:
            for logger, handlers, propagate in state:
                logger.handlers, logger.propagate = handlers, propagate


def _pdf_segments(contents: bytes) -> list[dict[str, str]]:
    with _quiet_pdf_diagnostics():
        try:
            pdf = importlib.import_module("pypdf")
        except ImportError:
            raise ValueError(
                "material.format: PDF extraction requires pip install 'agent-roundtable[materials]'"
            ) from None
        try:
            reader = pdf.PdfReader(BytesIO(contents))
            page_count = len(reader.pages)
        except Exception:
            raise ValueError("path: unable to read PDF") from None
        _segment_count(page_count)
        segments = _Segments()
        for index in range(page_count):
            try:
                text = reader.pages[index].extract_text()
            except Exception:
                segments.add(
                    "",
                    f"page {index + 1}",
                    "unreadable",
                    "Text extraction failed for this page; visual review is needed. No OCR was performed.",
                )
                continue
            if isinstance(text, str) and text.strip():
                segments.add(
                    text,
                    f"page {index + 1}",
                    "needs_review",
                    "Visually review images, tables and reading order against the PDF. No OCR was performed.",
                )
            else:
                segments.add(
                    text if isinstance(text, str) else "",
                    f"page {index + 1}",
                    "unreadable",
                    "No text was extracted from this page; visual review is needed. No OCR was performed.",
                )
        if not segments.entries:
            segments.add("", "document", "unreadable", "The PDF has no pages. No OCR was performed.")
        return segments.entries


def prepare_material(
    path: str | os.PathLike[str], *, source_id: str, title: str, format: str | None = None
) -> dict[str, Any]:
    """Read one explicit local TXT/MD/CSV/PDF, without storing its path.

    A title is always supplied by the caller. Text uses at most 50 physical
    lines per segment; CSV uses one logical row; PDF uses one page. Unsupported
    formats, invalid encoding and exceeded limits fail without partial output.
    """
    source = _source({"id": source_id, "title": title})
    local_path = _local_path(path)
    material_format = _SUFFIX_FORMATS.get(local_path.suffix.lower()) if format is None else format
    if not isinstance(material_format, str) or material_format not in ("text", "markdown", "csv", "pdf"):
        raise ValueError("material.format: local extraction supports text, markdown, csv or pdf")
    contents = _read_file(local_path)
    if material_format == "pdf":
        segments = _pdf_segments(contents)
    else:
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("path: expected UTF-8 or UTF-8 BOM text") from None
        segments = _csv_segments(text) if material_format == "csv" else _text_segments(text)
    return normalize_material({"source": source, "format": material_format, "segments": segments})
