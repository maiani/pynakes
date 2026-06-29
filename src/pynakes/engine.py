"""In-process engine facade for bibliography operations.

``Bibliography`` wraps one :class:`~pynakes.model.BibFile`, remembers the pristine
file text it was opened from, stages edits in memory, and can preview, diff, or
commit those staged edits. Entry edits use the same surgical splice strategy as
the CLI so unchanged entries stay byte-stable where possible.

Operation methods (field edits, key ops, normalization, import, …) live in
:mod:`pynakes._engine_ops`; low-level text helpers live in
:mod:`pynakes._engine_helpers`. Both are implementation details; import only
from this module.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pynakes import importer as importer_ops
from pynakes import metadata as metadata_ops
from pynakes._engine_helpers import (
    CommitResult,
    ExternalModificationError,
    FileFingerprint,
    append_entry_text,
    compute_change_plan,
    fingerprint,
    insert_metadata_comment,
    iter_changed_entries,
    read_text,
    snapshot_entries,
)
from pynakes._engine_ops import BibliographyOperations
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.diff import generate_diff
from pynakes.editing import splice_into_text
from pynakes.filestore import FileStore, PinaxRenameTransaction
from pynakes.io import load_bib, save_text
from pynakes.model import BibEntry, BibFile, EntryStore

QueryFilter = Callable[[BibEntry], bool] | None

# Re-export so ``from pynakes.engine import CommitResult, ExternalModificationError`` works.
__all__ = [
    "Bibliography",
    "CommitResult",
    "ExternalModificationError",
    "FileFingerprint",
    "QueryFilter",
]


@dataclass
class Bibliography(BibliographyOperations):
    """One in-memory bibliography.

    A bibliography is a *derived editing buffer*, not a second source of truth. It
    may be bound to a path via :meth:`open`, or constructed from already-loaded
    text/library data. Operation methods stage changes in the contained
    ``BibFile`` and return the underlying operation reports/counts.

    ``preview`` and ``diff`` expose the staged state without I/O. ``commit``
    performs the atomic, validated write and refuses to overwrite an externally
    changed bound file unless explicitly forced. ``reset`` and ``reload``
    discard the buffer and restore the file-derived state.
    """

    lib: BibFile
    path: Path | None = None
    _dirty: bool = False
    _pristine_text: str = ""
    _entry_snapshot: dict[int, str | None] = field(default_factory=dict)
    _fingerprint: FileFingerprint | None = None
    _appended_entries: list[BibEntry] = field(default_factory=list)
    _removed_entries: list[BibEntry] = field(default_factory=list)
    _text_replacements: list[tuple[str | None, str]] = field(default_factory=list)
    _consolidate_metadata: bool = False
    _pinax_renames: list[tuple[str, str]] = field(default_factory=list)
    _pinax_material_merges: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def open(cls, path: str | Path) -> "Bibliography":
        """Load a `.bib` file into a bibliography."""
        bound_path = Path(path)
        lib = load_bib(str(bound_path))
        pristine_text = read_text(bound_path, lib.encoding)
        coll = cls(
            lib,
            bound_path,
            _pristine_text=pristine_text,
            _entry_snapshot=snapshot_entries(lib),
            _fingerprint=fingerprint(bound_path),
        )
        FileStore.from_metadata(coll.lib, bound_path)
        return coll

    @classmethod
    def from_text(cls, text: str, path: str | Path | None = None) -> "Bibliography":
        """Create a bibliography from BibTeX text."""
        lib = parse_bib(text)
        coll = cls(
            lib,
            Path(path) if path is not None else None,
            _pristine_text=text,
            _entry_snapshot=snapshot_entries(lib),
        )
        if coll.path is not None:
            FileStore.from_metadata(coll.lib, coll.path)
        return coll

    @classmethod
    def from_bibfile(cls, lib: BibFile, path: str | Path | None = None) -> "Bibliography":
        """Wrap an existing library without copying it."""
        text = write_bib(lib)
        coll = cls(
            lib,
            Path(path) if path is not None else None,
            _pristine_text=text,
            _entry_snapshot=snapshot_entries(lib),
        )
        if coll.path is not None:
            FileStore.from_metadata(coll.lib, coll.path)
        return coll

    @property
    def entries(self) -> EntryStore:
        """Return the duplicate-preserving entry store."""
        return self.lib.entries

    @property
    def is_dirty(self) -> bool:
        """Return whether an engine operation changed the in-memory library."""
        return self._dirty

    @property
    def is_modified(self) -> bool:
        """Return whether staged output differs from the pristine text."""
        return self.preview() != self._pristine_text

    @property
    def files(self) -> FileStore | None:
        """Return the Pinax file store when ``files-dir`` metadata is configured."""
        if self.path is None:
            return None
        return FileStore.from_metadata(self.lib, self.path)

    def _mark(self, changed: int | bool) -> None:
        if changed:
            self._dirty = True

    def mark_dirty(self, changed: int | bool = True) -> None:
        """Mark the bibliography dirty after a caller mutates ``lib`` directly."""
        self._mark(changed)

    # --- lifecycle -------------------------------------------------------

    def preview(self) -> str:
        """Render staged edits without writing them."""
        return self._render_text()

    def diff(self) -> str:
        """Return a unified diff for staged edits."""
        new_text = self.preview()
        if new_text == self._pristine_text:
            return ""
        return generate_diff(self._pristine_text, new_text, self._file_name())

    def changed_entries_count(self) -> int:
        """Return how many entries have staged content changes."""
        entry_edits = self._entry_edits()
        changed = len(entry_edits) if entry_edits is not None else self._changed_entry_count()
        return changed + len(self._appended_entries) + len(self._removed_entries)

    def change_plan(self) -> dict:
        """Return a structured, machine-readable summary of the staged changes.

        Compares the pristine library against the staged one by citation key and
        reports entries ``added``, ``removed``, ``renamed`` (a removed key whose
        record reappears under a new key), or ``modified`` (with per-field and
        entry-type ``old``/``new`` values), plus top-level metadata key changes
        and a rollup ``summary``. This complements the textual :meth:`diff` with
        something an agent can reason over directly. Must be read **before**
        :meth:`commit` (a commit refreshes the pristine baseline). Duplicate
        citation keys are compared best-effort.
        """
        return compute_change_plan(self._pristine_text, self.lib)

    def externally_changed(self) -> bool:
        """Return whether the bound file changed since open/commit."""
        if self.path is None or self._fingerprint is None:
            return False
        return fingerprint(self.path) != self._fingerprint

    def commit(self, *, force: bool = False, backup: bool = False) -> CommitResult:
        """Write staged edits to the bound file and refresh the collection snapshot.

        Writes are atomic and re-parse-validated, so a ``.bak`` is opt-in:
        pass ``backup=True`` to also leave a ``<file>.bak`` copy behind.
        """
        if self.path is None:
            raise ValueError("commit requires a bound path")
        if (
            not force
            and self._fingerprint is not None
            and fingerprint(self.path) != self._fingerprint
        ):
            raise ExternalModificationError(self.path)

        changed_entries = self.changed_entries_count()
        diff_text = self.diff()
        new_text = self.preview()
        modified = new_text != self._pristine_text
        transactions: list[PinaxRenameTransaction] = []
        try:
            transactions = self._apply_pinax_renames()
            transactions.extend(self._apply_pinax_material_merges())
            if modified:
                result = save_text(
                    new_text, str(self.path), encoding=self.lib.encoding, backup=backup
                )
                if not result.success:
                    raise OSError(result.error or f"Could not write {self.path}")
        except Exception:
            for transaction in reversed(transactions):
                transaction.rollback()
            raise
        self._refresh_from_text(new_text, fingerprint=fingerprint(self.path))
        return CommitResult(changed_entries, diff_text, modified)

    def _clear_staged_edits(self) -> None:
        self._appended_entries.clear()
        self._removed_entries.clear()
        self._text_replacements.clear()
        self._pinax_renames.clear()
        self._pinax_material_merges.clear()
        self._consolidate_metadata = False
        self._dirty = False

    def reset(self) -> None:
        """Discard staged edits and restore the pristine in-memory library."""
        encoding = self.lib.encoding
        self.lib = parse_bib(self._pristine_text)
        self.lib.encoding = encoding
        self._entry_snapshot = snapshot_entries(self.lib)
        self._clear_staged_edits()

    def reload(self, *, force: bool = False) -> None:
        """Reload the bound file from disk, optionally discarding staged edits."""
        if self.path is None:
            raise ValueError("reload requires a bound path")
        if self._dirty and not force:
            raise ValueError("cannot reload a dirty bibliography without force=True")
        lib = load_bib(str(self.path))
        FileStore.from_metadata(lib, self.path)
        self.lib = lib
        self._pristine_text = read_text(self.path, self.lib.encoding)
        self._entry_snapshot = snapshot_entries(self.lib)
        self._fingerprint = fingerprint(self.path)
        self._clear_staged_edits()

    def _refresh_from_text(self, text: str, fingerprint: FileFingerprint | None = None) -> None:
        encoding = self.lib.encoding
        self.lib = parse_bib(text)
        self.lib.encoding = encoding
        self._pristine_text = text
        self._entry_snapshot = snapshot_entries(self.lib)
        self._fingerprint = fingerprint
        self._clear_staged_edits()

    def _iter_changed_entries(self):
        """Yield ``(entry, before, missing)`` for every non-appended entry.

        Delegates to the module-level :func:`~pynakes._engine_helpers.iter_changed_entries`
        helper, passing the current appended-entry id set.
        """
        appended_ids = {id(e) for e in self._appended_entries}
        yield from iter_changed_entries(
            list(self.lib.entries.values()), self._entry_snapshot, appended_ids
        )

    def _entry_edits(self) -> list[tuple[str, str]] | None:
        """Return surgical entry edits, or ``None`` when a full rewrite is needed."""
        edits: list[tuple[str, str]] = []
        for entry, before, missing in self._iter_changed_entries():
            if missing:
                return None
            if before is None:
                continue
            if entry.raw_content is None:
                return None
            if entry.raw_content != before:
                edits.append((before, entry.raw_content))
        return edits

    def _render_text(self) -> str:
        text = self._render_entry_text()
        if self._consolidate_metadata:
            text = metadata_ops.consolidate_metadata(self.lib, text, self.lib.line_ending) or text
        return text

    def _render_entry_text(self) -> str:
        text = self._apply_text_replacements(self._pristine_text)
        if text is None:
            return write_bib(self.lib)
        edits = self._entry_edits()
        if edits is None:
            return write_bib(self.lib)
        if edits:
            spliced = splice_into_text(text, edits)
            if spliced is None:
                return write_bib(self.lib)
            text = spliced

        for entry in self._appended_entries:
            text = append_entry_text(
                text,
                importer_ops.render_entry(entry, self.lib.line_ending),
                self.lib.line_ending,
                self.lib.metadata_blocks,
            )
        return text

    def _apply_text_replacements(self, text: str) -> str | None:
        for old, new in self._text_replacements:
            if old is None:
                text = insert_metadata_comment(text, new, self.lib.line_ending)
            elif old in text:
                text = text.replace(old, new, 1)
            else:
                return None
        return text

    def _changed_entry_count(self) -> int:
        count = 0
        for entry, before, missing in self._iter_changed_entries():
            if missing:
                count += 1
            elif entry.raw_content != before:
                count += 1
        return count

    def _stage_pinax_renames(self, renames: list[tuple[str, str]]) -> None:
        if not renames or self.files is None:
            return
        current_keys = set(self.lib.entries.keys())
        for old, new in renames:
            if old == new or old in current_keys:
                continue
            self._pinax_renames.append((old, new))

    def _apply_pinax_renames(self) -> list[PinaxRenameTransaction]:
        if not self._pinax_renames:
            return []
        store = self.files
        if store is None:
            return []
        transactions: list[PinaxRenameTransaction] = []
        for old, new in self._pinax_renames:
            transactions.append(store.rename_materials(old, new))
        return transactions

    def _stage_pinax_material_merges(self, merges: list[tuple[str, str]]) -> None:
        if not merges or self.files is None:
            return
        self._pinax_material_merges.extend((old, new) for old, new in merges if old != new)

    def _apply_pinax_material_merges(self) -> list[PinaxRenameTransaction]:
        if not self._pinax_material_merges:
            return []
        store = self.files
        if store is None:
            return []
        transactions: list[PinaxRenameTransaction] = []
        for old, new in self._pinax_material_merges:
            transactions.append(store.merge_materials(old, new))
        return transactions

    def _file_name(self) -> str:
        return self.path.name if self.path is not None else "bibliography.bib"
