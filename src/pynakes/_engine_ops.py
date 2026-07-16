"""Operation-method mixin for :class:`~pynakes.engine.Bibliography`.

All methods here delegate to the relevant operation modules and call
``self._mark()`` / ``self._stage_pinax_renames()`` to record staging state.
Do not import this module directly; use ``pynakes.engine``.

Group-tree and key operations live in :mod:`pynakes._engine_groups` and
:mod:`pynakes._engine_keys` respectively.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pynakes import convert as convert_ops
from pynakes import dedupe as dedupe_ops
from pynakes import fields as field_ops
from pynakes import files as file_ops
from pynakes import importer as importer_ops
from pynakes import integrity as integrity_ops
from pynakes import journals as journal_ops
from pynakes import metadata as metadata_ops
from pynakes import normalize as normalize_ops
from pynakes._engine_helpers import (
    build_fetch_queue,
    entry_removal_text,
    metadata_fetch_policy,
    run_fetch_loop,
)
from pynakes.canonical import CanonicalLayout
from pynakes.editing import set_entry_type
from pynakes.fetch_progress import FetchProgress
from pynakes.filestore import FILES_DIR_KEY, resolve_files_dir
from pynakes.lint import LintIssue
from pynakes.lint import lint as lint_lib
from pynakes.metadata import FetchPolicy
from pynakes.model import BibEntry, QueryFilter


class BibliographyOperations:
    """Mixin providing all operation methods for :class:`~pynakes.engine.Bibliography`.

    Consumers must not instantiate this class directly.
    """

    # --- read-only views -------------------------------------------------

    def lint(self) -> list[LintIssue]:
        """Run linting against the current in-memory library."""
        return lint_lib(self.lib)

    def duplicate_keys(self) -> dict[str, int]:
        """Return duplicate citation-key counts."""
        return self.lib.entries.duplicate_keys()

    def files_check(self, roots: list[str | Path] | None = None) -> file_ops.FileCheckReport:
        """Validate JabRef linked files for this bibliography."""
        if self.path is None:
            raise ValueError("files_check requires a bound path")
        return file_ops.check_linked_files(self.lib, self.path, roots)

    def journals_check(
        self,
        journal_table: str | None = None,
        ltwa_table: str | None = None,
    ) -> list[dict[str, str]]:
        """Classify distinct journal titles without modifying the bibliography."""
        sources = journal_ops.load_sources(journal_table, ltwa_table)
        seen: dict[str, str] = {}
        for entry in self.lib.entries.values():
            for journal_field in journal_ops.JOURNAL_FIELDS:
                title = entry.fields.get(journal_field)
                if title and title not in seen:
                    seen[title] = journal_ops.classify_journal(title, entry, sources)
        return [{"journal": title, "status": status} for title, status in seen.items()]

    def dedupe_check(self) -> list[dedupe_ops.DuplicateCluster]:
        """Return duplicate-work clusters without modifying the bibliography."""
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

    def set_field(self, field: str, value: str, where: str | QueryFilter = None) -> int:
        """Set or replace a field on matching entries."""
        count = field_ops.set_field(self.lib, field, value, self._where(where))
        self._mark(count)
        return count

    def edit_entry(
        self,
        key: str,
        *,
        fields: dict[str, str] | None = None,
        clear_fields: list[str] | None = None,
        entry_type: str | None = None,
    ) -> dict[str, object]:
        """Patch the unique entry named ``key`` through surgical edit operations.

        Raises ``KeyError`` when absent and ``ValueError`` when the key is
        duplicated; callers must not guess which physical duplicate to edit.
        """
        matches = self.lib.entries.get_all(key)
        if not matches:
            raise KeyError(key)
        if len(matches) != 1:
            raise ValueError(f"Citation key {key!r} is duplicated; repair duplicates first")
        entry = matches[0]

        def selected(candidate: BibEntry) -> bool:
            return candidate is entry

        set_count = 0
        for name, value in (fields or {}).items():
            set_count += self.set_field(name, value, selected)
        clear_count = 0
        for name in clear_fields or []:
            clear_count += self.clear_field(name, selected)
        type_changed = False
        if entry_type is not None:
            normalized_type = entry_type.strip()
            if not normalized_type:
                raise ValueError("Entry type must not be empty")
            type_changed = set_entry_type(entry, normalized_type)
            self._mark(type_changed)
        return {
            "fields_set": set_count,
            "fields_cleared": clear_count,
            "entry_type_changed": type_changed,
        }

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

    def format(self, layout: CanonicalLayout | None = None) -> int:
        """Stage a layout-only canonical rewrite and return the entry count."""
        self._format_layout = layout or CanonicalLayout()
        self._entry_snapshot = {}
        self._mark(True)
        return len(self.lib.entries)

    def normalize(
        self,
        options: normalize_ops.NormalizeOptions | None = None,
    ) -> normalize_ops.NormalizeResult:
        """Apply the configured normalization steps to the staged library in memory."""
        opts = options or normalize_ops.NormalizeOptions()
        report = normalize_ops.normalize_library(self.lib, opts)
        self._consolidate_metadata = normalize_ops.resolve_format_metadata(
            self.lib, opts.format_metadata
        )
        if report.sort_entries_count:
            # Sorting reorders _entries in-place. Clearing the snapshot makes
            # every entry appear "missing" to _entry_edits(), which falls back
            # to write_bib() and preserves the new order.
            self._entry_snapshot = {}
        if report.renamed_keys:
            self._stage_pinax_renames(report.renamed_keys)
            self._rewrite_tex_for_renames(report.renamed_keys)
        self._mark(
            bool(
                report.authors
                or report.journals
                or report.dois
                or report.months
                or sum(report.title_fields.values())
                or report.entry_types
                or report.field_names
                or report.keys
                or report.sort_entries_count
                or self._consolidate_metadata
                or self._format_layout is not None
            )
        )
        return report

    def convert(self, target: str) -> convert_ops.ConvertResult:
        """Convert the bibliography in memory to ``target`` conventions."""
        report = convert_ops.convert(self.lib, target)
        if report.entries:
            if target == "bibtex":
                self.set_metadata("databaseType", "bibtex")
            elif target == "biblatex":
                self.set_metadata("databaseType", "biblatex")
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
            dialect=metadata_ops.library_dialect(self.lib),
            key=key,
            key_source=key_source,
            allow_duplicate=allow_duplicate,
        )
        self.lib.entries.add(entry)
        self._appended_entries.append(entry)
        self._mark(True)
        return kind, entry

    def add_entry(
        self,
        entry_type: str,
        key: str,
        fields: dict[str, str],
        *,
        allow_duplicate: bool = False,
    ) -> BibEntry:
        """Append one manually specified entry to the bibliography."""
        key = key.strip()
        entry_type = entry_type.strip().lower()
        if not key:
            raise ValueError("Citation key must not be empty")
        if not entry_type:
            raise ValueError("Entry type must not be empty")
        if self.lib.entries.get_all(key) and not allow_duplicate:
            raise ValueError(f"Citation key already exists: {key}")
        entry = BibEntry(key=key, type=entry_type, fields=dict(fields), modified=True)
        self.lib.entries.add(entry)
        self._appended_entries.append(entry)
        self._mark(True)
        return entry

    def set_metadata(
        self,
        key: str,
        value: str,
        *,
        namespace: str | None = None,
        allow_unknown: bool = False,
    ) -> metadata_ops.MetadataUpdate:
        """Set one metadata block in memory (jabref-meta or pynakes-meta)."""
        if self.path is not None and key.strip().lower() == FILES_DIR_KEY:
            resolve_files_dir(value, self.path)
        update = metadata_ops.set_metadata(
            self.lib, key, value, namespace=namespace, allow_unknown=allow_unknown
        )
        self._text_replacements.append((update.old_raw, update.new_raw))
        # Mirror an aliased pynakes-native write (dialect, sort-order,
        # key-pattern) into the jabref-meta projection on JabRef-tracked files so
        # JabRef never sees a stale value; a no-op otherwise.
        mirror = metadata_ops.project_aliased_to_jabref(self.lib, update)
        if mirror is not None:
            self._text_replacements.append((mirror.old_raw, mirror.new_raw))
            update.mirrored = mirror
        self._mark(True)
        return update

    def remove_metadata(
        self, key: str, *, namespace: str | None = None
    ) -> metadata_ops.MetadataUpdate | None:
        """Remove one metadata block in memory, or ``None`` if the key is absent."""
        update = metadata_ops.remove_metadata(self.lib, key, namespace=namespace)
        if update is None:
            return None
        self._text_replacements.append((update.old_raw, update.new_raw))
        self._mark(True)
        return update

    def adopt_jabref(self) -> metadata_ops.JabRefAdoptReport:
        """Establish a ``jabref-meta`` projection so JabRef tracks this library.

        Relocates any JabRef-native keys stranded in ``pynakes-meta`` into
        ``jabref-meta`` and ensures a ``databaseType`` block exists to anchor
        tracking. From then on the library is JabRef-tracked, so future writes of
        JabRef-native keys are routed to ``jabref-meta`` automatically. A library
        that is already tracked with nothing to relocate is a no-op.
        """
        was_tracked = metadata_ops.library_is_jabref_tracked(self.lib)
        rehome = [
            (block.key, block.value)
            for block in self.lib.pynakes_metadata_blocks
            if metadata_ops.metadata_owner(block.key) == "jabref"
        ]
        moved: list[str] = []
        for key, value in rehome:
            self.remove_metadata(key, namespace="pynakes")
            self.set_metadata(key, value, namespace="jabref")
            moved.append(key)

        database_type_added = False
        if not any(b.key.lower() == "databasetype" for b in self.lib.jabref_metadata_blocks):
            self.set_metadata(
                "databaseType", metadata_ops.library_dialect(self.lib), namespace="jabref"
            )
            database_type_added = True

        return metadata_ops.JabRefAdoptReport(
            moved_keys=moved,
            database_type_added=database_type_added,
            was_tracked=was_tracked,
        )

    def dedupe_merge(self) -> dedupe_ops.DedupeMergeReport:
        """Merge duplicate-work clusters in memory."""
        clusters = dedupe_ops.find_duplicate_clusters(self.lib)
        pinax_materials, pinax_merges = self._plan_pinax_dedupe_materials(clusters)
        report = dedupe_ops.merge_duplicates(self.lib, clusters)
        for entry in report.removed_entries:
            if entry.raw_content:
                span = (
                    entry_removal_text(self._pristine_text, entry.raw_content) or entry.raw_content
                )
                self._text_replacements.append((span, ""))
        self._removed_entries.extend(report.removed_entries)
        report.pinax_materials = pinax_materials
        self._stage_pinax_material_merges(pinax_merges)
        self._mark(report.removed_entry_count or report.field_changes)
        return report

    def _plan_pinax_dedupe_materials(
        self, clusters: list[dedupe_ops.DuplicateCluster]
    ) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
        store = self.files
        if store is None or not clusters:
            return [], []
        planned: list[dict[str, str]] = []
        merges: list[tuple[str, str]] = []
        conflicts: list[dedupe_ops.MergeConflict] = []
        for cluster in clusters:
            primary = cluster.entries[0]
            for entry in cluster.entries[1:]:
                if entry.key == primary.key:
                    continue
                try:
                    material_plan = store.plan_material_merge(entry.key, primary.key)
                except ValueError as exc:
                    conflicts.append(
                        dedupe_ops.MergeConflict(
                            cluster.identity,
                            "pinax_materials",
                            {primary.key: "survivor", entry.key: str(exc)},
                        )
                    )
                    continue
                planned.extend(material_plan)
                merges.append((entry.key, primary.key))
        if conflicts:
            raise dedupe_ops.DedupeConflictError(conflicts, clusters)
        return planned, merges

    def remove_entry(self, key: str) -> int:
        """Remove every entry with the given citation key from memory.

        Returns the number of entries removed.
        """
        entries = self.lib.entries.get_all(key)
        for entry in entries:
            if entry.raw_content:
                span = (
                    entry_removal_text(self._pristine_text, entry.raw_content) or entry.raw_content
                )
                self._text_replacements.append((span, ""))
            self.lib.entries.remove(entry)
            self._removed_entries.append(entry)
        self._mark(len(entries))
        return len(entries)

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

    # --- Pinax fetch/ensure operations -----------------------------------

    def ensure_files_dir(self) -> bool:
        """Bootstrap ``files-dir`` metadata if not already configured.

        Returns True if metadata was set (bibliography marked dirty), False if
        ``files-dir`` was already present.
        """
        for name in self.lib.metadata:
            if name.strip().lower() == FILES_DIR_KEY:
                return False
        if self.path is None:
            raise ValueError("ensure_files_dir requires a bound path")
        default = f"{self.path.stem}.files"
        self.set_metadata(FILES_DIR_KEY, default)
        return True

    def fetch_materials(
        self,
        target: str | None = None,
        *,
        policy: FetchPolicy | None = None,
        dry_run: bool = False,
        pdf_fetcher: Callable[[str], bytes] | None = None,
        source_fetcher: Callable[[str], bytes] | None = None,
        published_url_fetcher: Callable[[str], str | None] | None = None,
        institutional_url_fetcher: Callable[[str], str | None] | None = None,
        published_pdf_fetcher: Callable[[str], bytes] | None = None,
        supplement_url_fetcher: Callable[[str], tuple[str, ...]] | None = None,
        supplement_pdf_fetcher: Callable[[str], bytes] | None = None,
        cache_dir: str | Path | None = None,
        progress: FetchProgress | None = None,
        access: str = "open",
    ) -> dict:
        """Download selected arXiv, published, and supplementary materials for entries.

        Args:
            target: Optional single citation key to fetch. If None, fetch all.
            policy: Optional explicit fetch policy. When provided, overrides the
                library's metadata ``fetch-policy`` setting.
            dry_run: If True, report what would be fetched without downloading.
            pdf_fetcher: Injectable arXiv PDF fetcher for testing.
            source_fetcher: Injectable arXiv source fetcher for testing.
            published_url_fetcher: Injectable OA PDF URL resolver for testing.
            institutional_url_fetcher: Injectable publisher PDF URL resolver.
            published_pdf_fetcher: Injectable published PDF bytes fetcher.
            supplement_url_fetcher: Injectable supplement URL resolver.
            supplement_pdf_fetcher: Injectable supplement PDF bytes fetcher.
            cache_dir: Optional provider-response cache directory.
            progress: Optional callback receiving fetch progress events.
            access: Published-material access mode: ``open`` or ``institutional``.

        Returns:
            A dict with ``fetched``, ``skipped``, ``failed`` lists, plus
            ``fetch_policy`` dict reflecting the resolved fetch-policy.
        """
        if access not in {"open", "institutional"}:
            raise ValueError(f"Unknown fetch access mode: {access!r}")
        store = self.files
        if store is None:
            self.ensure_files_dir()
            store = self.files
            if store is None:
                raise ValueError("could not resolve files-dir after bootstrapping")

        store.ensure_root()

        if policy is not None:
            resolved = policy
        else:
            resolved = metadata_fetch_policy(self.lib)

        entry_queue = build_fetch_queue(self.lib, target)
        fetched, skipped, failed = run_fetch_loop(
            entry_queue,
            store,
            resolved,
            dry_run,
            pdf_fetcher=pdf_fetcher,
            source_fetcher=source_fetcher,
            published_url_fetcher=published_url_fetcher,
            institutional_url_fetcher=institutional_url_fetcher,
            published_pdf_fetcher=published_pdf_fetcher,
            supplement_url_fetcher=supplement_url_fetcher,
            supplement_pdf_fetcher=supplement_pdf_fetcher,
            cache_dir=cache_dir,
            progress=progress,
            access=access,
        )

        return {
            "fetch_policy": {
                "preprint": resolved.preprint,
                "published": resolved.published,
                "source": resolved.source,
                "supplement": resolved.supplement,
                "bestpdf": resolved.bestpdf,
            },
            "access": access,
            "fetched": fetched,
            "skipped": skipped,
            "failed": failed,
        }
