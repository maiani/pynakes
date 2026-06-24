"""In-process engine facade for bibliography operations.

``Collection`` wraps one :class:`~pynakes.model.BibFile`, remembers the pristine
file text it was opened from, stages edits in memory, and can preview, diff, or
commit those staged edits. Entry edits use the same surgical splice strategy as
the CLI so unchanged entries stay byte-stable where possible.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pynakes import convert as convert_ops
from pynakes import dedupe as dedupe_ops
from pynakes import fields as field_ops
from pynakes import files as file_ops
from pynakes import groups as group_ops
from pynakes import importer as importer_ops
from pynakes import integrity as integrity_ops
from pynakes import journals as journal_ops
from pynakes import keys as key_ops
from pynakes import metadata as metadata_ops
from pynakes import normalize as normalize_ops
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.diff import generate_diff
from pynakes.editing import splice_into_text
from pynakes.io import load_bib, save_text
from pynakes.lint import LintIssue
from pynakes.lint import lint as lint_lib
from pynakes.model import BibEntry, BibFile, EntryStore, MetadataBlock

QueryFilter = Callable[[BibEntry], bool] | None


@dataclass
class FileFingerprint:
    """Observed file state used for optimistic-concurrency checks.

    The size, nanosecond modification time, and content digest make a
    ``Collection`` reject a commit when its on-disk source changed externally.
    """

    size: int
    mtime_ns: int
    sha256: str


@dataclass
class CommitResult:
    """Outcome of one :meth:`Collection.commit` lifecycle transition.

    ``diff`` compares the pre-commit pristine text with the staged output;
    ``modified`` distinguishes a successful no-op commit from one that wrote.
    """

    changed_entries: int
    diff: str
    modified: bool


class ExternalModificationError(Exception):
    """Raised when a bound collection's file changed since it was opened."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"File changed on disk since it was opened: {path}")


@dataclass
class Collection:
    """One in-memory bibliography collection.

    A collection is a *derived editing buffer*, not a second source of truth. It
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

    @classmethod
    def open(cls, path: str | Path) -> "Collection":
        """Load a `.bib` file into a collection."""
        bound_path = Path(path)
        lib = load_bib(str(bound_path))
        pristine_text = _read_text(bound_path, lib.encoding)
        return cls(
            lib,
            bound_path,
            _pristine_text=pristine_text,
            _entry_snapshot=_snapshot_entries(lib),
            _fingerprint=_fingerprint(bound_path),
        )

    @classmethod
    def from_text(cls, text: str, path: str | Path | None = None) -> "Collection":
        """Create a collection from BibTeX text."""
        lib = parse_bib(text)
        return cls(
            lib,
            Path(path) if path is not None else None,
            _pristine_text=text,
            _entry_snapshot=_snapshot_entries(lib),
        )

    @classmethod
    def from_bibfile(cls, lib: BibFile, path: str | Path | None = None) -> "Collection":
        """Wrap an existing library without copying it."""
        text = write_bib(lib)
        return cls(
            lib,
            Path(path) if path is not None else None,
            _pristine_text=text,
            _entry_snapshot=_snapshot_entries(lib),
        )

    @property
    def entries(self) -> EntryStore:
        """Return the duplicate-preserving entry collection."""
        return self.lib.entries

    @property
    def is_dirty(self) -> bool:
        """Return whether an engine operation changed the in-memory library."""
        return self._dirty

    @property
    def is_modified(self) -> bool:
        """Return whether staged output differs from the pristine text."""
        return self.preview() != self._pristine_text

    def _mark(self, changed: int | bool) -> None:
        if changed:
            self._dirty = True

    def mark_dirty(self, changed: int | bool = True) -> None:
        """Mark the collection dirty after a caller mutates ``lib`` directly."""
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
        return len(self._entry_edits()) + len(self._appended_entries) + len(self._removed_entries)

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
        pristine = parse_bib(self._pristine_text)
        before = {entry.key: entry for entry in pristine.entries.values()}
        after = {entry.key: entry for entry in self.lib.entries.values()}

        def signature(entry: BibEntry) -> tuple[str, tuple[tuple[str, str], ...]]:
            return (entry.type.lower(), tuple(sorted(entry.fields.items())))

        added_keys = [key for key in after if key not in before]
        removed_keys = [key for key in before if key not in after]

        # Pair a removed key with an added key carrying the same record → rename.
        added_by_sig = {signature(after[key]): key for key in added_keys}
        renamed_to: set[str] = set()
        renames: list[dict] = []
        plain_removed: list[str] = []
        for key in removed_keys:
            match = added_by_sig.get(signature(before[key]))
            if match is not None and match not in renamed_to:
                renames.append({"change": "renamed", "from": key, "to": match})
                renamed_to.add(match)
            else:
                plain_removed.append(key)
        added_keys = [key for key in added_keys if key not in renamed_to]

        entries: list[dict] = list(renames)
        entries += [{"change": "added", "key": key} for key in added_keys]
        entries += [{"change": "removed", "key": key} for key in plain_removed]

        modified = 0
        for key, after_entry in after.items():
            before_entry = before.get(key)
            if before_entry is None:
                continue
            fields: dict[str, dict[str, str | None]] = {}
            for name in sorted(set(before_entry.fields) | set(after_entry.fields)):
                old = before_entry.fields.get(name)
                new = after_entry.fields.get(name)
                if old != new:
                    fields[name] = {"old": old, "new": new}
            type_changed = before_entry.type.lower() != after_entry.type.lower()
            if not fields and not type_changed:
                continue
            modified += 1
            item: dict = {"change": "modified", "key": key}
            if type_changed:
                item["type"] = {"old": before_entry.type, "new": after_entry.type}
            if fields:
                item["fields"] = fields
            entries.append(item)

        metadata: list[dict] = []
        before_meta, after_meta = pristine.metadata, self.lib.metadata
        for name in sorted(set(before_meta) | set(after_meta)):
            old = before_meta.get(name)
            new = after_meta.get(name)
            if old != new:
                metadata.append({"key": name, "old": old, "new": new})

        return {
            "summary": {
                "added": len(added_keys),
                "removed": len(plain_removed),
                "renamed": len(renames),
                "modified": modified,
                "metadata_changed": len(metadata),
            },
            "entries": entries,
            "metadata": metadata,
        }

    def externally_changed(self) -> bool:
        """Return whether the bound file changed since open/commit."""
        if self.path is None or self._fingerprint is None:
            return False
        return _fingerprint(self.path) != self._fingerprint

    def commit(self, *, force: bool = False, backup: bool = False) -> CommitResult:
        """Write staged edits to the bound file and refresh the collection snapshot.

        Writes are atomic and re-parse-validated, so a ``.bak`` is opt-in:
        pass ``backup=True`` to also leave a ``<file>.bak`` copy behind.
        """
        if self.path is None:
            raise ValueError("commit requires a collection path")
        if (
            not force
            and self._fingerprint is not None
            and _fingerprint(self.path) != self._fingerprint
        ):
            raise ExternalModificationError(self.path)

        changed_entries = self.changed_entries_count()
        diff_text = self.diff()
        new_text = self.preview()
        modified = new_text != self._pristine_text
        if modified:
            result = save_text(new_text, str(self.path), encoding=self.lib.encoding, backup=backup)
            if not result.success:
                raise OSError(result.error or f"Could not write {self.path}")
        self._refresh_from_text(new_text, fingerprint=_fingerprint(self.path))
        return CommitResult(changed_entries, diff_text, modified)

    def reset(self) -> None:
        """Discard staged edits and restore the pristine in-memory library."""
        encoding = self.lib.encoding
        self.lib = parse_bib(self._pristine_text)
        self.lib.encoding = encoding
        self._entry_snapshot = _snapshot_entries(self.lib)
        self._appended_entries.clear()
        self._removed_entries.clear()
        self._text_replacements.clear()
        self._consolidate_metadata = False
        self._dirty = False

    def reload(self, *, force: bool = False) -> None:
        """Reload the bound file from disk, optionally discarding staged edits."""
        if self.path is None:
            raise ValueError("reload requires a collection path")
        if self._dirty and not force:
            raise ValueError("cannot reload a dirty collection without force=True")
        self.lib = load_bib(str(self.path))
        self._pristine_text = _read_text(self.path, self.lib.encoding)
        self._entry_snapshot = _snapshot_entries(self.lib)
        self._fingerprint = _fingerprint(self.path)
        self._appended_entries.clear()
        self._removed_entries.clear()
        self._text_replacements.clear()
        self._consolidate_metadata = False
        self._dirty = False

    def _refresh_from_text(self, text: str, fingerprint: FileFingerprint | None = None) -> None:
        encoding = self.lib.encoding
        self.lib = parse_bib(text)
        self.lib.encoding = encoding
        self._pristine_text = text
        self._entry_snapshot = _snapshot_entries(self.lib)
        self._fingerprint = fingerprint
        self._appended_entries.clear()
        self._removed_entries.clear()
        self._text_replacements.clear()
        self._consolidate_metadata = False
        self._dirty = False

    def _entry_edits(self) -> list[tuple[str, str]]:
        edits: list[tuple[str, str]] = []
        appended_ids = {id(entry) for entry in self._appended_entries}
        for entry in self.lib.entries.values():
            if id(entry) in appended_ids:
                continue
            before = self._entry_snapshot.get(id(entry))
            if before is None:
                if entry.raw_content is not None and entry.raw_content != before:
                    return []
                continue
            if entry.raw_content is None:
                return []
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
        if edits:
            spliced = splice_into_text(text, edits)
            if spliced is None:
                return write_bib(self.lib)
            text = spliced
        elif self._requires_full_write():
            return write_bib(self.lib)

        for entry in self._appended_entries:
            text = _append_entry_text(
                text,
                importer_ops.render_entry(entry, self.lib.line_ending),
                self.lib.line_ending,
                self.lib.metadata_blocks,
            )
        return text

    def _apply_text_replacements(self, text: str) -> str | None:
        for old, new in self._text_replacements:
            if old is None:
                text = _insert_metadata_comment(text, new, self.lib.line_ending)
            elif old in text:
                text = text.replace(old, new, 1)
            else:
                return None
        return text

    def _requires_full_write(self) -> bool:
        appended_ids = {id(entry) for entry in self._appended_entries}
        for entry in self.lib.entries.values():
            if id(entry) in appended_ids:
                continue
            before = self._entry_snapshot.get(id(entry))
            if before is None and entry.raw_content is not None:
                continue
            if before is not None and entry.raw_content is not None:
                continue
            if entry.raw_content != before:
                return True
        return False

    def _file_name(self) -> str:
        return self.path.name if self.path is not None else "collection.bib"

    # --- read-only views -------------------------------------------------

    def lint(self) -> list[LintIssue]:
        """Run linting against the current in-memory library."""
        return lint_lib(self.lib)

    def duplicate_keys(self) -> dict[str, int]:
        """Return duplicate citation-key counts."""
        return self.lib.entries.duplicate_keys()

    def list_groups(self) -> list[str]:
        """Return all group names in first-seen order."""
        return group_ops.list_groups(self.lib)

    def list_entries_in_group(self, group: str) -> list[str]:
        """Return entry keys that belong to ``group``."""
        return group_ops.list_entries_in_group(self.lib, group)

    def files_check(self, roots: list[str | Path] | None = None) -> file_ops.FileCheckReport:
        """Validate JabRef linked files for this collection."""
        if self.path is None:
            raise ValueError("files_check requires a collection path")
        return file_ops.check_linked_files(self.lib, self.path, roots)

    def journals_check(
        self,
        journal_table: str | None = None,
        ltwa_table: str | None = None,
    ) -> list[dict[str, str]]:
        """Classify distinct journal titles without modifying the collection."""
        sources = journal_ops.load_sources(journal_table, ltwa_table)
        seen: dict[str, str] = {}
        for entry in self.lib.entries.values():
            for journal_field in journal_ops.JOURNAL_FIELDS:
                title = entry.fields.get(journal_field)
                if title and title not in seen:
                    seen[title] = journal_ops.classify_journal(title, entry, sources)
        return [{"journal": title, "status": status} for title, status in seen.items()]

    def dedupe_check(self) -> list[dedupe_ops.DuplicateCluster]:
        """Return duplicate-work clusters without modifying the collection."""
        return dedupe_ops.find_duplicate_clusters(self.lib)

    def verify(
        self,
        *,
        online: bool = False,
        cache_dir: str | Path | None = None,
    ) -> integrity_ops.VerifyReport:
        """Verify entries against authoritative metadata without modifying."""
        return integrity_ops.verify_library(self.lib, online=online, cache_dir=cache_dir)

    def published_check(
        self,
        *,
        online: bool = False,
        cache_dir: str | Path | None = None,
    ) -> integrity_ops.PublishedReport:
        """Check preprint entries for published metadata without modifying."""
        return integrity_ops.check_published(self.lib, online=online, cache_dir=cache_dir)

    # --- group operations -----------------------------------------------

    def add_to_group(self, key: str, group: str) -> int:
        """Add every entry with ``key`` to ``group``."""
        count = group_ops.add_to_group(self.lib, key, group)
        self._mark(count)
        return count

    def remove_from_group(self, key: str, group: str) -> int:
        """Remove every entry with ``key`` from ``group``."""
        count = group_ops.remove_from_group(self.lib, key, group)
        self._mark(count)
        return count

    # --- key operations --------------------------------------------------

    def generate_keys(self) -> list[tuple[str, str]]:
        """Regenerate all citation keys from entry metadata."""
        renames = key_ops.regenerate_keys(self.lib)
        self._mark(bool(renames))
        return renames

    def generate_key(self, key: str) -> tuple[str, str] | None:
        """Regenerate one citation key from its entry metadata."""
        rename = key_ops.regenerate_key(self.lib, key)
        self._mark(rename is not None)
        return rename

    def repair_keys(self) -> list[tuple[str, str]]:
        """Repair duplicate citation keys."""
        renames = key_ops.repair_duplicate_keys(self.lib)
        self._mark(bool(renames))
        return renames

    def rename_key(self, old: str, new: str) -> int:
        """Rename one unique citation key."""
        count = key_ops.rename_key(self.lib, old, new)
        self._mark(count)
        return count

    # --- field operations ------------------------------------------------

    def _where(self, where: str | QueryFilter) -> QueryFilter:
        if isinstance(where, str):
            return field_ops.parse_query(where)
        return where

    def rename_field(self, old: str, new: str, where: str | QueryFilter = None) -> int:
        """Rename a field on matching entries."""
        count = field_ops.rename_field(self.lib, old, new, self._where(where))
        self._mark(count)
        return count

    def move_field(self, old: str, new: str, where: str | QueryFilter = None) -> int:
        """Move a field on matching entries."""
        count = field_ops.move_field(self.lib, old, new, self._where(where))
        self._mark(count)
        return count

    def append_field(
        self,
        field: str,
        value: str,
        where: str | QueryFilter = None,
    ) -> int:
        """Append a delimited field value on matching entries."""
        count = field_ops.append_field(self.lib, field, value, self._where(where))
        self._mark(count)
        return count

    def clear_field(self, field: str, where: str | QueryFilter = None) -> int:
        """Remove a field from matching entries."""
        count = field_ops.clear_field(self.lib, field, self._where(where))
        self._mark(count)
        return count

    def protect_title(
        self,
        field: str = "title",
        where: str | QueryFilter = None,
        terms: list[str] | None = None,
    ) -> int:
        """Brace-protect capitalization-sensitive title tokens."""
        count = field_ops.protect_title_capitalization(
            self.lib,
            field=field,
            where=self._where(where),
            terms=terms,
        )
        self._mark(count)
        return count

    # --- format/metadata operations -------------------------------------

    def normalize(
        self,
        options: normalize_ops.NormalizeOptions | None = None,
    ) -> normalize_ops.NormalizeResult:
        """Run the standard normalization routine in memory."""
        opts = options or normalize_ops.NormalizeOptions()
        report = normalize_ops.normalize_library(self.lib, opts)
        self._consolidate_metadata = normalize_ops.resolve_format_metadata(
            self.lib, opts.format_metadata
        )
        self._mark(
            bool(
                report.authors
                or report.journals
                or report.dois
                or sum(report.title_fields.values())
                or report.entry_types
                or report.field_names
                or self._consolidate_metadata
            )
        )
        return report

    def convert(self, target: str) -> convert_ops.ConvertResult:
        """Convert the collection in memory to ``target`` conventions."""
        report = convert_ops.convert(self.lib, target)
        self._mark(bool(report.entries))
        return report

    def abbreviate_journals(
        self,
        journal_table: str | None = None,
        ltwa_table: str | None = None,
    ) -> journal_ops.JournalResult:
        """Abbreviate journal titles in memory."""
        sources = journal_ops.load_sources(journal_table, ltwa_table)
        report = journal_ops.normalize_journals(self.lib, "abbreviated", sources)
        self._mark(report.changed)
        return report

    def expand_journals(
        self,
        journal_table: str | None = None,
        ltwa_table: str | None = None,
    ) -> journal_ops.JournalResult:
        """Expand journal titles in memory."""
        sources = journal_ops.load_sources(journal_table, ltwa_table)
        report = journal_ops.normalize_journals(self.lib, "full", sources)
        self._mark(report.changed)
        return report

    def import_doi(
        self,
        doi: str,
        *,
        key: str | None = None,
        key_source: str = "generated",
        allow_duplicate_doi: bool = False,
    ) -> BibEntry:
        """Import one DOI entry into memory."""
        entry = importer_ops.prepare_imported_entry(
            self.lib,
            doi,
            key=key,
            key_source=key_source,
            allow_duplicate_doi=allow_duplicate_doi,
        )
        self.lib.entries.add(entry)
        self._appended_entries.append(entry)
        self._mark(True)
        return entry

    def import_reference(
        self,
        identifier: str,
        *,
        key: str | None = None,
        key_source: str = "generated",
        allow_duplicate: bool = False,
    ) -> tuple[str, BibEntry]:
        """Import one reference (DOI or arXiv) into memory.

        The identifier type is auto-detected. arXiv entries use ``@online`` for
        BibLaTeX libraries and ``@misc`` for BibTeX ones, per the library's
        ``databaseType`` metadata (defaulting to BibTeX). Returns
        ``(kind, entry)``.
        """
        kind, entry = importer_ops.prepare_imported_reference(
            self.lib,
            identifier,
            dialect=metadata_ops.library_database_type(self.lib),
            key=key,
            key_source=key_source,
            allow_duplicate=allow_duplicate,
        )
        self.lib.entries.add(entry)
        self._appended_entries.append(entry)
        self._mark(True)
        return kind, entry

    def set_metadata(
        self,
        key: str,
        value: str,
        *,
        namespace: str | None = None,
        allow_unknown: bool = False,
    ) -> metadata_ops.MetadataUpdate:
        """Set one metadata block in memory (jabref-meta or pynakes-meta)."""
        update = metadata_ops.set_metadata(
            self.lib, key, value, namespace=namespace, allow_unknown=allow_unknown
        )
        self._text_replacements.append((update.old_raw, update.new_raw))
        self._mark(True)
        return update

    def dedupe_merge(self) -> dedupe_ops.DedupeMergeReport:
        """Merge duplicate-work clusters in memory."""
        report = dedupe_ops.merge_duplicates(self.lib)
        for entry in report.removed_entries:
            if entry.raw_content:
                self._text_replacements.append((entry.raw_content, ""))
        self._removed_entries.extend(report.removed_entries)
        self._mark(report.removed_entry_count or report.field_changes)
        return report

    def enrich(
        self,
        *,
        online: bool = False,
        cache_dir: str | Path | None = None,
    ) -> integrity_ops.EnrichReport:
        """Conservatively fill missing metadata in memory."""
        report = integrity_ops.enrich_library(self.lib, online=online, cache_dir=cache_dir)
        self._mark(report.changed_fields)
        return report

    def apply_published(
        self,
        *,
        online: bool = False,
        cache_dir: str | Path | None = None,
    ) -> integrity_ops.PublishedReport:
        """Apply conservative published-version metadata updates in memory."""
        report = integrity_ops.check_published(
            self.lib,
            online=online,
            apply=True,
            cache_dir=cache_dir,
        )
        self._mark(bool(report.updates))
        return report


def _snapshot_entries(lib: BibFile) -> dict[int, str | None]:
    return {id(entry): entry.raw_content for entry in lib.entries.values()}


def _read_text(path: Path, encoding: str) -> str:
    return path.read_text(encoding=encoding, errors="replace")


def _fingerprint(path: Path) -> FileFingerprint:
    data = path.read_bytes()
    stat = path.stat()
    return FileFingerprint(
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _append_entry_text(
    original_text: str,
    entry_text: str,
    line_ending: str,
    metadata_blocks: list[MetadataBlock],
) -> str:
    """Append an entry, placing it before a canonical trailing metadata section."""
    metadata_start = _trailing_metadata_start(original_text, metadata_blocks)
    if metadata_start is not None:
        body = original_text[:metadata_start].rstrip("\r\n")
        metadata = original_text[metadata_start:]
        if body:
            return body + line_ending * 2 + entry_text + line_ending * 2 + metadata
        return entry_text + line_ending * 2 + metadata
    if not original_text:
        return entry_text + line_ending
    if original_text.endswith(line_ending * 2):
        return original_text + entry_text + line_ending
    if original_text.endswith(line_ending):
        return original_text + line_ending + entry_text + line_ending
    return original_text + line_ending + line_ending + entry_text + line_ending


def _trailing_metadata_start(text: str, blocks: list[MetadataBlock]) -> int | None:
    """Find the start of a metadata-only section at the end of *text*.

    Metadata comments are canonical only when they form the final non-whitespace
    content of a library. Earlier metadata remains untouched, so importing into
    a hand-arranged file does not relocate unrelated comments or entries.
    """
    end = len(text.rstrip("\r\n"))
    start = end
    found = False
    for block in reversed(blocks):
        index = text.rfind(block.raw, 0, start)
        if index == -1 or text[index + len(block.raw) : start].strip():
            continue
        start = index
        found = True
    return start if found else None


def _insert_metadata_comment(original_text: str, comment: str, line_ending: str) -> str:
    """Append a new metadata comment at the file end (the canonical position).

    JabRef writes its ``@Comment{...-meta: ...}`` blocks at the bottom of the
    file, so a newly-created block is appended there — separated from the
    preceding content by one blank line — rather than prepended.
    """
    if not original_text:
        return comment + line_ending
    body = original_text.rstrip("\r\n")
    return body + line_ending + line_ending + comment + line_ending
