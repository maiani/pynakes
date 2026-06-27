"""Pinax material storage addressed by citation key.

This module is deliberately filesystem-only: it computes deterministic material
paths from citation keys, scans for existing files, and performs atomic material
writes. It does not fetch or parse remote content.
"""

import shutil
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pynakes.model import BibEntry, BibFile

FILES_DIR_KEY = "files-dir"
PREPRINT_SUFFIX = "_preprint"
MANIFEST_DIR = ".pinax"


@dataclass(frozen=True)
class MaterialPaths:
    """Deterministic material paths for one citation key."""

    key: str
    published_pdf: Path
    preprint_pdf: Path
    preprint_source: Path

    def to_dict(self) -> dict[str, str]:
        """Serialize paths to a JSON-friendly dict."""
        return {
            "key": self.key,
            "published_pdf": str(self.published_pdf),
            "preprint_pdf": str(self.preprint_pdf),
            "preprint_source": str(self.preprint_source),
        }


@dataclass(frozen=True)
class MaterialPresence:
    """Filesystem presence for one entry's deterministic material paths."""

    key: str
    paths: MaterialPaths
    published_pdf: bool
    preprint_pdf: bool
    preprint_source: bool

    @property
    def any_present(self) -> bool:
        """Return whether any material exists for this citation key."""
        return self.published_pdf or self.preprint_pdf or self.preprint_source

    def to_dict(self) -> dict[str, object]:
        """Serialize the presence record to a JSON-friendly dict."""
        return {
            "key": self.key,
            "paths": self.paths.to_dict(),
            "published_pdf": self.published_pdf,
            "preprint_pdf": self.preprint_pdf,
            "preprint_source": self.preprint_source,
            "any_present": self.any_present,
        }


@dataclass(frozen=True)
class OrphanMaterial:
    """One material-shaped path in ``files-dir`` whose key is not in the library."""

    key: str
    kind: str
    path: Path

    def to_dict(self) -> dict[str, str]:
        """Serialize the orphan record to a JSON-friendly dict."""
        return {"key": self.key, "kind": self.kind, "path": str(self.path)}


@dataclass(frozen=True)
class FileStoreScan:
    """Result of scanning a pinax files directory against known citation keys."""

    root: Path
    entries: list[MaterialPresence] = field(default_factory=list)
    orphans: list[OrphanMaterial] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Serialize the scan to a JSON-friendly dict."""
        return {
            "root": str(self.root),
            "entries": [entry.to_dict() for entry in self.entries],
            "orphans": [orphan.to_dict() for orphan in self.orphans],
        }


@dataclass(frozen=True)
class FileStore:
    """Deterministic Pinax files directory for one bibliography."""

    root: Path
    bib_path: Path

    @classmethod
    def from_metadata(cls, lib: BibFile, bib_path: str | Path) -> "FileStore | None":
        """Return the configured file store, or ``None`` when no ``files-dir`` is set."""
        value = _metadata_value(lib, FILES_DIR_KEY)
        if value is None:
            return None
        path = resolve_files_dir(value, bib_path)
        return cls(root=path, bib_path=_absolute_bib_path(bib_path))

    def paths_for(self, key: str) -> MaterialPaths:
        """Return deterministic material paths for ``key``."""
        key = _validate_key(key)
        return MaterialPaths(
            key=key,
            published_pdf=self.root / f"{key}.pdf",
            preprint_pdf=self.root / f"{key}{PREPRINT_SUFFIX}.pdf",
            preprint_source=self.root / f"{key}{PREPRINT_SUFFIX}",
        )

    def presence_for(self, key: str) -> MaterialPresence:
        """Return live filesystem presence for one citation key."""
        paths = self.paths_for(key)
        return MaterialPresence(
            key=key,
            paths=paths,
            published_pdf=paths.published_pdf.is_file(),
            preprint_pdf=paths.preprint_pdf.is_file(),
            preprint_source=paths.preprint_source.is_dir(),
        )

    def ensure_root(self) -> Path:
        """Create and return the files directory for this store."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def write_preprint_pdf(self, key: str, data: bytes) -> Path:
        """Atomically write the arXiv preprint PDF bytes for ``key``."""
        path = self.paths_for(key).preprint_pdf
        self.ensure_root()
        _atomic_write_bytes(path, data, self.root)
        return path

    def write_preprint_source(self, key: str, source_dir: str | Path) -> Path:
        """Atomically install an extracted arXiv source tree for ``key``."""
        source = Path(source_dir)
        if not source.is_dir():
            raise ValueError(f"source_dir is not a directory: {source}")
        target = self.paths_for(key).preprint_source
        self.ensure_root()
        _atomic_replace_dir(source, target, self.root)
        return target

    def scan(self, keys: Iterable[str]) -> FileStoreScan:
        """Scan this store for known-key presence and material-shaped orphans.

        Duplicate keys are rejected because a citation key is the address of its
        materials in Pinax mode.
        """
        key_list = _unique_keys(keys)
        known = set(key_list)
        entries = [self.presence_for(key) for key in key_list]
        return FileStoreScan(root=self.root, entries=entries, orphans=self._orphans(known))

    def scan_entries(self, entries: Iterable[BibEntry]) -> FileStoreScan:
        """Scan material presence for bibliography entries."""
        return self.scan(entry.key for entry in entries if entry.key.strip())

    def _orphans(self, known: set[str]) -> list[OrphanMaterial]:
        if not self.root.is_dir():
            return []
        orphans: list[OrphanMaterial] = []
        for path in sorted(self.root.iterdir(), key=lambda item: item.name):
            if path.name == MANIFEST_DIR:
                continue
            material = _classify_material_path(path)
            if material is None:
                continue
            key, kind = material
            if key not in known:
                orphans.append(OrphanMaterial(key=key, kind=kind, path=path))
        return orphans


def resolve_files_dir(value: str, bib_path: str | Path) -> Path:
    """Resolve and validate a ``files-dir`` metadata value.

    Empty values use the default ``<bib-stem>.files`` directory. Non-empty values
    must be relative to the bibliography directory and must not escape it.
    """
    bib = _absolute_bib_path(bib_path)
    base = bib.parent
    raw = value.strip().rstrip(";").strip()
    if not raw:
        return base / f"{bib.stem}.files"
    path = Path(raw).expanduser()
    if path.is_absolute():
        raise ValueError("files-dir must be a relative path inside the bibliography directory")
    resolved = (base / path).resolve(strict=False)
    if not resolved.is_relative_to(base):
        raise ValueError("files-dir must not escape the bibliography directory")
    return resolved


def _absolute_bib_path(path: str | Path) -> Path:
    bib = Path(path).expanduser()
    return bib if bib.is_absolute() else bib.resolve(strict=False)


def _metadata_value(lib: BibFile, key: str) -> str | None:
    for name, value in lib.metadata.items():
        if name.lower() == key:
            return value
    return None


def _validate_key(key: str) -> str:
    normalized = key.strip()
    if not normalized:
        raise ValueError("citation key must not be empty")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError(f"citation key {key!r} cannot address Pinax materials")
    return normalized


def _unique_keys(keys: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    duplicates: set[str] = set()
    for key in keys:
        normalized = _validate_key(key)
        if normalized in seen:
            duplicates.add(normalized)
            continue
        seen.add(normalized)
        result.append(normalized)
    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ValueError(f"Pinax material addressing requires unique citation keys: {joined}")
    return result


def _classify_material_path(path: Path) -> tuple[str, str] | None:
    name = path.name
    if path.is_dir() and name.endswith(PREPRINT_SUFFIX):
        return name[: -len(PREPRINT_SUFFIX)], "preprint_source"
    if not path.is_file() or path.suffix != ".pdf":
        return None
    stem = path.stem
    if stem.endswith(PREPRINT_SUFFIX):
        return stem[: -len(PREPRINT_SUFFIX)], "preprint_pdf"
    return stem, "published_pdf"


def _atomic_write_bytes(path: Path, data: bytes, root: Path) -> None:
    tmp = tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=root,
        delete=False,
    )
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            tmp.write(data)
            tmp.flush()
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_replace_dir(source: Path, target: Path, root: Path) -> None:
    backup = root / f".{target.name}.old-{uuid.uuid4().hex}"
    had_target = target.exists()
    if had_target:
        target.replace(backup)
    try:
        source.replace(target)
    except Exception:
        if had_target and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    else:
        if had_target:
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink(missing_ok=True)
