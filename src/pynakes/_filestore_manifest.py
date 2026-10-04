"""The Pinax provenance manifest: ``.pinax/manifest.json`` and its upkeep.

What a pinax knows about each material beyond its presence on disk — where it
came from, when, its checksum, and whether it can be fetched again — kept per
citation key. :class:`PinaxManifest` is a mixin of
:class:`pynakes.filestore.FileStore`, which supplies the paths and atomic
writes it builds on.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Literal, overload

if TYPE_CHECKING:
    from pynakes.filestore import FileStore, MaterialPaths, MaterialPresence

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


class PinaxManifest:
    """Manifest operations for :class:`pynakes.filestore.FileStore`.

    Consumers must not instantiate this class directly.
    """

    if TYPE_CHECKING:
        root: Path

        def _require_real_bookkeeping(self) -> None: ...
        def _atomic_write(self, path: Path, data: bytes) -> None: ...
        def paths_for(self, key: str) -> MaterialPaths: ...
        def presence_for(self, key: str) -> MaterialPresence: ...

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
        self._require_real_bookkeeping()
        target = self.manifest_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup and target.exists():
            shutil.copy2(target, Path(str(target) + ".bak"))
        text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        self._atomic_write(target, text.encode("utf-8"))

    def record_artifact(
        self,
        key: str,
        kind: str,
        *,
        source: str,
        refetchable: bool,
        fetched_date: str | None = None,
        added_date: str | None = None,
        access: str | None = None,
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
        if access is not None:
            record["access"] = access
        manifest = self.read_manifest()
        row = _manifest_row(manifest, key, create=True)
        row[kind] = record
        self.write_manifest(manifest)

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
            if not _manifest_row_has_state(row):
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
            if not row_existed and not _manifest_row_has_state(row):
                del files[key]

        self.write_manifest(manifest, backup=backup)
        return fixed

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

    def _validate_manifest_row_merge(self, old: str, new: str) -> None:
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
        files.pop(old, None)
        if not _manifest_row_has_state(new_row):
            files.pop(new, None)
        self.write_manifest(manifest)


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


@overload
def _manifest_row(
    manifest: dict[str, object], key: str, *, create: Literal[True]
) -> dict[str, object]: ...


@overload
def _manifest_row(
    manifest: dict[str, object], key: str, *, create: bool
) -> dict[str, object] | None: ...


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


def _manifest_row_has_state(row: dict[str, object]) -> bool:
    return any(kind in row for kind in ARTIFACT_KINDS)


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
