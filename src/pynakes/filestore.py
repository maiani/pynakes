"""Pinax material storage addressed by citation key.

This module is deliberately filesystem-only: it computes deterministic material
paths from citation keys, scans for existing files, and performs atomic material
writes. It does not fetch or parse remote content.
"""

import os
import shutil
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pynakes._filestore_atomic import (
    _atomic_replace_dir,
    _atomic_write_bytes,
    _process_alive,
    _remove_path,
)
from pynakes._filestore_manifest import (
    ARTIFACT_KINDS,
    MANIFEST_DIR,
    PinaxManifest,
    _copy_manifest_row,
    _manifest_refetchable,
    _unique_keys,
    _validate_key,
)
from pynakes._text_utils import strip_meta_terminator
from pynakes.metadata import metadata_value
from pynakes.model import BibEntry, BibFile

FILES_DIR_KEY = "pinax-files-dir"
PUBLISHED_SUFFIX = ".published"
PREPRINT_SUFFIX = ".preprint"
SOURCE_SUFFIX = ".source"
SUPPLEMENT_SUFFIX = ".supplement"
ERRATUM_SUFFIX = ".erratum"
# In-flight temporary files live under MANIFEST_DIR rather than beside the
# materials, so an interrupted write cannot litter the user's files directory.
TEMP_DIR = "tmp"


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
    """One material-shaped path in ``pinax-files-dir`` whose key is not in the library."""

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
class FileStore(PinaxManifest):
    """Deterministic Pinax files directory for one bibliography."""

    root: Path
    bib_path: Path

    @classmethod
    def from_metadata(cls, lib: BibFile, bib_path: str | Path) -> "FileStore | None":
        """Return the configured file store, or ``None`` when no ``pinax-files-dir`` is set."""
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

    @property
    def scratch_root(self) -> Path:
        """Return the directory that holds in-flight temporary files."""
        return self.root / MANIFEST_DIR / TEMP_DIR

    def _require_real_bookkeeping(self) -> None:
        """Refuse a store whose ``.pinax`` bookkeeping is reached through a symlink.

        Scratch sweeping deletes what it finds and the manifest is rewritten in
        place, so either one reached through a link — a committed
        ``.pinax/tmp -> ../../elsewhere``, say — would act on files outside the
        store.
        """
        for path in (self.root / MANIFEST_DIR, self.scratch_root):
            if path.is_symlink():
                raise OSError(f"Refusing to use {path}: it is a symbolic link")

    @contextmanager
    def scratch(self) -> Iterator[Path]:
        """Yield this process's scratch directory, releasing it when empty.

        Temporary files stage here instead of beside the materials, so a write
        interrupted by a signal leaves nothing in the files directory the user
        looks at. Scratch directories owned by processes that have since exited
        are swept on entry, which makes a killed run self-healing rather than
        permanently messy — nothing accumulates across runs.
        """
        root = self.scratch_root
        self._require_real_bookkeeping()
        root.mkdir(parents=True, exist_ok=True)
        self.sweep_scratch()
        mine = root / str(os.getpid())
        mine.mkdir(exist_ok=True)
        try:
            yield mine
        finally:
            self._release_scratch()

    def sweep_scratch(self) -> list[Path]:
        """Remove scratch directories belonging to processes that have exited.

        Concurrent pynakes processes each own a directory named for their pid,
        so sweeping never touches another live run's in-flight files. Anything
        not named like a pid was not put there by pynakes and is left alone.
        """
        self._require_real_bookkeeping()
        root = self.scratch_root
        if not root.is_dir():
            return []
        current = str(os.getpid())
        removed: list[Path] = []
        for item in sorted(root.iterdir(), key=lambda entry: entry.name):
            if item.name == current or not item.name.isdigit():
                continue
            if _process_alive(int(item.name)):
                continue
            _remove_path(item)
            removed.append(item)
        return removed

    def _release_scratch(self) -> None:
        """Drop this process's scratch directory, and its empty parents.

        Nested users (an extraction staging its tree inside the same directory)
        leave it non-empty, so ``rmdir`` refusing is the expected outcome and
        the outermost caller performs the actual cleanup.
        """
        for path in (
            self.scratch_root / str(os.getpid()),
            self.scratch_root,
            self.root / MANIFEST_DIR,
        ):
            try:
                path.rmdir()
            except OSError:
                return

    def _atomic_write(self, path: Path, data: bytes) -> None:
        """Write ``path`` atomically, staging through the contained scratch dir."""
        with self.scratch() as scratch:
            _atomic_write_bytes(path, data, scratch)

    def write_preprint_pdf(self, key: str, data: bytes) -> Path:
        """Atomically write the arXiv preprint PDF bytes for ``key``."""
        path = self.paths_for(key).preprint_pdf
        self.ensure_root()
        self._atomic_write(path, data)
        return path

    def write_published_pdf(self, key: str, data: bytes) -> Path:
        """Atomically write the published (version-of-record) PDF for ``key``."""
        path = self.paths_for(key).published_pdf
        self.ensure_root()
        self._atomic_write(path, data)
        return path

    def write_preprint_source(self, key: str, source_dir: str | Path) -> Path:
        """Atomically install an extracted arXiv source tree for ``key``."""
        source = Path(source_dir)
        if not source.is_dir():
            raise ValueError(f"source_dir is not a directory: {source}")
        target = self.paths_for(key).preprint_source
        self.ensure_root()
        with self.scratch() as scratch:
            _atomic_replace_dir(source, target, scratch)
        return target

    def write_supplement_pdf(self, key: str, data: bytes) -> Path:
        """Atomically write the supplementary-material PDF for ``key``."""
        path = self.paths_for(key).supplement_pdf
        self.ensure_root()
        self._atomic_write(path, data)
        return path

    def annotation_for(self, key: str, *, refetchable: bool = False) -> dict[str, object]:
        """Return agent-facing material paths and canonical selection for ``key``."""
        presence = self.presence_for(key)

        published_pdf = presence.paths.published_pdf if presence.published_pdf else None
        preprint_pdf = presence.paths.preprint_pdf if presence.preprint_pdf else None
        preprint_source = presence.paths.preprint_source if presence.preprint_source else None
        supplement_pdf = presence.paths.supplement_pdf if presence.supplement_pdf else None
        erratum_pdf = presence.paths.erratum_pdf if presence.erratum_pdf else None

        # The version of record is what to read when there is one; a preprint
        # stands in for it, bringing its source tree, only when there is not.
        canonical_pdf = published_pdf or preprint_pdf
        canonical_source = (
            preprint_source if published_pdf is None and preprint_pdf is not None else None
        )

        return {
            "published_pdf": _path_or_none(published_pdf),
            "preprint_pdf": _path_or_none(preprint_pdf),
            "preprint_source": _path_or_none(preprint_source),
            "supplement_pdf": _path_or_none(supplement_pdf),
            "erratum_pdf": _path_or_none(erratum_pdf),
            "canonical_pdf": _path_or_none(canonical_pdf),
            "canonical_source": _path_or_none(canonical_source),
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
            if src.resolve() == dst.resolve():
                # Source and target resolve to the same location (e.g. a combine
                # whose --out is also an input): the material is already in place.
                continue
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
            self._validate_manifest_row_merge(old, new)
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


def resolve_files_dir(value: str, bib_path: str | Path) -> Path:
    """Resolve and validate a ``pinax-files-dir`` metadata value.

    Empty values use the default ``<bib-stem>.files`` directory. Non-empty values
    must be relative to the bibliography directory and must not escape it. A
    symlinked bibliography is anchored at the link path the user supplied, not
    the link target.
    """
    bib = _absolute_bib_path(bib_path)
    base = bib.parent
    raw = strip_meta_terminator(value)
    if not raw:
        return base / f"{bib.stem}.files"
    path = Path(raw).expanduser()
    if path.is_absolute():
        raise ValueError(
            "pinax-files-dir must be a relative path inside the bibliography directory"
        )
    resolved = Path(os.path.abspath(os.fspath(base / path)))
    if not resolved.is_relative_to(base):
        raise ValueError("pinax-files-dir must not escape the bibliography directory")
    return resolved


def _absolute_bib_path(path: str | Path) -> Path:
    bib = Path(path).expanduser()
    return Path(os.path.abspath(os.fspath(bib)))


def _material_exists(path: Path, kind: str) -> bool:
    return path.is_dir() if kind == "preprint_source" else path.is_file()


def _path_or_none(path: Path | None) -> str | None:
    return str(path) if path is not None else None


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
