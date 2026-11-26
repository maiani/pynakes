"""Durable roll-forward journal for native ingestion (not global atomicity).

Every output is staged and fsynced before the journal is published. Recovery
accepts only original or intended bytes, checks all targets before changing any,
and installs materials before manifests, bibliographies and finally receipts.
An external edit blocks recovery rather than being overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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


def contained(root: Path, path: Path) -> str:
    """Require a real, contained path, including currently absent parents."""
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError(f"Managed ingestion target is outside the Library root: {path}") from None
    if ".." in relative.parts:
        raise ValueError("Invalid ingestion target")
    for parent in (path, *path.parents):
        if parent == root.parent:
            break
        if parent.is_symlink():
            raise ValueError(f"Symlink in ingestion target: {parent}")
    return relative.as_posix()


@dataclass(frozen=True)
class Output:
    path: Path
    before: str | None
    data: bytes | Path


@contextmanager
def locked(state: Path) -> Generator[None, None, None]:
    """Serialize cooperating ingest/recover commands; reclaim dead-process locks."""
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "lock"
    try:
        stream = lock.open("x", encoding="ascii")
    except FileExistsError:
        try:
            pid = int(lock.read_text(encoding="ascii"))
        except (ValueError, OSError):
            raise ValueError(f"Unrecognised ingestion lock; inspect {lock}") from None
        if _process_alive(pid):
            raise ValueError("Another ingestion operation is running") from None
        lock.unlink()
        stream = lock.open("x", encoding="ascii")
    try:
        with stream:
            stream.write(str(os.getpid()))
            sync_file(stream)
        yield
    finally:
        lock.unlink(missing_ok=True)


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
    for item in journal.get("remove_sources", []):
        source = Path(item["path"])
        if not source.exists():
            continue
        if source.is_symlink() or digest(source) != item["sha256"]:
            raise MaterialConflictError(
                f"Stored material is committed; source changed, removal pending: {source}"
            )
        # Check the stored copy again immediately before retiring the source.
        target = root / item["target"]
        contained(root, target)
        if digest(target) != item["sha256"]:
            raise MaterialConflictError(f"Stored material changed; source retained: {source}")
        source.unlink()
        sync_directory(source.parent)
    result = journal["report"]
    (state / "journal.json").unlink()
    sync_directory(state)
    shutil.rmtree(state / "payloads", ignore_errors=True)
    return result


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
) -> dict:
    """Prepare all bytes and publish a replayable transaction before mutation."""
    contained(root, state)
    with locked(state):
        journal_path = state / "journal.json"
        if journal_path.exists():
            raise ValueError("Interrupted ingestion: run library recover before another import")
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
        stable = {
            contained(root, p): h
            for p, h in guards.items()
            if p not in output_paths and p not in sources and p.is_relative_to(root)
        }
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
