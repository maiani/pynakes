"""Internal helpers for the Bibliography engine.

These are standalone module-level utilities extracted from ``engine.py`` to
keep that module under the project's 600-line limit. They are not part of the
public API; importers should use the re-exports in ``engine.py``.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pynakes.fetch_progress import FetchProgress, FetchProgressEvent
from pynakes.metadata import metadata_bool as _coerce_metadata_bool
from pynakes.metadata import metadata_value
from pynakes.model import BibEntry, BibFile, MetadataBlock


@dataclass(frozen=True)
class FileFingerprint:
    """Observed file state used for optimistic-concurrency checks.

    The size, nanosecond modification time, and content digest make a
    ``Bibliography`` reject a commit when its on-disk source changed externally.
    """

    size: int
    mtime_ns: int
    sha256: str


@dataclass
class CommitResult:
    """Outcome of one :meth:`Bibliography.commit` lifecycle transition.

    ``diff`` compares the pre-commit pristine text with the staged output;
    ``modified`` distinguishes a successful no-op commit from one that wrote.
    """

    changed_entries: int
    diff: str
    modified: bool


class ExternalModificationError(Exception):
    """Raised when a bound bibliography's file changed since it was opened."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"File changed on disk since it was opened: {path}")


def snapshot_entries(lib: BibFile) -> dict[int, str | None]:
    """Return a mapping of ``id(entry) → raw_content`` for all entries."""
    return {id(entry): entry.raw_content for entry in lib.entries.values()}


def metadata_bool(lib: BibFile, name: str, default: bool) -> bool:
    """Return a boolean metadata value for ``name``, falling back to ``default``.

    A thin ``lib``-aware wrapper over the canonical lookup/coercion pair in
    :mod:`pynakes.metadata`, so the truthy/falsy spellings stay defined once.
    """
    return _coerce_metadata_bool(metadata_value(lib, name), default)


def read_text(path: Path, encoding: str) -> str:
    """Read *path* as text, substituting replacement characters on error."""
    return path.read_text(encoding=encoding, errors="replace")


def fingerprint(path: Path) -> FileFingerprint:
    """Build a ``FileFingerprint`` for the current on-disk state of *path*."""
    data = path.read_bytes()
    stat = path.stat()
    return FileFingerprint(
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def append_entry_text(
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


def insert_metadata_comment(original_text: str, comment: str, line_ending: str) -> str:
    """Insert a new metadata comment at its namespace's canonical position.

    pynakes-native metadata belongs at the top of the file. JabRef writes its
    ``@Comment{jabref-meta: ...}`` blocks at the bottom, so newly-created
    JabRef projection blocks are appended there.
    """
    if not original_text:
        return comment + line_ending
    if "pynakes-meta:" in comment:
        body = original_text.lstrip("\r\n")
        return comment + line_ending + line_ending + body
    body = original_text.rstrip("\r\n")
    return body + line_ending + line_ending + comment + line_ending


# ---------------------------------------------------------------------------
# Snapshot iteration helper
# ---------------------------------------------------------------------------

_MISSING_SNAPSHOT = object()


def iter_changed_entries(
    entries: list[BibEntry],
    snapshot: dict[int, str | None],
    appended_ids: set[int],
):
    """Yield ``(entry, before, missing)`` for each non-appended entry.

    ``before`` is the snapshotted ``raw_content`` (may be ``None`` if the entry
    had no raw content when snapshotted). ``missing`` is ``True`` when the entry
    was not present in *snapshot* at all — i.e. it appeared after the snapshot
    was taken via a path that bypassed normal staging.
    """
    for entry in entries:
        if id(entry) in appended_ids:
            continue
        sentinel = snapshot.get(id(entry), _MISSING_SNAPSHOT)
        if sentinel is _MISSING_SNAPSHOT:
            yield entry, None, True
        else:
            yield entry, sentinel, False


# ---------------------------------------------------------------------------
# change_plan helper
# ---------------------------------------------------------------------------


def compute_change_plan(pristine_text: str, lib: BibFile) -> dict:
    """Compute the structured change-plan dict for :meth:`~pynakes.engine.Bibliography.change_plan`.

    Compares *pristine_text* (the pre-edit BibTeX source) against *lib* (the
    current in-memory state) and returns a dict with ``summary``, ``entries``,
    and ``metadata`` keys.
    """
    from pynakes.bibtex_parser import parse_bib  # local import avoids top-level cycle

    pristine = parse_bib(pristine_text)
    before_rows = _indexed_entries(pristine)
    after_rows = _indexed_entries(lib)
    before = {token: (index, entry) for token, index, entry in before_rows}
    after = {token: (index, entry) for token, index, entry in after_rows}
    before_duplicate_keys = pristine.entries.duplicate_keys()
    after_duplicate_keys = lib.entries.duplicate_keys()

    def signature(entry: BibEntry) -> tuple[str, tuple[tuple[str, str], ...]]:
        return (entry.type.lower(), tuple(sorted(entry.fields.items())))

    added_tokens = [token for token, _, _ in after_rows if token not in before]
    removed_tokens = [token for token, _, _ in before_rows if token not in after]

    # Pair a removed key with an added key carrying the same record → rename.
    added_by_sig: dict[tuple[str, tuple[tuple[str, str], ...]], list[tuple[str, int]]] = {}
    for token in added_tokens:
        _, entry = after[token]
        added_by_sig.setdefault(signature(entry), []).append(token)
    renamed_to: set[tuple[str, int]] = set()
    renames: list[dict] = []
    plain_removed: list[tuple[str, int]] = []
    for token in removed_tokens:
        before_index, before_entry = before[token]
        candidates = added_by_sig.get(signature(before_entry), [])
        match = next((candidate for candidate in candidates if candidate not in renamed_to), None)
        if match is not None and match not in renamed_to:
            after_index, after_entry = after[match]
            item = {"change": "renamed", "from": before_entry.key, "to": after_entry.key}
            _add_entry_index(item, before_entry.key, before_index, before_duplicate_keys)
            _add_entry_index(
                item, after_entry.key, after_index, after_duplicate_keys, name="to_index"
            )
            renames.append(item)
            renamed_to.add(match)
        else:
            plain_removed.append(token)
    added_tokens = [token for token in added_tokens if token not in renamed_to]

    entries: list[dict] = list(renames)
    entries += [
        _entry_item("added", after[token][1], after[token][0], after_duplicate_keys)
        for token in added_tokens
    ]
    entries += [
        _entry_item("removed", before[token][1], before[token][0], before_duplicate_keys)
        for token in plain_removed
    ]

    modified = 0
    for token, after_index, after_entry in after_rows:
        row = before.get(token)
        if row is None:
            continue
        _, before_entry = row
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
        item: dict = _entry_item("modified", after_entry, after_index, after_duplicate_keys)
        if type_changed:
            item["type"] = {"old": before_entry.type, "new": after_entry.type}
        if fields:
            item["fields"] = fields
        entries.append(item)

    metadata: list[dict] = []
    before_meta, after_meta = pristine.metadata, lib.metadata
    for name in sorted(set(before_meta) | set(after_meta)):
        old = before_meta.get(name)
        new = after_meta.get(name)
        if old != new:
            metadata.append({"key": name, "old": old, "new": new})

    return {
        "summary": {
            "added": len(added_tokens),
            "removed": len(plain_removed),
            "renamed": len(renames),
            "modified": modified,
            "metadata_changed": len(metadata),
        },
        "entries": entries,
        "metadata": metadata,
    }


def _indexed_entries(lib: BibFile) -> list[tuple[tuple[str, int], int, BibEntry]]:
    """Return entries tagged by ``(key, occurrence)`` and absolute entry index."""
    counts: dict[str, int] = {}
    rows: list[tuple[tuple[str, int], int, BibEntry]] = []
    for index, entry in enumerate(lib.entries.values()):
        occurrence = counts.get(entry.key, 0)
        counts[entry.key] = occurrence + 1
        rows.append(((entry.key, occurrence), index, entry))
    return rows


def _entry_item(
    change: str,
    entry: BibEntry,
    index: int,
    duplicate_keys: dict[str, int],
) -> dict:
    item = {"change": change, "key": entry.key}
    _add_entry_index(item, entry.key, index, duplicate_keys)
    return item


def _add_entry_index(
    item: dict,
    key: str,
    index: int,
    duplicate_keys: dict[str, int],
    *,
    name: str = "entry_index",
) -> None:
    if key in duplicate_keys:
        item[name] = index


# ---------------------------------------------------------------------------
# fetch_materials helpers
# ---------------------------------------------------------------------------


def build_fetch_queue(lib: BibFile, target: str | None) -> list[BibEntry]:
    """Resolve the list of entries to fetch, raising on ambiguous keys.

    When *target* is given only that one entry is returned; otherwise all
    entries in *lib* are returned after verifying that no duplicate citation
    keys exist (Pinax material addressing requires unique keys).
    """
    if target is not None:
        entries = list(lib.entries.get_all(target))
        if not entries:
            raise ValueError(f"No entry with key {target!r} in the library")
        if len(entries) > 1:
            raise ValueError(f"Cannot fetch for duplicate key {target!r}")
        return [entries[0]]

    duplicates = lib.entries.duplicate_keys()
    if duplicates:
        instances = lib.entries.duplicate_key_instances()
        parts = []
        for key in sorted(duplicates):
            indices = instances.get(key, [])
            line_refs = f" (entry {', '.join(f'#{i}' for i in indices)})" if indices else ""
            parts.append(f"{key} ×{duplicates[key]}{line_refs}")
        raise ValueError(
            f"Pinax material addressing requires unique citation keys: {'; '.join(parts)}"
        )
    return list(lib.entries.values())


def run_fetch_loop(
    entry_queue: list[BibEntry],
    store: "object",  # FileStore — typed as object to avoid import
    fetch_preprint: bool,
    fetch_source: bool,
    fetch_published: bool,
    dry_run: bool,
    pdf_fetcher: Callable[[str], bytes] | None = None,
    source_fetcher: Callable[[str], bytes] | None = None,
    published_url_fetcher: Callable[[str], str | None] | None = None,
    published_pdf_fetcher: Callable[[str], bytes] | None = None,
    cache_dir: str | Path | None = None,
    progress: FetchProgress | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Iterate *entry_queue* and download materials into *store*.

    For entries with an arXiv id, downloads the preprint PDF and/or source
    bundle. For entries with a DOI, downloads the open-access published PDF
    when ``fetch_published`` is true.

    Returns ``(fetched, skipped, failed)`` lists.
    """
    from pynakes.fetch import (
        ArxivFetchError,
        PublishedPdfFetchError,
        download_arxiv_materials,
        download_published_material,
    )
    from pynakes.importer import entry_arxiv_id

    fetched: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    entry_total = len(entry_queue)
    for index, entry in enumerate(entry_queue, start=1):
        if not entry.key.strip():
            skipped.append({"key": entry.key, "reason": "empty key"})
            _emit_fetch_progress(
                progress,
                FetchProgressEvent(
                    kind="skip",
                    key=entry.key,
                    entry_index=index,
                    entry_total=entry_total,
                    message="empty key",
                ),
            )
            continue

        key = entry.key
        _emit_fetch_progress(
            progress,
            FetchProgressEvent(kind="entry", key=key, entry_index=index, entry_total=entry_total),
        )
        arxiv_id = entry_arxiv_id(entry)
        doi = entry.fields.get("doi", "").strip()
        presence = store.presence_for(key)

        can_fetch_preprint = arxiv_id is not None and fetch_preprint and not presence.preprint_pdf
        can_fetch_source = arxiv_id is not None and fetch_source and not presence.preprint_source
        can_fetch_published = fetch_published and bool(doi) and not presence.published_pdf

        anything_to_fetch = can_fetch_preprint or can_fetch_source or can_fetch_published

        if not anything_to_fetch:
            needs_arxiv = fetch_preprint or fetch_source
            missing_arxiv = needs_arxiv and arxiv_id is None
            missing_doi = fetch_published and not doi
            if missing_arxiv and missing_doi:
                skipped.append({"key": key, "reason": "no arXiv id and no DOI"})
            elif missing_arxiv:
                skipped.append({"key": key, "reason": "no arXiv id"})
            elif missing_doi:
                skipped.append({"key": key, "reason": "no DOI"})
            else:
                skipped.append({"key": key, "reason": "materials already present"})
            _emit_fetch_progress(
                progress,
                FetchProgressEvent(
                    kind="skip",
                    key=key,
                    entry_index=index,
                    entry_total=entry_total,
                    message=skipped[-1]["reason"],
                ),
            )
            continue

        if dry_run:
            skipped.append({"key": key, "reason": "would fetch"})
            _emit_fetch_progress(
                progress,
                FetchProgressEvent(
                    kind="skip",
                    key=key,
                    entry_index=index,
                    entry_total=entry_total,
                    message="would fetch",
                ),
            )
            continue

        # --- Fetch arXiv preprint materials ---
        if can_fetch_preprint or can_fetch_source:
            try:
                result = download_arxiv_materials(
                    store,
                    key,
                    arxiv_id,
                    pdf=can_fetch_preprint,
                    source=can_fetch_source,
                    pdf_fetcher=pdf_fetcher,
                    source_fetcher=source_fetcher,
                    progress=progress,
                )
                if result.pdf_path is not None or result.source_path is not None:
                    fetched.append(result.to_dict())
                if result.source_unavailable:
                    skipped.append(
                        {"key": key, "reason": "no arXiv source archive (PDF-only submission)"}
                    )
            except ArxivFetchError as exc:
                failed.append({"key": key, "error": str(exc)})
                _emit_fetch_progress(
                    progress,
                    FetchProgressEvent(
                        kind="fail",
                        key=key,
                        entry_index=index,
                        entry_total=entry_total,
                        message=str(exc),
                    ),
                )

        # --- Fetch published PDF ---
        if can_fetch_published:
            try:
                pub_result = download_published_material(
                    store,
                    key,
                    doi,
                    url_resolver=published_url_fetcher,
                    pdf_fetcher=published_pdf_fetcher,
                    cache_dir=cache_dir,
                    progress=progress,
                )
                if pub_result.pdf_path is not None:
                    fetched.append(pub_result.to_dict())
                else:
                    skipped.append({"key": key, "reason": "no open-access copy found"})
                    _emit_fetch_progress(
                        progress,
                        FetchProgressEvent(
                            kind="skip",
                            key=key,
                            entry_index=index,
                            entry_total=entry_total,
                            message="no open-access copy found",
                        ),
                    )
            except PublishedPdfFetchError as exc:
                failed.append({"key": key, "error": str(exc)})
                _emit_fetch_progress(
                    progress,
                    FetchProgressEvent(
                        kind="fail",
                        key=key,
                        entry_index=index,
                        entry_total=entry_total,
                        message=str(exc),
                    ),
                )

    return fetched, skipped, failed


def _emit_fetch_progress(progress: FetchProgress | None, event: FetchProgressEvent) -> None:
    if progress is not None:
        progress(event)
