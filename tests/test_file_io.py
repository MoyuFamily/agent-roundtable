"""Durability of snapshots shared by independent viewer writers."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from roundtable.file_io import file_lock, write_json_atomic


def _merge_records(directory, worker, barrier):
    target = Path(directory) / "discussion.json"
    barrier.wait(timeout=15)
    for index in range(12):
        with file_lock(target.with_suffix(".json.lock")):
            data = json.loads(target.read_text(encoding="utf-8"))
            data["records"].append({"id": [worker, index], "text": "独立进程的评审 🌱"})
            write_json_atomic(target, data)


def test_concurrent_processes_preserve_all_snapshot_updates(tmp_path):
    target = tmp_path / "discussion.json"
    write_json_atomic(target, {"records": []})
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    workers = [context.Process(target=_merge_records, args=(str(tmp_path), index, barrier)) for index in range(3)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
    records = json.loads(target.read_text(encoding="utf-8"))["records"]
    assert len(records) == 36
    assert {tuple(record["id"]) for record in records} == {
        (worker, index) for worker in range(3) for index in range(12)
    }
    assert all(record["text"] == "独立进程的评审 🌱" for record in records)


def test_failed_serialization_preserves_previous_snapshot_and_releases_lock(tmp_path):
    target = tmp_path / "discussion.json"
    saved = {"conclusion": "保留原始结论 🌱"}
    write_json_atomic(target, saved)
    with pytest.raises(TypeError), file_lock(target.with_suffix(".json.lock")):
        write_json_atomic(target, {"invalid": object()})
    assert json.loads(target.read_text(encoding="utf-8")) == saved
    assert not list(tmp_path.glob("*.tmp"))
    with file_lock(target.with_suffix(".json.lock")):
        write_json_atomic(target, {"conclusion": "恢复后更新"})
    assert json.loads(target.read_text(encoding="utf-8"))["conclusion"] == "恢复后更新"
