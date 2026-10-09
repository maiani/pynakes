"""In-process engine facade for bibliography operations.

``Bibliography`` wraps one :class:`~pynakes.model.BibFile`, remembers the pristine
file text it was opened from, stages edits in memory, and can preview, diff, or
commit those staged edits. Entry and metadata edits are applied to identity-aware
spans in the pristine source, so even byte-identical duplicate blocks remain
distinct and unchanged content stays byte-stable.

Operation methods (field edits, key ops, normalization, import, …) live in
:mod:`pynakes._engine_ops`; low-level text helpers live in
:mod:`pynakes._engine_helpers`. Both are implementation details; import only
from this module.
"""

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path

from pynakes import _tex_rewrite
from pynakes import metadata as metadata_ops
from pynakes._engine_directives import BibliographyDirectives
from pynakes._engine_groups import BibliographyGroups
from pynakes._engine_helpers import (
    CommitResult,
    ExternalModificationError,
    FileFingerprint,
    SourceSnapshot,
    SourceSpan,
    SpanEdit,
    append_entry_text,
    apply_span_edits,
    block_removal_span,
    compute_change_plan,
    fingerprint,
    insert_metadata_comment,
    iter_changed_entries,
    snapshot_entries,
    snapshot_source_spans,
)
from pynakes._engine_keys import BibliographyKeys
from pynakes._engine_ops import BibliographyOperations
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.canonical import CanonicalLayout, write_bib_canonical
from pynakes.diff import generate_diff
from pynakes.filestore import FileStore, PinaxRenameTransaction
from pynakes.io import _load_source, save_text
from pynakes.model import BibEntry, BibFile, EntryStore, QueryFilter

# Re-export so ``from pynakes.engine import CommitResult, ExternalModificationError`` works.
__all__ = [
    "Bibliography",
    "CommitResult",
    "ExternalModificationError",
    "FileFingerprint",
    "QueryFilter",
]


@dataclass
class Bibliography(
    BibliographyKeys, BibliographyGroups, BibliographyDirectives, BibliographyOperations
):
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
    _pristine_text: str = ""
    _entry_snapshot: dict[int, str | None] = field(default_factory=dict)
    _source_snapshot: SourceSnapshot = field(
        default_factory=lambda: SourceSnapshot({}, (), {}, False)
    )
    _fingerprint: FileFingerprint | None = None
    _appended_entries: list[BibEntry] = field(default_factory=list)
    _removed_entries: list[BibEntry] = field(default_factory=list)
    _consolidate_metadata: bool = False
    #: Comment slots a scrub blanked, removed from the source with their
    #: trailing gap so no empty block is left where they were.
    _removed_comments: set[int] = field(default_factory=set)
    #: Directive lines to write directly above an entry (see ``add_entry_directive``).
    _directive_insertions: list[tuple[BibEntry, str]] = field(default_factory=list)
    _pinax_renames: list[tuple[str, str]] = field(default_factory=list)
    _pinax_material_merges: list[tuple[str, str]] = field(default_factory=list)
    _format_layout: CanonicalLayout | None = None
    _tex_rewrites: list[_tex_rewrite.TexRewrite] = field(default_factory=list)
    _after_commit: list[Callable[[], object]] = field(default_factory=list)

    @classmethod
    def open(cls, path: str | Path) -> "Bibliography":
        """Load a `.bib` file into a bibliography."""
        bound_path = Path(path)
        lib, pristine_text, data = _load_source(bound_path)
        source_snapshot = snapshot_source_spans(pristine_text, lib)
        coll = cls(
            lib,
            bound_path,
            _pristine_text=pristine_text,
            _entry_snapshot=snapshot_entries(lib),
            _source_snapshot=source_snapshot,
            _fingerprint=fingerprint(bound_path, data),
        )
        FileStore.from_metadata(coll.lib, bound_path)
        return coll

    @classmethod
    def from_text(cls, text: str, path: str | Path | None = None) -> "Bibliography":
        """Create a bibliography from BibTeX text."""
        lib = parse_bib(text)
        source_snapshot = snapshot_source_spans(text, lib)
        coll = cls(
            lib,
            Path(path) if path is not None else None,
            _pristine_text=text,
            _entry_snapshot=snapshot_entries(lib),
            _source_snapshot=source_snapshot,
        )
        if coll.path is not None:
            FileStore.from_metadata(coll.lib, coll.path)
        return coll

    @classmethod
    def from_bibfile(cls, lib: BibFile, path: str | Path | None = None) -> "Bibliography":
        """Wrap an existing library without copying it."""
        text = write_bib(lib)
        source_snapshot = snapshot_source_spans(text, lib)
        coll = cls(
            lib,
            Path(path) if path is not None else None,
            _pristine_text=text,
            _entry_snapshot=snapshot_entries(lib),
            _source_snapshot=source_snapshot,
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
        """Return whether output or a deferred Pinax transaction is staged."""
        return self.is_modified or bool(self._pinax_renames or self._pinax_material_merges)

    @property
    def is_modified(self) -> bool:
        """Return whether staged output differs from the pristine text."""
        return self.preview() != self._pristine_text

    @property
    def files(self) -> FileStore | None:
        """Return the Pinax file store when ``pinax-files-dir`` metadata is configured."""
        if self.path is None:
            return None
        return FileStore.from_metadata(self.lib, self.path)

    def mark_dirty(self, changed: int | bool = True) -> None:
        """Compatibility hook after a caller mutates ``lib`` directly.

        Dirty state is derived from renderable output, so no flag needs setting.
        When ``changed`` is truthy, render once to validate that the direct model
        mutation is represented by the engine's serialization paths.
        """
        if changed:
            self.preview()

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

    @property
    def source_fingerprint(self) -> FileFingerprint | None:
        """Return the fingerprint of the file state this bibliography was read from.

        ``None`` when the bibliography is not bound to a file it read. A commit
        refreshes it to the written state.
        """
        return self._fingerprint

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
        tex_rewrites = list(self._tex_rewrites)
        after_commit = list(self._after_commit)
        # Check every staged TeX source before touching anything, so a source
        # that cannot be rewritten stops the commit rather than splitting it.
        try:
            _tex_rewrite.preflight(tex_rewrites)
        except _tex_rewrite.TexSourceChangedError as exc:
            raise ExternalModificationError(exc.path) from exc
        transactions: list[PinaxRenameTransaction] = []
        try:
            transactions = self._apply_pinax_renames()
            transactions.extend(self._apply_pinax_material_merges())
            if modified:
                result = save_text(
                    new_text,
                    str(self.path),
                    encoding=self.lib.encoding,
                    backup=backup,
                    validate=True,
                )
                if not result.success:
                    raise OSError(result.error or f"Could not write {self.path}")
        except Exception:
            for transaction in reversed(transactions):
                transaction.rollback()
            raise
        self._refresh_from_text(new_text, fingerprint=fingerprint(self.path))
        # The .bib is committed; the manuscript follows it, never the reverse.
        _tex_rewrite.apply(tex_rewrites, backup=backup)
        for action in after_commit:
            action()
        return CommitResult(changed_entries, diff_text, modified)

    def after_commit(self, action: Callable[[], object]) -> None:
        """Run ``action`` once the next commit has written the ``.bib``.

        For side effects that must follow the bibliography rather than precede
        it, such as deleting the materials of a removed entry: if the commit
        fails, they never happen.
        """
        self._after_commit.append(action)

    def stage_tex_rewrites(self, rewrites: list[_tex_rewrite.TexRewrite]) -> None:
        """Stage TeX source rewrites to be applied after the next commit."""
        self._tex_rewrites.extend(rewrite for rewrite in rewrites if rewrite.modified)

    def _clear_staged_edits(self) -> None:
        self._appended_entries.clear()
        self._removed_entries.clear()
        self._pinax_renames.clear()
        self._pinax_material_merges.clear()
        self._consolidate_metadata = False
        self._removed_comments.clear()
        self._directive_insertions.clear()
        self._format_layout = None
        self._tex_rewrites.clear()
        self._after_commit.clear()

    def reset(self) -> None:
        """Discard staged edits and restore the pristine in-memory library."""
        encoding = self.lib.encoding
        self.lib = parse_bib(self._pristine_text)
        self.lib.encoding = encoding
        self._entry_snapshot = snapshot_entries(self.lib)
        self._source_snapshot = snapshot_source_spans(self._pristine_text, self.lib)
        self._clear_staged_edits()

    def reload(self, *, force: bool = False) -> None:
        """Reload the bound file from disk, optionally discarding staged edits."""
        if self.path is None:
            raise ValueError("reload requires a bound path")
        if self.is_dirty and not force:
            raise ValueError("cannot reload a dirty bibliography without force=True")
        lib, text, data = _load_source(self.path)
        FileStore.from_metadata(lib, self.path)
        self.lib = lib
        self._pristine_text = text
        self._entry_snapshot = snapshot_entries(self.lib)
        self._source_snapshot = snapshot_source_spans(self._pristine_text, self.lib)
        self._fingerprint = fingerprint(self.path, data)
        self._clear_staged_edits()

    def _refresh_from_text(self, text: str, fingerprint: FileFingerprint | None = None) -> None:
        encoding = self.lib.encoding
        self.lib = parse_bib(text)
        self.lib.encoding = encoding
        self._pristine_text = text
        self._entry_snapshot = snapshot_entries(self.lib)
        self._source_snapshot = snapshot_source_spans(text, self.lib)
        self._fingerprint = fingerprint
        self._clear_staged_edits()

    def _iter_changed_entries(
        self,
    ) -> Generator[tuple[BibEntry, str | None, bool], None, None]:
        """Yield ``(entry, before, missing)`` for every non-appended entry.

        Delegates to the module-level :func:`~pynakes._engine_helpers.iter_changed_entries`
        helper, passing the current appended-entry id set.
        """
        appended_ids = {id(e) for e in self._appended_entries}
        yield from iter_changed_entries(
            self.lib.entries.values(), self._entry_snapshot, appended_ids
        )

    def _entry_edits(self) -> list[SpanEdit] | None:
        """Return surgical entry edits, or ``None`` when a full rewrite is needed."""
        edits: list[SpanEdit] = []
        for entry, before, missing in self._iter_changed_entries():
            if missing:
                return None
            if before is None:
                continue
            if entry.raw_content is None:
                return None
            if entry.raw_content != before:
                span = self._source_snapshot.entries.get(id(entry))
                if span is None:
                    if self._source_snapshot.complete:
                        raise RuntimeError("snapshotted entry has no pristine source span")
                    return None
                edits.append(SpanEdit(span, entry.raw_content))
        return edits

    def _metadata_edits(self) -> tuple[list[SpanEdit], list[str]] | None:
        """Derive raw-comment edits from the pristine and current model states.

        Metadata operations preserve physical comment slots: they replace a slot
        in place, blank it when removing the final key, or append a new slot.  The
        snapshot therefore lets rendering discover metadata changes without every
        operation also maintaining a parallel text-replacement list.  A slot a
        scrub removed outright is deleted together with its trailing gap, so no
        blank block is left behind where it stood.
        """
        edits: list[SpanEdit] = []
        insertions: list[str] = []
        raw_comments_snapshot = self._source_snapshot.raw_comments
        size = max(len(raw_comments_snapshot), len(self.lib.raw_comments))
        for index in range(size):
            old = raw_comments_snapshot[index] if index < len(raw_comments_snapshot) else None
            new = self.lib.raw_comments[index] if index < len(self.lib.raw_comments) else ""
            if old == new:
                continue
            if not old:
                if new:
                    insertions.append(new)
                continue
            span = self._source_snapshot.comments.get(index)
            if span is None:
                if self._source_snapshot.complete:
                    raise RuntimeError("snapshotted comment has no pristine source span")
                return None
            if index in self._removed_comments:
                span = block_removal_span(self._pristine_text, span)
            edits.append(SpanEdit(span, new))
        return edits, insertions

    def _directive_edits(self) -> list[SpanEdit]:
        """Insert each staged directive line at the start of its entry's span."""
        le = self.lib.line_ending
        edits: list[SpanEdit] = []
        for entry, line in self._directive_insertions:
            start = self._source_snapshot.entries[id(entry)].start
            own_line = start == 0 or self._pristine_text[start - 1] == "\n"
            text = f"{line}{le}" if own_line else f"{le}{line}{le}"
            edits.append(SpanEdit(SourceSpan(start, start, ""), text))
        return edits

    def _removed_entry_edits(self) -> list[SpanEdit] | None:
        edits: list[SpanEdit] = []
        for entry in self._removed_entries:
            span = self._source_snapshot.entries.get(id(entry))
            if span is None:
                if self._source_snapshot.complete:
                    raise RuntimeError("removed entry has no pristine source span")
                return None
            edits.append(SpanEdit(block_removal_span(self._pristine_text, span), ""))
        return edits

    def _render_text(self) -> str:
        if self._format_layout is not None:
            text = write_bib_canonical(self.lib, self._format_layout)
            if self._consolidate_metadata:
                text = (
                    metadata_ops.consolidate_metadata(self.lib, text, self.lib.line_ending) or text
                )
            return text
        text = self._render_entry_text()
        if self._consolidate_metadata:
            text = metadata_ops.consolidate_metadata(self.lib, text, self.lib.line_ending) or text
        return text

    def _render_entry_text(self) -> str:
        entry_edits = self._entry_edits()
        removed_entry_edits = self._removed_entry_edits()
        metadata_edits = self._metadata_edits()
        if entry_edits is None or removed_entry_edits is None or metadata_edits is None:
            # Libraries constructed without a source layout have no positional
            # identity to preserve; whole-model rendering is explicit for them.
            return write_bib(self.lib)
        comment_edits, comment_insertions = metadata_edits
        try:
            text = apply_span_edits(
                self._pristine_text,
                [*entry_edits, *removed_entry_edits, *comment_edits, *self._directive_edits()],
            )
        except ValueError as exc:
            raise RuntimeError(f"could not apply surgical source edits: {exc}") from exc

        for comment in comment_insertions:
            text = insert_metadata_comment(text, comment, self.lib.line_ending)

        for entry in self._appended_entries:
            text = append_entry_text(
                text,
                write_bib(BibFile(entries=[entry], line_ending=self.lib.line_ending)).rstrip(
                    "\r\n"
                ),
                self.lib.line_ending,
                self.lib.metadata_blocks,
            )
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
