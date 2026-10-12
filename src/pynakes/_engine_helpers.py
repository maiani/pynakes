"""Internal helpers for the Bibliography engine.

These are standalone module-level utilities extracted from ``engine.py`` to
keep that module under the project's 600-line limit. They are not part of the
public API; importers should use the re-exports in ``engine.py``.
"""

import hashlib
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pynakes._engine_fetch import (
    build_fetch_queue as build_fetch_queue,
)
from pynakes._engine_fetch import (
    run_fetch_loop as run_fetch_loop,
)
from pynakes._engine_source import (
    SourceSnapshot as SourceSnapshot,
)
from pynakes._engine_source import (
    SourceSpan as SourceSpan,
)
from pynakes._engine_source import (
    SpanEdit as SpanEdit,
)
from pynakes._engine_source import (
    _source_block_raw as _source_block_raw,
)
from pynakes._engine_source import (
    apply_span_edits as apply_span_edits,
)
from pynakes._engine_source import (
    snapshot_source_spans as snapshot_source_spans,
)
from pynakes.metadata import FetchPolicy, metadata_value
from pynakes.metadata import metadata_bool as _coerce_metadata_bool
from pynakes.metadata import parse_fetch_policy as _parse_fetch_policy
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


def fingerprint(path: Path, data: bytes | None = None) -> FileFingerprint:
    """Build a ``FileFingerprint`` for the current on-disk state of *path*.

    Pass ``data`` when the bytes were already read, so the digest describes
    exactly the content that was parsed.
    """
    if data is None:
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
    # Count the file's own line breaks at its end, whatever their style, so an
    # LF ending a CRLF file is not taken for a missing one. A file that had no
    # final newline gets none after the appended entry either.
    breaks = _trailing_line_breaks(original_text)
    final = line_ending if breaks else ""
    return original_text + line_ending * max(0, 2 - breaks) + entry_text + final


def _trailing_line_breaks(text: str) -> int:
    """Count the line breaks (``\\r\\n``, ``\\n``, or ``\\r``) ending ``text``."""
    count = 0
    end = len(text)
    while end:
        if text.endswith("\r\n", 0, end):
            end -= 2
        elif text[end - 1] in "\r\n":
            end -= 1
        else:
            break
        count += 1
    return count


def block_removal_span(pristine_text: str, span: SourceSpan) -> SourceSpan:
    """Extend a top-level block's span over its trailing inter-block whitespace.

    Removing only the block's own source span leaves the blank-line gap
    that preceded it *and* the one that followed it back to back, doubling
    the separator. When another block follows, the span is extended over
    that trailing gap so exactly one blank-line separator remains (the one
    that preceded the removed block). At end of file there is no trailing
    gap to fold away, so the block text alone is returned unchanged.

    Used for removed entries and for whole comment blocks a scrub drops, which
    face the same doubled-separator problem.
    """
    end = span.end
    tail = end
    while tail < len(pristine_text) and pristine_text[tail] in " \t\r\n":
        tail += 1
    if tail < len(pristine_text):
        end = tail
    return SourceSpan(span.start, end, pristine_text[span.start : end])


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
) -> Generator[tuple[BibEntry, str | None, bool], None, None]:
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
            yield entry, cast(str | None, sentinel), False


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


def metadata_bool(lib: BibFile, name: str, default: bool) -> bool:
    """Return a boolean metadata value for ``name``, falling back to ``default``.

    A thin ``lib``-aware wrapper over the canonical lookup/coercion pair in
    :mod:`pynakes.metadata`, so the truthy/falsy spellings stay defined once.
    """
    return _coerce_metadata_bool(metadata_value(lib, name), default)


def metadata_fetch_policy(lib: BibFile) -> FetchPolicy:
    """Return the parsed ``pinax-fetch-policy`` for *lib*, or default ``bestpdf``.

    A thin ``lib``-aware wrapper over :func:`pynakes.metadata.parse_fetch_policy`.
    """
    return _parse_fetch_policy(metadata_value(lib, "pinax-fetch-policy"))
