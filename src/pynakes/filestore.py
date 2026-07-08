"""Pinax material storage addressed by citation key.

This module is deliberately filesystem-only: it computes deterministic material
paths from citation keys, scans for existing files, and performs atomic material
writes. It does not fetch or parse remote content.
"""

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pynakes._text_utils import strip_jabref_terminator
from pynakes.metadata import metadata_value
from pynakes.model import BibEntry, BibFile

FILES_DIR_KEY = "files-dir"
PUBLISHED_SUFFIX = ".published"
PREPRINT_SUFFIX = ".preprint"
SOURCE_SUFFIX = ".source"
SUPPLEMENT_SUFFIX = ".supplement"
ERRATUM_SUFFIX = ".erratum"
MANIFEST_DIR = ".pinax"
MANIFEST_FILE = "manifest.json"
MANIFEST_VERSION = 1
ARTIFACT_KINDS = (
    "published_pdf",
    "preprint_pdf",
    "preprint_source",
    "supplement_pdf",
    "erratum_pdf",
)
_FILESYSTEM_ERRORS = (OSError, shutil.Error)


@dataclass(frozen=True)
class MaterialPaths:
    """Deterministic material paths for one citation key."""

    key: str
    published_pdf: Path
    preprint_pdf: Path
    preprint_source: Path
    supplement_pdf: Path
    erratum_pdf: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "published_pdf": str(self.published_pdf),
            "preprint_pdf": str(self.preprint_pdf),
            "preprint_source": str(self.preprint_source),
            "supplement_pdf": str(self.supplement_pdf),
            "erratum_pdf": str(self.erratum_pdf),
        }


@dataclass(frozen=True)
class MaterialPresence:
    """Filesystem presence for one entry's deterministic material paths."""

    key: str
    paths: MaterialPaths
    published_pdf: bool
    preprint_pdf: bool
    preprint_source: bool
    supplement_pdf: bool
    erratum_pdf: bool

    @property
    def any_present(self) -> bool:
        return (
            self.published_pdf
            or self.preprint_pdf
            or self.preprint_source
            or self.supplement_pdf
            or self.erratum_pdf
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "paths": self.paths.to_dict(),
            "published_pdf": self.published_pdf,
            "preprint_pdf": self.preprint_pdf,
            "preprint_source": self.preprint_source,
            "supplement_pdf": self.supplement_pdf,
            "erratum_pdf": self.erratum_pdf,
            "any_present": self.any_present,
        }


@dataclass(frozen=True)
class OrphanMaterial:
    """One material-shaped path in ``files-dir`` whose key is not in the library."""

    key: str
    kind: str
    path: Path

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "kind": self.kind, "path": str(self.path)}


@dataclass(frozen=True)
class FileStoreScan:
    """Result of scanning a pinax files directory against known citation keys."""

    root: Path
    entries: list[MaterialPresence] = field(default_factory=list)
    orphans: list[OrphanMaterial] = field(default_factory=list)
    drift: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "entries": [entry.to_dict() for entry in self.entries],
            "orphans": [orphan.to_dict() for orphan in self.orphans],
            "drift": list(self.drift),
        }


@dataclass
class PinaxRenameTransaction:
    """Rollback handle for one in-place Pinax material rename."""

    store: "FileStore"
    moved: list[tuple[Path, Path]]
    original_manifest: dict[str, object] | None
    manifest_existed: bool

    def rollback(self) -> None:
        """Best-effort rollback of filesystem moves and manifest edits."""
        for old, new in reversed(self.moved):
            if new.exists() and not old.exists():
                new.replace(old)
        if self.original_manifest is not None:
            self.store.write_manifest(self.original_manifest)
        elif not self.manifest_existed:
            self.store.manifest_path.unlink(missing_ok=True)
            try:
                self.store.manifest_path.parent.rmdir()
            except OSError:
                pass


@dataclass(frozen=True)
class FileStore:
    """Deterministic Pinax files directory for one bibliography."""

    root: Path
    bib_path: Path

    @classmethod
    def from_metadata(cls, lib: BibFile, bib_path: str | Path) -> "FileStore | None":
        """Return the configured file store, or ``None`` when no ``files-dir`` is set."""
        value = metadata_value(lib, FILES_DIR_KEY)
        if value is None:
            return None
        path = resolve_files_dir(value, bib_path)
        return cls(root=path, bib_path=_absolute_bib_path(bib_path))

    def paths_for(self, key: str) -> MaterialPaths:
        """Return deterministic material paths for ``key``."""
        key = _validate_key(key)
        return MaterialPaths(
            key=key,
            published_pdf=self.root / f"{key}{PUBLISHED_SUFFIX}.pdf",
            preprint_pdf=self.root / f"{key}{PREPRINT_SUFFIX}.pdf",
            preprint_source=self.root / f"{key}{SOURCE_SUFFIX}",
            supplement_pdf=self.root / f"{key}{SUPPLEMENT_SUFFIX}.pdf",
            erratum_pdf=self.root / f"{key}{ERRATUM_SUFFIX}.pdf",
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
            supplement_pdf=paths.supplement_pdf.is_file(),
            erratum_pdf=paths.erratum_pdf.is_file(),
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

    def write_published_pdf(self, key: str, data: bytes) -> Path:
        """Atomically write the published (version-of-record) PDF for ``key``."""
        path = self.paths_for(key).published_pdf
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

    def write_supplement_pdf(self, key: str, data: bytes) -> Path:
        """Atomically write the supplementary-material PDF for ``key``."""
        path = self.paths_for(key).supplement_pdf
        self.ensure_root()
        _atomic_write_bytes(path, data, self.root)
        return path

    def write_erratum_pdf(self, key: str, data: bytes) -> Path:
        """Atomically write the erratum/corrected PDF for ``key``."""
        path = self.paths_for(key).erratum_pdf
        self.ensure_root()
        _atomic_write_bytes(path, data, self.root)
        return path

    @property
    def manifest_path(self) -> Path:
        """Return the Pinax provenance manifest path."""
        return self.root / MANIFEST_DIR / MANIFEST_FILE

    def read_manifest(self) -> dict[str, object]:
        """Read the provenance manifest, returning an empty v1 manifest if absent."""
        path = self.manifest_path
        if not path.is_file():
            return {"version": MANIFEST_VERSION, "files": {}}
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
            raise ValueError(f"Unsupported Pinax manifest format: {path}")
        files = data.get("files")
        if not isinstance(files, dict):
            raise ValueError(f"Invalid Pinax manifest: {path}")
        return data

    def write_manifest(self, manifest: dict[str, object], *, backup: bool = False) -> None:
        """Atomically write a provenance manifest."""
        manifest = _normalized_manifest(manifest)
        target = self.manifest_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup and target.exists():
            shutil.copy2(target, Path(str(target) + ".bak"))
        text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        _atomic_write_bytes(target, text.encode("utf-8"), target.parent)

    def preprint_canonical(self, key: str) -> bool:
        """Return whether ``key`` selects preprint material as canonical."""
        row = _manifest_row(self.read_manifest(), key, create=False)
        return bool(row.get("preprint_canonical", False)) if row is not None else False

    def set_preprint_canonical(self, key: str, value: bool) -> None:
        """Set the per-entry canonical preprint flag in the manifest."""
        manifest = self.read_manifest()
        row = _manifest_row(manifest, key, create=True)
        row["preprint_canonical"] = bool(value)
        self.write_manifest(manifest)

    def record_artifact(
        self,
        key: str,
        kind: str,
        *,
        source: str,
        refetchable: bool,
        fetched_date: str | None = None,
        added_date: str | None = None,
    ) -> None:
        """Record provenance for one material artifact."""
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"Unknown Pinax artifact kind: {kind}")
        if fetched_date is None and added_date is None:
            fetched_date = date.today().isoformat()
        path = getattr(self.paths_for(key), kind)
        record = {
            "source": source,
            "sha256": _sha256_path(path),
            "refetchable": bool(refetchable),
        }
        if fetched_date is not None:
            record["fetched_date"] = fetched_date
        if added_date is not None:
            record["added_date"] = added_date
        manifest = self.read_manifest()
        row = _manifest_row(manifest, key, create=True)
        row.setdefault("preprint_canonical", False)
        row[kind] = record
        self.write_manifest(manifest)

    def annotation_for(self, key: str, *, refetchable: bool = False) -> dict[str, object]:
        """Return agent-facing material paths and canonical selection for ``key``."""
        presence = self.presence_for(key)
        preprint_canonical = self.preprint_canonical(key)

        published_pdf = presence.paths.published_pdf if presence.published_pdf else None
        preprint_pdf = presence.paths.preprint_pdf if presence.preprint_pdf else None
        preprint_source = presence.paths.preprint_source if presence.preprint_source else None
        supplement_pdf = presence.paths.supplement_pdf if presence.supplement_pdf else None
        erratum_pdf = presence.paths.erratum_pdf if presence.erratum_pdf else None

        canonical_pdf: Path | None
        canonical_source: Path | None = None
        if preprint_canonical:
            canonical_pdf = preprint_pdf or published_pdf
            canonical_source = preprint_source if preprint_pdf is not None else None
        else:
            canonical_pdf = published_pdf or preprint_pdf
            if published_pdf is None and preprint_pdf is not None:
                canonical_source = preprint_source

        return {
            "published_pdf": _path_or_none(published_pdf),
            "preprint_pdf": _path_or_none(preprint_pdf),
            "preprint_source": _path_or_none(preprint_source),
            "supplement_pdf": _path_or_none(supplement_pdf),
            "erratum_pdf": _path_or_none(erratum_pdf),
            "canonical_pdf": _path_or_none(canonical_pdf),
            "canonical_source": _path_or_none(canonical_source),
            "preprint_canonical": preprint_canonical,
            "refetchable": bool(refetchable or _manifest_refetchable(self.read_manifest(), key)),
        }

    def copy_materials_from(self, source: "FileStore", key: str) -> list[dict[str, str]]:
        """Copy one entry's material files and manifest row from ``source``.

        The root directory is created lazily, only once a matching file or
        directory is actually found — an entry with no materials never
        touches the target filesystem, so routing it at a destination that
        can't hold a ``.files`` directory (e.g. a ``/dev/null`` discard
        bucket) doesn't fail.
        """
        copied: list[dict[str, str]] = []
        source_paths = source.paths_for(key)
        target_paths = self.paths_for(key)
        for kind in ARTIFACT_KINDS:
            src = getattr(source_paths, kind)
            dst = getattr(target_paths, kind)
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied.append({"key": key, "kind": kind, "path": str(dst)})
            elif src.is_dir():
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                copied.append({"key": key, "kind": kind, "path": str(dst)})
        _copy_manifest_row(source, self, key)
        return copied

    def plan_material_merge(self, old: str, new: str) -> list[dict[str, str]]:
        """Return planned in-place material moves from ``old`` onto ``new``.

        The merge is conservative: a source material kind may move only when the
        surviving key has no file/directory and no manifest record for that kind.
        """
        old = _validate_key(old)
        new = _validate_key(new)
        if old == new:
            return []

        planned: list[dict[str, str]] = []
        old_paths = self.paths_for(old)
        new_paths = self.paths_for(new)
        for kind in ARTIFACT_KINDS:
            src = getattr(old_paths, kind)
            dst = getattr(new_paths, kind)
            if not _material_exists(src, kind):
                continue
            if dst.exists():
                raise ValueError(f"Cannot merge Pinax material {src}: target exists: {dst}")
            planned.append(
                {
                    "source_key": old,
                    "target_key": new,
                    "kind": kind,
                    "source_path": str(src),
                    "target_path": str(dst),
                }
            )

        if self.manifest_path.exists():
            self._validate_manifest_row_merge(old, new, {item["kind"] for item in planned})
        return planned

    def merge_materials(self, old: str, new: str) -> PinaxRenameTransaction:
        """Move one duplicate key's materials and provenance onto ``new``."""
        old = _validate_key(old)
        new = _validate_key(new)
        transaction = PinaxRenameTransaction(
            store=self,
            moved=[],
            original_manifest=self.read_manifest() if self.manifest_path.exists() else None,
            manifest_existed=self.manifest_path.exists(),
        )
        if old == new:
            return transaction

        plan = self.plan_material_merge(old, new)
        try:
            for item in plan:
                src = Path(item["source_path"])
                dst = Path(item["target_path"])
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dst)
                transaction.moved.append((src, dst))
            self._merge_manifest_row(old, new, {item["kind"] for item in plan})
        except Exception:
            transaction.rollback()
            raise
        return transaction

    def fix_drift(
        self, keys: Iterable[str], *, added_date: str | None = None, backup: bool = False
    ) -> list[dict[str, str]]:
        """Reconcile manifest drift against live material files."""
        key_list = _unique_keys(keys)
        known = set(key_list)
        manifest = self.read_manifest()
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError("Pinax manifest 'files' must be a dict")
        fixed: list[dict[str, str]] = []

        for key in list(files):
            if key not in known:
                del files[key]
                fixed.append({"key": key, "kind": "manifest", "action": "removed_orphan_row"})
                continue
            row = files.get(key)
            if not isinstance(row, dict):
                del files[key]
                fixed.append({"key": key, "kind": "manifest", "action": "removed_invalid_row"})
                continue
            paths = self.paths_for(key)
            for kind in ARTIFACT_KINDS:
                if kind not in row:
                    continue
                material = getattr(paths, kind)
                exists = material.is_dir() if kind == "preprint_source" else material.is_file()
                if not exists:
                    del row[kind]
                    fixed.append({"key": key, "kind": kind, "action": "removed_missing_file"})
            if not any(kind in row for kind in ARTIFACT_KINDS) and not row.get(
                "preprint_canonical", False
            ):
                del files[key]

        for key in key_list:
            presence = self.presence_for(key)
            row_existed = key in files
            row = files.setdefault(key, {})
            if not isinstance(row, dict):
                row = {}
                files[key] = row
            for kind in ARTIFACT_KINDS:
                present = bool(getattr(presence, kind))
                if present and kind not in row:
                    path = getattr(presence.paths, kind)
                    row[kind] = {
                        "source": "manual",
                        "added_date": added_date or date.today().isoformat(),
                        "sha256": _sha256_path(path),
                        "refetchable": False,
                    }
                    fixed.append({"key": key, "kind": kind, "action": "added_manual_record"})
            if (
                not row_existed
                and not any(kind in row for kind in ARTIFACT_KINDS)
                and not row.get("preprint_canonical", False)
            ):
                del files[key]

        self.write_manifest(manifest, backup=backup)
        return fixed

    def rename_materials(self, old: str, new: str) -> PinaxRenameTransaction:
        """Move one key's materials and manifest row in place."""
        old = _validate_key(old)
        new = _validate_key(new)
        transaction = PinaxRenameTransaction(
            store=self,
            moved=[],
            original_manifest=self.read_manifest() if self.manifest_path.exists() else None,
            manifest_existed=self.manifest_path.exists(),
        )
        if old == new:
            return transaction

        old_paths = self.paths_for(old)
        new_paths = self.paths_for(new)
        planned: list[tuple[Path, Path]] = []
        for kind in ARTIFACT_KINDS:
            src = getattr(old_paths, kind)
            dst = getattr(new_paths, kind)
            if not src.exists():
                continue
            if dst.exists():
                raise ValueError(f"Cannot move Pinax material {src}: target exists: {dst}")
            planned.append((src, dst))

        try:
            for src, dst in planned:
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dst)
                transaction.moved.append((src, dst))
            self._rename_manifest_row(old, new)
        except Exception:
            transaction.rollback()
            raise
        return transaction

    def _materials_paths_for(self, key: str) -> list[str]:
        """Return relative paths that *would* be removed for *key* (no-op)."""
        if not self.root.is_dir():
            return []
        paths = self.paths_for(key)
        removed: list[str] = []
        for path in [
            paths.published_pdf,
            paths.preprint_pdf,
            paths.supplement_pdf,
            paths.erratum_pdf,
        ]:
            if path.exists():
                removed.append(str(path.relative_to(self.root)))
        if paths.preprint_source.is_dir():
            removed.append(str(paths.preprint_source.relative_to(self.root)))
        return removed

    def remove_materials(self, key: str) -> list[str]:
        """Remove all disk materials and manifest row for ``key``.

        Returns a list of relative paths that were removed (empty when nothing
        existed). Does nothing when the store root does not exist.
        """
        key = _validate_key(key)
        if not self.root.is_dir():
            return []
        paths = self.paths_for(key)
        removed: list[str] = []
        for path in [
            paths.published_pdf,
            paths.preprint_pdf,
            paths.supplement_pdf,
            paths.erratum_pdf,
        ]:
            if path.exists():
                path.unlink()
                removed.append(str(path.relative_to(self.root)))
        if paths.preprint_source.is_dir():
            shutil.rmtree(paths.preprint_source)
            removed.append(str(paths.preprint_source.relative_to(self.root)))
        if self.manifest_path.exists():
            manifest = self.read_manifest()
            files: dict = manifest.get("files", {})
            if key in files:
                del files[key]
                manifest["files"] = files
                self.write_manifest(manifest)
        return removed

    def scan(self, keys: Iterable[str]) -> FileStoreScan:
        """Scan this store for known-key presence and material-shaped orphans.

        Duplicate keys are rejected because a citation key is the address of its
        materials in Pinax mode.
        """
        key_list = _unique_keys(keys)
        known = set(key_list)
        entries = [self.presence_for(key) for key in key_list]
        return FileStoreScan(
            root=self.root,
            entries=entries,
            orphans=self._orphans(known),
            drift=self._manifest_drift(known),
        )

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

    def _manifest_drift(self, known: set[str]) -> list[dict[str, str]]:
        path = self.manifest_path
        if not path.exists():
            return []
        manifest = self.read_manifest()
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError("Pinax manifest 'files' must be a dict")
        drift: list[dict[str, str]] = []
        for key, row in sorted(files.items()):
            if key not in known:
                drift.append({"key": key, "kind": "manifest", "reason": "manifest key not in bib"})
                continue
            if not isinstance(row, dict):
                drift.append({"key": key, "kind": "manifest", "reason": "invalid manifest row"})
                continue
            paths = self.paths_for(key)
            for kind in ARTIFACT_KINDS:
                if kind not in row:
                    continue
                material = getattr(paths, kind)
                exists = material.is_dir() if kind == "preprint_source" else material.is_file()
                if not exists:
                    drift.append({"key": key, "kind": kind, "reason": "manifest without file"})
        for key in sorted(known):
            presence = self.presence_for(key)
            row = files.get(key, {})
            if not isinstance(row, dict):
                row = {}
            for kind in ARTIFACT_KINDS:
                present = bool(getattr(presence, kind))
                if present and kind not in row:
                    drift.append({"key": key, "kind": kind, "reason": "file without manifest"})
        return drift

    def _rename_manifest_row(self, old: str, new: str) -> None:
        if not self.manifest_path.exists():
            return
        manifest = self.read_manifest()
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError("Pinax manifest 'files' must be a dict")
        if old not in files:
            return
        if new in files:
            raise ValueError(f"Cannot move Pinax manifest row {old!r}: target key exists: {new!r}")
        files[new] = files.pop(old)
        self.write_manifest(manifest)

    def _validate_manifest_row_merge(self, old: str, new: str, moved_kinds: set[str]) -> None:
        manifest = self.read_manifest()
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError("Pinax manifest 'files' must be a dict")
        old_row = files.get(old)
        if not isinstance(old_row, dict):
            return
        new_row = files.get(new, {})
        if not isinstance(new_row, dict):
            raise ValueError(f"Cannot merge Pinax manifest row {old!r}: invalid target row {new!r}")
        for kind in ARTIFACT_KINDS:
            if kind in old_row and kind in new_row:
                raise ValueError(
                    f"Cannot merge Pinax manifest row {old!r}: target key {new!r} "
                    f"already has {kind}"
                )
        if moved_kinds and "preprint_canonical" in old_row and "preprint_canonical" in new_row:
            if bool(old_row["preprint_canonical"]) != bool(new_row["preprint_canonical"]):
                raise ValueError(
                    f"Cannot merge Pinax manifest row {old!r}: target key {new!r} "
                    "has conflicting preprint_canonical state"
                )

    def _merge_manifest_row(self, old: str, new: str, moved_kinds: set[str]) -> None:
        if not self.manifest_path.exists():
            return
        manifest = self.read_manifest()
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError("Pinax manifest 'files' must be a dict")
        old_row = files.get(old)
        if not isinstance(old_row, dict):
            files.pop(old, None)
            self.write_manifest(manifest)
            return
        new_row = files.setdefault(new, {})
        if not isinstance(new_row, dict):
            raise ValueError(f"Cannot merge Pinax manifest row {old!r}: invalid target row {new!r}")
        for kind in moved_kinds:
            if kind in old_row:
                new_row[kind] = old_row[kind]
        if moved_kinds and "preprint_canonical" in old_row:
            new_row.setdefault("preprint_canonical", bool(old_row["preprint_canonical"]))
        files.pop(old, None)
        if not _manifest_row_has_state(new_row):
            files.pop(new, None)
        self.write_manifest(manifest)


def resolve_files_dir(value: str, bib_path: str | Path) -> Path:
    """Resolve and validate a ``files-dir`` metadata value.

    Empty values use the default ``<bib-stem>.files`` directory. Non-empty values
    must be relative to the bibliography directory and must not escape it. A
    symlinked bibliography is anchored at the link path the user supplied, not
    the link target.
    """
    bib = _absolute_bib_path(bib_path)
    base = bib.parent
    raw = strip_jabref_terminator(value)
    if not raw:
        return base / f"{bib.stem}.files"
    path = Path(raw).expanduser()
    if path.is_absolute():
        raise ValueError("files-dir must be a relative path inside the bibliography directory")
    resolved = Path(os.path.abspath(os.fspath(base / path)))
    if not resolved.is_relative_to(base):
        raise ValueError("files-dir must not escape the bibliography directory")
    return resolved


def _absolute_bib_path(path: str | Path) -> Path:
    bib = Path(path).expanduser()
    return Path(os.path.abspath(os.fspath(bib)))


def _normalized_manifest(manifest: dict[str, object]) -> dict[str, object]:
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("Pinax manifest files must be an object")
    normalized_files: dict[str, object] = {}
    for key, row in files.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            raise ValueError("Pinax manifest rows must be keyed objects")
        normalized_files[key] = dict(row)
    return {"version": MANIFEST_VERSION, "files": normalized_files}


def _manifest_row(
    manifest: dict[str, object], key: str, *, create: bool
) -> dict[str, object] | None:
    key = _validate_key(key)
    files = manifest.setdefault("files", {})
    if not isinstance(files, dict):
        raise ValueError("Pinax manifest files must be an object")
    row = files.get(key)
    if row is None:
        if not create:
            return None
        row = {}
        files[key] = row
    if not isinstance(row, dict):
        raise ValueError(f"Invalid Pinax manifest row for {key!r}")
    return row


def _manifest_refetchable(manifest: dict[str, object], key: str) -> bool:
    row = _manifest_row(manifest, key, create=False)
    if row is None:
        return False
    for kind in ARTIFACT_KINDS:
        record = row.get(kind)
        if isinstance(record, dict) and record.get("refetchable") is True:
            return True
    return False


def _material_exists(path: Path, kind: str) -> bool:
    return path.is_dir() if kind == "preprint_source" else path.is_file()


def _manifest_row_has_state(row: dict[str, object]) -> bool:
    return any(kind in row for kind in ARTIFACT_KINDS) or bool(row.get("preprint_canonical", False))


def _copy_manifest_row(source: FileStore, target: FileStore, key: str) -> None:
    source_row = _manifest_row(source.read_manifest(), key, create=False)
    if source_row is None:
        return
    target_manifest = target.read_manifest()
    files = target_manifest["files"]
    if not isinstance(files, dict):
        raise TypeError("Pinax manifest 'files' must be a dict")
    files[_validate_key(key)] = dict(source_row)
    target.write_manifest(target_manifest)


def _path_or_none(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _sha256_path(path: Path) -> str:
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if path.is_dir():
        return _sha256_dir(path)
    raise ValueError(f"Pinax artifact path does not exist: {path}")


def _sha256_dir(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_key(key: str) -> str:
    normalized = key.strip()
    if not normalized:
        raise ValueError("citation key must not be empty")
    if "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError(f"citation key {key!r} cannot address Pinax materials")
    return normalized


def _unique_keys(keys: Iterable[str]) -> list[str]:
    """Return a deduplicated list of validated keys; silently drops duplicates."""
    seen: set[str] = set()
    result: list[str] = []
    for key in keys:
        normalized = _validate_key(key)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _classify_material_path(path: Path) -> tuple[str, str] | None:
    name = path.name
    if path.is_dir() and name.endswith(SOURCE_SUFFIX):
        return name[: -len(SOURCE_SUFFIX)], "preprint_source"
    if not path.is_file() or path.suffix != ".pdf":
        return None
    stem = path.stem
    if stem.endswith(PREPRINT_SUFFIX):
        return stem[: -len(PREPRINT_SUFFIX)], "preprint_pdf"
    if stem.endswith(PUBLISHED_SUFFIX):
        return stem[: -len(PUBLISHED_SUFFIX)], "published_pdf"
    if stem.endswith(SUPPLEMENT_SUFFIX):
        return stem[: -len(SUPPLEMENT_SUFFIX)], "supplement_pdf"
    if stem.endswith(ERRATUM_SUFFIX):
        return stem[: -len(ERRATUM_SUFFIX)], "erratum_pdf"
    return None


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
    except _FILESYSTEM_ERRORS:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_replace_dir(source: Path, target: Path, root: Path) -> None:
    backup = root / f".{target.name}.old-{uuid.uuid4().hex}"
    had_target = target.exists()
    if had_target:
        target.replace(backup)
    try:
        source.replace(target)
    except _FILESYSTEM_ERRORS:
        if had_target and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    else:
        if had_target:
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink(missing_ok=True)
