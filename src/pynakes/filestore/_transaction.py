"""Durable roll-forward journal for native ingestion (not global atomicity).

Every output is staged and fsynced before the journal is published. Recovery
accepts only original or intended bytes, checks all targets before changing any,
and installs materials before manifests, bibliographies and finally receipts.
An external edit blocks recovery rather than being overwritten. Moved originals
are removed only after every output is verified; one that cannot be removed is
kept and reported, since the transaction is already complete.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pynakes._atomic import sync_directory, sync_file
from pynakes.filestore._atomic import _atomic_write_bytes, _process_alive


class MaterialConflictError(ValueError):
    """A reviewed source or destination changed; leave it for explicit review."""


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"Expected regular file: {path}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def _inside(root: Path, path: Path) -> str | None:
    """Return ``path`` relative to ``root``, or None when it lies outside.

    Containment compares real locations, so a root reached through a symlinked,
    mapped or short-name directory still owns its files. Below the root, no
    component may be a symlink, and ``..`` is refused.
    """
    real_root = root.resolve()
    path = path.absolute()
    for anchor in (path, *path.parents):
        if anchor.resolve() == real_root:
            break
    else:
        return None
    relative = path.relative_to(anchor)
    if ".." in relative.parts:
        raise ValueError("Invalid ingestion target")
    current = anchor
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Symlink in ingestion target: {current}")
    return relative.as_posix()


def contained(root: Path, path: Path) -> str:
    """Require a real, contained path, including currently absent parents."""
    relative = _inside(root, path)
    if relative is None:
        raise ValueError(f"Managed ingestion target is outside the Library root: {path}")
    return relative


def retained_warnings(report: dict) -> list[str]:
    """Render the originals a completed move had to keep as envelope warnings."""
    return [f"Kept {item['path']}: {item['reason']}" for item in report.get("retained_sources", [])]


@dataclass(frozen=True)
class Output:
    path: Path
    before: str | None
    data: bytes | Path


_LOCK_NAME = re.compile(r"lock-(\d+)-(\d+)")


@contextmanager
def locked(state: Path) -> Generator[None, None, None]:
    """Serialize cooperating ingest/recover commands; reclaim dead-process locks.

    Each holder claims ``lock-<pid>-<thread>``. The holder is in the name, which
    is created in one step, so a crash never leaves an anonymous lock behind.
    A claim stands only if no live process holds another; claims of exited
    processes are swept, and two racing claims both withdraw.
    """
    state.mkdir(parents=True, exist_ok=True)
    mine = state / f"lock-{os.getpid()}-{threading.get_ident()}"
    with mine.open("x", encoding="ascii"):
        pass
    try:
        for other in state.glob("lock-*"):
            if other == mine:
                continue
            match = _LOCK_NAME.fullmatch(other.name)
            if match is None:
                raise ValueError(f"Unrecognised ingestion lock; inspect {other}")
            if _process_alive(int(match[1])):
                raise ValueError("Another ingestion operation is running")
            other.unlink(missing_ok=True)
        yield
    finally:
        mine.unlink(missing_ok=True)


def _install(root: Path, state: Path, journal: dict) -> dict:
    if journal.get("version") != 1 or not isinstance(journal.get("outputs"), list):
        raise ValueError("Unsupported ingestion journal")
    for name, expected in journal["guards"].items():
        path = root / name
        contained(root, path)
        if digest(path) != expected:
            raise MaterialConflictError(f"Recovery blocked by changed Library input: {path}")
    for item in journal["outputs"]:
        target = root / item["path"]
        contained(root, target)
        blob = state / item["blob"]
        contained(state, blob)
        if digest(blob) != item["after"]:
            raise ValueError(f"Missing or damaged recovery payload: {blob}")
        if digest(target) not in (item["before"], item["after"]):
            raise MaterialConflictError(f"Recovery blocked by external changes: {target}")
    for item in journal["outputs"]:
        target = root / item["path"]
        if digest(target) == item["after"]:
            continue
        if digest(target) != item["before"]:
            raise MaterialConflictError(f"Target changed during recovery: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Use a same-filesystem temporary and fsync/replace through shared helpers.
        _atomic_write_bytes(target, (state / item["blob"]).read_bytes(), target.parent)
    # Recheck all published links and receipts before retiring any original.
    for output in journal["outputs"]:
        target = root / output["path"]
        contained(root, target)
        if digest(target) != output["after"]:
            raise MaterialConflictError(f"Committed output changed; sources retained: {target}")
    retained = []
    for item in journal.get("remove_sources", []):
        reason = _retire_source(root, item)
        if reason is not None:
            retained.append({"path": item["path"], "reason": reason})
    result = {**journal["report"], "retained_sources": retained}
    (state / "journal.json").unlink()
    sync_directory(state)
    shutil.rmtree(state / "payloads", ignore_errors=True)
    return result


def _retire_source(root: Path, item: dict) -> str | None:
    """Remove one moved original, or return why it was kept.

    Every output is committed and verified by now, so nothing here may block
    the transaction: an original that changed, is the stored copy itself (a
    hard link or case-insensitive alias), or cannot be removed (open in a
    viewer, read-only) stays in place and is reported.
    """
    source = Path(item["path"])
    target = root / item["target"]
    contained(root, target)
    try:
        if not source.exists() and not source.is_symlink():
            return None
        if source.is_symlink() or digest(source) != item["sha256"]:
            return "source changed after the stored copy was committed"
        # Check the stored copy again immediately before retiring the source.
        if digest(target) != item["sha256"]:
            return "stored copy changed before the source could be removed"
        if os.path.samefile(source, target):
            return "source is the stored copy"
        source.unlink()
    except (OSError, ValueError) as exc:
        return f"source could not be removed ({exc})"
    sync_directory(source.parent)
    return None


def recover(root: Path, state: Path) -> dict:
    """Complete a prepared transaction without re-extraction or provider calls."""
    contained(root, state)
    if not (state / "journal.json").exists():
        return {"recovered": False}
    with locked(state):
        path = state / "journal.json"
        if not path.exists():
            return {"recovered": False}
        journal = json.loads(path.read_text(encoding="utf-8"))
        return {"recovered": True, **_install(root, state, journal)}


def commit(
    root: Path,
    state: Path,
    outputs: list[Output],
    guards: dict[Path, str | None],
    report: dict,
    *,
    remove_sources: list[dict] | None = None,
    recover_command: str = "library recover",
) -> dict:
    """Prepare all bytes and publish a replayable transaction before mutation."""
    contained(root, state)
    with locked(state):
        journal_path = state / "journal.json"
        if journal_path.exists():
            raise ValueError(f"Interrupted ingestion: run {recover_command} before another import")
        for path, expected in guards.items():
            if digest(path) != expected:
                raise MaterialConflictError(f"Ingestion input changed: {path}")
        if len({output.path for output in outputs}) != len(outputs):
            raise ValueError("Duplicate ingestion output")
        payloads = state / "payloads"
        contained(root, payloads)
        payloads.mkdir(exist_ok=True)
        items = []
        for index, output in enumerate(outputs):
            name = contained(root, output.path)
            if digest(output.path) != output.before:
                raise MaterialConflictError(f"Ingestion destination changed: {output.path}")
            blob = payloads / str(index)
            contained(root, blob)
            with blob.open("wb") as stream:
                if isinstance(output.data, Path):
                    with output.data.open("rb") as source:
                        shutil.copyfileobj(source, stream)
                else:
                    stream.write(output.data)
                sync_file(stream)
            if isinstance(output.data, Path) and digest(blob) != guards.get(output.data):
                raise ValueError("Staged material differs from inspected source")
            items.append(
                {
                    "path": name,
                    "before": output.before,
                    "after": digest(blob),
                    "blob": blob.relative_to(state).as_posix(),
                }
            )
        # Check sources again after staging, before making the transaction durable.
        for path, expected in guards.items():
            if digest(path) != expected:
                raise MaterialConflictError(f"Ingestion input changed while staging: {path}")
        output_paths = {output.path for output in outputs}
        sources = {output.data for output in outputs if isinstance(output.data, Path)}
        stable = {}
        for p, h in guards.items():
            if p in output_paths or p in sources:
                continue
            name = _inside(root, p)
            if name is not None:
                stable[name] = h
        journal = {
            "version": 1,
            "outputs": items,
            "guards": stable,
            "report": report,
            "remove_sources": remove_sources or [],
        }
        sync_directory(payloads)
        _atomic_write_bytes(journal_path, json_bytes(journal), state)
        return _install(root, state, journal)
