"""Operation-method mixin for :class:`~pynakes.engine.Bibliography`.

All methods here delegate to the relevant operation modules and stage any
matching Pinax transactions. Bibliography dirty state is derived from rendered
output and those transactions. Do not import this module directly; use
``pynakes.engine``.

Group-tree and key operations live in :mod:`pynakes._engine_groups` and
:mod:`pynakes._engine_keys` respectively.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
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
    metadata_fetch_policy,
    run_fetch_loop,
)
from pynakes.canonical import CanonicalLayout, format_selected_entries, validate_format_input
from pynakes.editing import set_entry_type
from pynakes.fetch_progress import FetchProgress
from pynakes.filestore import FILES_DIR_KEY, resolve_files_dir
from pynakes.lint import LintIssue
from pynakes.lint import lint as lint_lib
from pynakes.metadata import FetchPolicy
from pynakes.model import BibEntry, QueryFilter
from pynakes.progress import EntryProgress
from pynakes.usage import tex_sources_from_metadata, validate_tex_sources


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
        journal_source: str = journal_ops.DEFAULT_JOURNAL_SOURCE,
    ) -> list[dict[str, str]]:
        """Classify distinct journal titles without modifying the bibliography."""
        sources = journal_ops.load_sources(journal_table, ltwa_table, journal_source)
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
        cache_file: str | Path | None = None,
        progress: EntryProgress | None = None,
        concurrency: int = 1,
    ) -> integrity_ops.VerifyReport:
        """Verify entries against authoritative metadata without modifying."""
        return integrity_ops.verify_library(
            self.lib,
            online=online,
            cache_file=cache_file,
            progress=progress,
            concurrency=concurrency,
        )

    def published_check(
        self,
        *,
        online: bool = False,
        cache_file: str | Path | None = None,
        progress: EntryProgress | None = None,
        concurrency: int = 1,
    ) -> integrity_ops.PublishedReport:
        """Check preprint entries for published metadata without modifying."""
        return integrity_ops.check_published(
            self.lib,
            online=online,
            cache_file=cache_file,
            progress=progress,
            concurrency=concurrency,
        )

    def compare_entry_with_remote(
        self,
        key: str,
        *,
        online: bool = False,
        cache_file: str | Path | None = None,
    ) -> integrity_ops.EntryComparisonReport:
        """Compare one entry's fields against its DOI/arXiv remote record.

        Read-only: for a caller to review and apply only the fields they
        choose, e.g. through :meth:`edit_entry`. Raises ``KeyError`` when the
        key is absent and ``ValueError`` when it's duplicated; callers must
        not guess which physical duplicate to compare.
        """
        matches = self.lib.entries.get_all(key)
        if not matches:
            raise KeyError(key)
        if len(matches) != 1:
            raise ValueError(f"Citation key {key!r} is duplicated; repair duplicates first")
        return integrity_ops.compare_entry_with_remote(
            matches[0], online=online, cache_file=cache_file
        )

    def compare_entries(self, key: str, other_key: str) -> integrity_ops.EntryComparisonReport:
        """Compare two local entries' fields, for manual review.

        Read-only, no network access. Raises ``KeyError`` when either key is
        absent and ``ValueError`` when either is duplicated; callers must not
        guess which physical duplicate to compare.
        """
        matches = self.lib.entries.get_all(key)
        if not matches:
            raise KeyError(key)
        if len(matches) != 1:
            raise ValueError(f"Citation key {key!r} is duplicated; repair duplicates first")
        other_matches = self.lib.entries.get_all(other_key)
        if not other_matches:
            raise KeyError(other_key)
        if len(other_matches) != 1:
            raise ValueError(f"Citation key {other_key!r} is duplicated; repair duplicates first")
        return integrity_ops.compare_entries(matches[0], other_matches[0])

    # --- field operations ------------------------------------------------

    def _where(self, where: str | QueryFilter) -> QueryFilter:
        if isinstance(where, str):
            return field_ops.parse_query(where)
        return where

    def rename_field(self, old: str, new: str, where: str | QueryFilter = None) -> int:
        """Rename a field on matching entries."""
        count = field_ops.rename_field(self.lib, old, new, self._where(where))
        return count

    def set_field(self, field: str, value: str, where: str | QueryFilter = None) -> int:
        """Set or replace a field on matching entries."""
        count = field_ops.set_field(self.lib, field, value, self._where(where))
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
        return {
            "fields_set": set_count,
            "fields_cleared": clear_count,
            "entry_type_changed": type_changed,
        }

    def move_field(self, old: str, new: str, where: str | QueryFilter = None) -> int:
        """Move a field on matching entries."""
        count = field_ops.move_field(self.lib, old, new, self._where(where))
        return count

    def append_field(
        self,
        field: str,
        value: str,
        where: str | QueryFilter = None,
    ) -> int:
        """Append a delimited field value on matching entries."""
        count = field_ops.append_field(self.lib, field, value, self._where(where))
        return count

    def clear_field(self, field: str, where: str | QueryFilter = None) -> int:
        """Remove a field from matching entries."""
        count = field_ops.clear_field(self.lib, field, self._where(where))
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
        return count

    # --- format/metadata operations -------------------------------------

    def format(
        self,
        layout: CanonicalLayout | None = None,
        where: str | QueryFilter = None,
    ) -> int:
        """Lint, then stage a layout-only rewrite and return the entry count.

        Without ``where`` this is the whole-file canonical rewrite. With a
        ``where`` selector it reformats only the matching entries, in place, so
        unmatched entries and the file's block layout stay byte-for-byte
        identical; whole-file policies (entry order, block order, blank lines
        between entries) are not part of a selection and do not apply.
        """
        validate_format_input(self.lib)
        resolved = layout or CanonicalLayout()
        selector = self._where(where)
        if selector is None:
            self._format_layout = resolved
            self._entry_snapshot = {}
            return len(self.lib.entries)
        return format_selected_entries(self.lib, resolved, selector)

    def normalize(
        self,
        options: normalize_ops.NormalizeOptions | None = None,
        *,
        force_key_renames: bool = False,
    ) -> normalize_ops.NormalizeResult:
        """Apply configured normalization steps, optionally forcing incomplete key rewrites."""
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
            if force_key_renames and self.path is not None:
                sources = tex_sources_from_metadata(self.lib, self.path.parent)
                report.warnings.extend(validate_tex_sources(sources))
            self._rewrite_tex_for_renames(
                report.renamed_keys, allow_missing_sources=force_key_renames
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
        return report

    def abbreviate_journals(
        self,
        journal_table: str | None = None,
        ltwa_table: str | None = None,
        journal_source: str = journal_ops.DEFAULT_JOURNAL_SOURCE,
    ) -> journal_ops.JournalResult:
        """Abbreviate journal titles in memory."""
        sources = journal_ops.load_sources(journal_table, ltwa_table, journal_source)
        report = journal_ops.normalize_journals(self.lib, "abbreviated", sources)
        return report

    def expand_journals(
        self,
        journal_table: str | None = None,
        ltwa_table: str | None = None,
        journal_source: str = journal_ops.DEFAULT_JOURNAL_SOURCE,
    ) -> journal_ops.JournalResult:
        """Expand journal titles in memory."""
        sources = journal_ops.load_sources(journal_table, ltwa_table, journal_source)
        report = journal_ops.normalize_journals(self.lib, "full", sources)
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
        return entry

    def import_reference(
        self,
        identifier: str,
        *,
        key: str | None = None,
        key_source: str = "generated",
        allow_duplicate: bool = False,
    ) -> tuple[str, BibEntry]:
        """Import one reference from a supported identifier or URL into memory.

        The identifier type is auto-detected and provider metadata is normalized
        for the library's BibTeX/BibLaTeX dialect. Returns ``(kind, entry)``.
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
        # Mirror an aliased pynakes-native write (dialect, sort-order,
        # key-pattern) into the jabref-meta projection on JabRef-tracked files so
        # JabRef never sees a stale value; a no-op otherwise.
        mirror = metadata_ops.project_aliased_to_jabref(self.lib, update)
        if mirror is not None:
            update.mirrored = mirror
        return update

    def remove_metadata(
        self, key: str, *, namespace: str | None = None
    ) -> metadata_ops.MetadataUpdate | None:
        """Remove one metadata block in memory, or ``None`` if the key is absent."""
        update = metadata_ops.remove_metadata(self.lib, key, namespace=namespace)
        if update is None:
            return None
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

    def dedupe_merge(self, keys: Iterable[str] | None = None) -> dedupe_ops.DedupeMergeReport:
        """Merge duplicate-work clusters in memory.

        Without ``keys`` every cluster in the library is merged. With them, only
        the clusters containing at least one named citation key are, and the
        rest are left exactly as they are — the "I have looked at this pair and
        decided" case, which a whole-file merge cannot express. A key belonging
        to no cluster raises :class:`ValueError` rather than silently merging
        nothing, since the caller believed it named a duplicate.
        """
        clusters = dedupe_ops.find_duplicate_clusters(self.lib)
        if keys is not None:
            clusters = dedupe_ops.clusters_for_keys(clusters, keys)
        pinax_materials, pinax_merges = self._plan_pinax_dedupe_materials(clusters)
        report = dedupe_ops.merge_duplicates(self.lib, clusters)
        self._removed_entries.extend(report.removed_entries)
        report.pinax_materials = pinax_materials
        self._stage_pinax_material_merges(pinax_merges)
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
            self.lib.entries.remove(entry)
            self._removed_entries.append(entry)
        return len(entries)

    def enrich(
        self,
        *,
        online: bool = False,
        cache_file: str | Path | None = None,
        progress: EntryProgress | None = None,
        concurrency: int = 1,
    ) -> integrity_ops.EnrichReport:
        """Conservatively fill missing metadata in memory."""
        report = integrity_ops.enrich_library(
            self.lib,
            online=online,
            cache_file=cache_file,
            progress=progress,
            concurrency=concurrency,
        )
        return report

    def apply_published(
        self,
        *,
        online: bool = False,
        cache_file: str | Path | None = None,
        progress: EntryProgress | None = None,
        concurrency: int = 1,
    ) -> integrity_ops.PublishedReport:
        """Apply conservative published-version metadata updates in memory."""
        report = integrity_ops.check_published(
            self.lib,
            online=online,
            apply=True,
            cache_file=cache_file,
            progress=progress,
            concurrency=concurrency,
        )
        return report

    # --- Pinax fetch/ensure operations -----------------------------------

    def ensure_files_dir(self) -> bool:
        """Bootstrap ``pinax-files-dir`` metadata if not already configured.

        Returns True if metadata was set (bibliography marked dirty), False if
        ``pinax-files-dir`` was already present.
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
        cache_file: str | Path | None = None,
        progress: FetchProgress | None = None,
        access: str = "open",
    ) -> dict:
        """Download selected arXiv, published, and supplementary materials for entries.

        Args:
            target: Optional single citation key to fetch. If None, fetch all.
            policy: Optional explicit fetch policy. When provided, overrides the
                library's metadata ``pinax-fetch-policy`` setting.
            dry_run: If True, report what would be fetched without downloading.
            pdf_fetcher: Injectable arXiv PDF fetcher for testing.
            source_fetcher: Injectable arXiv source fetcher for testing.
            published_url_fetcher: Injectable OA PDF URL resolver for testing.
            institutional_url_fetcher: Injectable publisher PDF URL resolver.
            published_pdf_fetcher: Injectable published PDF bytes fetcher.
            supplement_url_fetcher: Injectable supplement URL resolver.
            supplement_pdf_fetcher: Injectable supplement PDF bytes fetcher.
            cache_file: Optional path to a provider-response cache file.
            progress: Optional callback receiving fetch progress events.
            access: Published-material access mode: ``open`` or ``institutional``.

        Returns:
            A dict with ``fetched``, ``skipped``, ``failed`` lists, plus
            ``fetch_policy`` dict reflecting the resolved Pinax fetch policy.
        """
        if access not in {"open", "institutional"}:
            raise ValueError(f"Unknown fetch access mode: {access!r}")
        store = self.files
        if store is None:
            self.ensure_files_dir()
            store = self.files
            if store is None:
                raise ValueError("could not resolve pinax-files-dir after bootstrapping")

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
            cache_file=cache_file,
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
