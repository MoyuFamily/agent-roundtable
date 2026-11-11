"""Shared file coordination for viewer snapshots and replay events."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def file_lock(path: Path, *, shared: bool = False) -> Iterator[None]:
    """Lock a stable sidecar file; Windows uses an exclusive byte-range lock."""
    with path.open("a+b") as lock:
        if sys.platform == "win32":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Replace a UTF-8 snapshot, leaving the previous file intact on failure.

    Callers hold the sidecar lock across their complete read/merge/write operation.
    """
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    """Append one complete UTF-8 event across cooperating writer processes."""
    with file_lock(path.with_suffix(path.suffix + ".lock")), path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
