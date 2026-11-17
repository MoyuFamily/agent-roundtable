"""Offline behavioral coverage using only synthetic material and temporary files."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from roundtable import materials as mt
from roundtable.evidence import EVIDENCE_SCHEMA, normalize_evidence

Payload = dict[str, Any]


@pytest.fixture
def material() -> Payload:
    return {
        "source": {
            "id": "S1",
            "title": "合成资料",
            "reference": "synthetic://inert-reference",
            "version": "v1",
            "date": "2026-11-17",
        },
        "format": "text",
        "segments": [
            {"id": "seg-1", "locator": "lines 1-2", "text": "Straße 合成文本\r\n第二行\r\n", "status": "ready"},
            {
                "id": "seg-2",
                "locator": "lines 3-4",
                "text": "需核对的完整原文",
                "status": "needs_review",
                "note": "请核对图像与表格",
            },
            {"id": "seg-3", "locator": "lines 5-6", "text": "", "status": "unreadable", "note": "无可提取文字"},
        ],
    }


def test_utf8_bom_and_markdown_preserve_physical_lines_and_blank_segments(tmp_path: Path) -> None:
    endings = ("\r\n", "\n", "\r")
    lines = [f"第 {index} 行\u2028仍是同一物理行{endings[index % 3]}" for index in range(1, 102)]
    lines.append("最后一行没有换行符")
    text = "".join(lines)
    for suffix, encoding, expected_format in ((".TXT", "utf-8", "text"), (".md", "utf-8-sig", "markdown")):
        path = tmp_path / f"synthetic-filename{suffix}"
        path.write_bytes(text.encode(encoding))
        packet = mt.prepare_material(path, source_id="S1", title="显式标题")
        assert packet["source"] == {"id": "S1", "title": "显式标题"}
        assert packet["format"] == expected_format
        assert [segment["locator"] for segment in packet["segments"]] == ["lines 1-50", "lines 51-100", "lines 101-102"]
        assert [segment["text"] for segment in packet["segments"]] == [
            "".join(lines[:50]),
            "".join(lines[50:100]),
            "".join(lines[100:]),
        ]
        assert all(segment["status"] == "ready" for segment in packet["segments"])
        assert str(path) not in json.dumps(packet) and path.name not in json.dumps(packet)
        assert normalize_evidence({"sources": [packet["source"]], "items": []})["sources"] == [packet["source"]]
    override = tmp_path / "explicit-format.data"
    override.write_bytes(text.encode("utf-8"))
    assert mt.prepare_material(override, source_id="S1", title="标题", format="text")["format"] == "text"
    for text in ("", " \r\n\t\r\n", "\ufeff"):
        override.write_bytes(text.encode("utf-8"))
        segment = mt.prepare_material(override, source_id="S1", title="标题", format="text")["segments"]
        assert len(segment) == 1 and segment[0]["status"] == "unreadable" and segment[0]["note"]
    override.write_bytes(("\n" * 50 + "tail").encode())
    packet = mt.prepare_material(override, source_id="S1", title="标题", format="text")
    assert [entry["status"] for entry in packet["segments"]] == ["unreadable", "ready"]
    assert "".join(entry["text"] for entry in packet["segments"]) == "\n" * 50 + "tail"


def test_csv_logical_rows_preserve_quoted_multiline_cells_and_physical_locations(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    text = 'name,note,quote\r\n"中 文","first\r\nsecond","said ""yes"""\r\nlast,value,\r\n\r\n'
    path.write_bytes(text.encode("utf-8-sig"))
    packet = mt.prepare_material(path, source_id="CSV_1", title="合成表格")
    assert [json.loads(entry["text"]) for entry in packet["segments"]] == [
        ["name", "note", "quote"],
        ["中 文", "first\r\nsecond", 'said "yes"'],
        ["last", "value", ""],
        [],
    ]
    assert [entry["locator"] for entry in packet["segments"]] == [
        "row 1 (lines 1-1)",
        "row 2 (lines 2-3)",
        "row 3 (lines 4-4)",
        "row 4 (lines 5-5)",
    ]
    assert [entry["status"] for entry in packet["segments"]] == ["ready", "ready", "ready", "unreadable"]
    for text in ("", " , \r\n"):
        path.write_bytes(text.encode())
        packet = mt.prepare_material(path, source_id="S1", title="空表格")
        assert len(packet["segments"]) == 1 and packet["segments"][0]["status"] == "unreadable"
    marker = "SYNTHETIC_CSV_SECRET"
    path.write_text(f'good,row\n"{marker}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"^path:") as error:
        mt.prepare_material(path, source_id="S1", title="合成表格")
    assert marker not in str(error.value) and str(path) not in str(error.value)


def test_synthetic_pdf_keeps_blank_text_and_broken_pages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pdf = pytest.importorskip("pypdf")
    generic = pdf.generic
    writer = pdf.PdfWriter()
    for index in range(4):
        page = writer.add_blank_page(width=300, height=300)
        if index in (1, 3):
            font = generic.DictionaryObject(
                {
                    generic.NameObject("/Type"): generic.NameObject("/Font"),
                    generic.NameObject("/Subtype"): generic.NameObject("/Type1"),
                    generic.NameObject("/BaseFont"): generic.NameObject("/Helvetica"),
                }
            )
            page[generic.NameObject("/Resources")] = generic.DictionaryObject(
                {generic.NameObject("/Font"): generic.DictionaryObject({generic.NameObject("/F1"): font})}
            )
            stream = generic.DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 30 200 Td (Synthetic page {index + 1}) Tj ET".encode())
            page[generic.NameObject("/Contents")] = stream
        elif index == 2:
            page[generic.NameObject("/Contents")] = generic.NumberObject(9)
    path = tmp_path / "synthetic.pdf"
    writer.write(path)
    packet = mt.prepare_material(path, source_id="PDF_1", title="合成 PDF")
    assert [entry["locator"] for entry in packet["segments"]] == ["page 1", "page 2", "page 3", "page 4"]
    assert [entry["status"] for entry in packet["segments"]] == [
        "unreadable",
        "needs_review",
        "unreadable",
        "needs_review",
    ]
    assert packet["segments"][0]["text"] == packet["segments"][2]["text"] == ""
    assert packet["segments"][2]["note"]
    reader = pdf.PdfReader(BytesIO(path.read_bytes()))
    for index in (1, 3):
        assert packet["segments"][index]["text"] == reader.pages[index].extract_text()
        assert f"Synthetic page {index + 1}" in packet["segments"][index]["text"]
        assert "images, tables" in packet["segments"][index]["note"]
    assert len(mt.material_summary(packet)["issues"]) == 4
    assert all("No OCR" in entry["note"] for entry in packet["segments"])
    empty_writer = pdf.PdfWriter()
    empty_writer.write(path)
    empty = mt.prepare_material(path, source_id="PDF_1", title="合成空 PDF")
    assert len(empty["segments"]) == 1 and empty["segments"][0]["status"] == "unreadable"
    writer.encrypt("synthetic-password")
    writer.write(path)
    with pytest.raises(ValueError, match=r"^path: unable to read PDF$"):
        mt.prepare_material(path, source_id="PDF_1", title="合成加密 PDF")
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_pdf_dependency_failures_and_diagnostics_are_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "SYNTHETIC_PRIVATE_PATH.pdf"
    path.write_bytes(b"SYNTHETIC_PDF_CONTENT")
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "pypdf", None)
        with pytest.raises(ValueError, match=r"pip install 'agent-roundtable\[materials\]'"):
            mt.prepare_material(path, source_id="S1", title="合成 PDF")
    marker = "SYNTHETIC_PRIVATE_CONTENT"

    def failing_reader(stream: BytesIO) -> None:
        assert stream.read() == path.read_bytes()
        logging.getLogger("pypdf._reader").warning("%s %s", marker, path)
        raise RuntimeError(f"{marker} {path}")

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=failing_reader))
    logger = logging.getLogger("pypdf")
    handlers, propagate = logger.handlers, logger.propagate
    diagnostics = StringIO()
    child = logging.getLogger("pypdf._reader")
    child_handler = logging.StreamHandler(diagnostics)
    monkeypatch.setattr(child, "handlers", [child_handler])
    monkeypatch.setattr(child, "propagate", False)
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError, match=r"^path: unable to read PDF$") as error:
        mt.prepare_material(path, source_id="S1", title="合成 PDF")
    assert error.value.__suppress_context__
    assert marker not in str(error.value) and str(path) not in str(error.value)
    assert logger.handlers is handlers and logger.propagate == propagate
    assert child.handlers == [child_handler] and child.propagate is False
    assert diagnostics.getvalue() == ""
    assert marker not in caplog.text
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""

    def broken_page() -> str:
        logging.getLogger("pypdf._page").warning("%s", marker)
        raise ValueError(marker)

    class PageReader:
        def __init__(self, stream: BytesIO) -> None:
            self.pages = [
                SimpleNamespace(extract_text=lambda: ""),
                SimpleNamespace(extract_text=broken_page),
                SimpleNamespace(extract_text=lambda: "Complete later page"),
            ]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=PageReader))
    packet = mt.prepare_material(path, source_id="S1", title="合成 PDF")
    assert [entry["status"] for entry in packet["segments"]] == ["unreadable", "unreadable", "needs_review"]
    assert "failed" in packet["segments"][1]["note"]
    assert packet["segments"][2]["text"] == "Complete later page"
    assert marker not in json.dumps(packet) and marker not in caplog.text

    class LargeReader:
        def __init__(self, stream: BytesIO) -> None:
            self.pages = [SimpleNamespace(extract_text=lambda: "x" * 100_001)]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=LargeReader))
    with pytest.raises(ValueError, match=r"^material.segments\[0\].text:"):
        mt.prepare_material(path, source_id="S1", title="合成 PDF")


def test_limits_reject_without_silent_truncation(tmp_path: Path, material: Payload) -> None:
    def packet_with(texts: list[str]) -> Payload:
        return {
            **material,
            "segments": [
                {"id": f"s-{index}", "locator": f"row {index + 1}", "text": text, "status": "ready"}
                for index, text in enumerate(texts)
            ],
        }

    boundary = packet_with(["x" * 100_000] * 5)
    assert mt.normalize_material(boundary) == boundary
    assert len(mt.normalize_material(packet_with(["x"] * 1000))["segments"]) == 1000
    for texts, error_path in (
        (["x" * 100_001], r"^material.segments\[0\].text:"),
        (["x" * 100_000] * 5 + ["x"], r"^material.segments:"),
        (["x"] * 1001, r"^material.segments:"),
    ):
        with pytest.raises(ValueError, match=error_path):
            mt.normalize_material(packet_with(texts))
    text_path = tmp_path / "large.txt"
    exact = ("x" * 1999 + "\n") * 250
    text_path.write_text(exact, encoding="utf-8")
    packet = mt.prepare_material(text_path, source_id="S1", title="合成边界文本")
    assert "".join(segment["text"] for segment in packet["segments"]) == exact
    for text, error_path in ((exact + "x", r"^material.segments:"), ("x" * 100_001, r"^material.segments\[0\].text:")):
        text_path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=error_path):
            mt.prepare_material(text_path, source_id="S1", title="合成超限文本")
    csv_path = tmp_path / "large.csv"
    for text in ("x\n" * 1001, "x" * 100_000):
        csv_path.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=r"^material.segments"):
            mt.prepare_material(csv_path, source_id="S1", title="合成超限表格")
    with text_path.open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match=r"^path: file exceeds 10 MiB$"):
        mt.prepare_material(text_path, source_id="S1", title="合成超限文件")


def test_search_pages_return_complete_unchanged_segments_and_strict_arguments(material: Payload) -> None:
    material["segments"] = [
        {
            "id": f"s-{index}",
            "locator": f"row {index + 1}",
            "text": ("Straße" if index % 2 == 0 else "other") + "合成完整文本" * 5000 + f"TAIL-{index}",
            "status": ("ready", "needs_review", "unreadable")[index % 3],
            "note": "保留提交状态",
        }
        for index in range(13)
    ]
    original = deepcopy(material)
    collected: list[Payload] = []
    offset = 0
    while True:
        page = mt.select_segments(material, offset=offset, limit=3, query="STRASSE")
        assert page["offset"] == offset and page["limit"] == 3 and page["total"] == 7
        assert page["digest"] == mt.material_digest(material) and page["source"] == material["source"]
        collected.extend(page["segments"])
        if page["next_offset"] is None:
            break
        assert page["next_offset"] == offset + 3
        offset = page["next_offset"]
    assert collected == material["segments"][::2]
    assert mt.select_segments(material)["segments"] == material["segments"][:10]
    assert mt.select_segments(material, limit=50)["segments"] == material["segments"]
    assert mt.select_segments(material, offset=1000)["next_offset"] is None
    assert mt.select_segments(material, offset=1000)["segments"] == []
    assert mt.select_segments(material, query="row 1")["total"] == 0
    assert mt.select_segments(material, query="保留提交状态")["total"] == 0
    assert mt.select_segments(material, query=" Straße ")["total"] == 0
    for key, values in (
        ("offset", (-1, True)),
        ("limit", (0, 51)),
        ("query", (" \n", 12)),
    ):
        for value in values:
            arguments: dict[str, Any] = {key: value}
            with pytest.raises(ValueError, match=rf"^{key}:"):
                mt.select_segments(material, **arguments)
    page["source"]["title"] = "changed"
    collected[0]["text"] = "changed"
    assert material == original


def test_canonical_hash_and_summary_are_complete_deterministic_and_immutable(material: Payload) -> None:
    original = deepcopy(material)
    normalized = mt.normalize_material(material)
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert mt.material_digest(material) == digest
    reordered = json.loads(json.dumps(material, sort_keys=True))
    assert mt.material_digest(reordered) == digest
    summary = mt.material_summary(material)
    assert summary == {
        "source": material["source"],
        "format": "text",
        "digest": digest,
        "segment_count": 3,
        "issues": [
            {"segment_id": entry["id"], "locator": entry["locator"], "status": entry["status"], "note": entry["note"]}
            for entry in material["segments"][1:]
        ],
    }
    assert '"text"' not in json.dumps(summary["issues"])
    normalized["source"]["title"] = "changed"
    normalized["segments"][0]["text"] = "changed"
    assert mt.material_digest(normalized) != digest
    summary["source"]["title"] = "changed"
    summary["issues"][0]["note"] = "changed"
    assert material == original and mt.material_digest(material) == digest


def test_schema_and_validation_reject_forged_ids_unknown_keys_and_types_without_echo(material: Payload) -> None:
    marker = "/synthetic-private-path/PRIVATE_VALUE"
    invalid_packets = [
        material | {marker: marker},
        material | {"source": material["source"] | {marker: marker}},
        material | {"source": material["source"] | {"id": marker}},
        material | {"source": material["source"] | {"id": True}},
        material | {"segments": []},
        material | {"segments": ()},
    ]
    for change in (
        {marker: marker},
        {"id": "bad\n"},
        {"id": "x" * 65},
        {"locator": "bad\x1b"},
        {"note": "bad\x1b"},
        {"text": ""},
        {"status": "needs_review"},
        {"status": "unreadable"},
    ):
        value = deepcopy(material)
        value["segments"][0].update(change)
        invalid_packets.append(value)
    for value in invalid_packets:
        with pytest.raises(ValueError, match=r"^material[.:]") as error:
            mt.normalize_material(value)
        assert marker not in str(error.value)
    duplicate = deepcopy(material)
    duplicate["segments"][1]["id"] = duplicate["segments"][0]["id"]
    with pytest.raises(ValueError, match=r"^material.segments\[1\].id: duplicate"):
        mt.normalize_material(duplicate)
    raw = deepcopy(material)
    raw["segments"][0]["text"] = "raw\x00\x1b\ftext"
    assert mt.normalize_material(raw) == raw
    validator = pytest.importorskip("jsonschema").Draft202012Validator
    validator.check_schema(mt.MATERIAL_SCHEMA)
    assert mt.MATERIAL_SCHEMA["properties"]["source"] == EVIDENCE_SCHEMA["properties"]["sources"]["items"]
    assert validator(mt.MATERIAL_SCHEMA).is_valid(raw)
    for value in invalid_packets:
        assert not validator(mt.MATERIAL_SCHEMA).is_valid(value)


def test_cli_utf8_json_and_errors_do_not_leak_paths_or_content(tmp_path: Path) -> None:
    marker = "SYNTHETIC_PRIVATE_MARKER"
    path = tmp_path / f"{marker}.txt"
    path.write_bytes("合成原文\r\n完整尾行".encode())
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONIOENCODING"] = "ascii:strict"

    def run(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, "-m", "roundtable.import_material", *arguments],
            capture_output=True,
            check=False,
            env=environment,
            timeout=20,
        )

    required = ["--source-id", "S1", "--title", "显式标题"]
    result = run([str(path), *required])
    assert result.returncode == 0 and result.stderr == b""
    packet = json.loads(result.stdout.decode("utf-8"))
    assert packet["segments"][0]["text"] == "合成原文\r\n完整尾行"
    assert packet["source"]["title"] == "显式标题" and "显式标题".encode() in result.stdout
    assert marker.encode() not in result.stdout and str(path).encode() not in result.stdout
    invalid_utf8 = tmp_path / f"{marker}-encoding.txt"
    invalid_utf8.write_bytes(b"\xff" + marker.encode())
    invalid_pdf = tmp_path / f"{marker}.pdf"
    invalid_pdf.write_bytes(marker.encode())
    for arguments in (
        [str(tmp_path / f"{marker}-missing.txt"), *required],
        [str(path), "--source-id", f"../{marker}", "--title", "title"],
        [str(path), *required, f"--{marker}"],
        [str(path), "--source-id", "S1"],
        [str(path), *required, "--format", marker],
        [str(invalid_utf8), *required],
        [str(invalid_pdf), *required],
        [str(tmp_path), *required, "--format", "text"],
    ):
        result = run(arguments)
        assert result.returncode == 2 and result.stdout == b"" and result.stderr
        assert marker.encode() not in result.stderr and str(tmp_path).encode() not in result.stderr
        assert b"Traceback" not in result.stderr
    with pytest.raises(ValueError, match=r"^material.source.title:"):
        mt.prepare_material(path, source_id="S1", title="")
