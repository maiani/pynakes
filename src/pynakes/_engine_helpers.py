"""Internal helpers for the Bibliography engine.

These are standalone module-level utilities extracted from ``engine.py`` to
keep that module under the project's 600-line limit. They are not part of the
public API; importers should use the re-exports in ``engine.py``.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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
    """Return a boolean metadata value, falling back to ``default``."""
    for key, value in lib.metadata.items():
        if key.strip().lower() == name.strip().lower():
            stripped = value.rstrip(";").strip().lower()
            if stripped in {"1", "true", "yes", "on", "enabled"}:
                return True
            if stripped in {"0", "false", "no", "off", "disabled"}:
                return False
            return default
    return default


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
    """Append a new metadata comment at the file end (the canonical position).

    JabRef writes its ``@Comment{...-meta: ...}`` blocks at the bottom of the
    file, so a newly-created block is appended there — separated from the
    preceding content by one blank line — rather than prepended.
    """
    if not original_text:
        return comment + line_ending
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
    before = {entry.key: entry for entry in pristine.entries.values()}
    after = {entry.key: entry for entry in lib.entries.values()}

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
    before_meta, after_meta = pristine.metadata, lib.metadata
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
        keys = ", ".join(sorted(duplicates))
        raise ValueError(f"Pinax material addressing requires unique citation keys: {keys}")
    return list(lib.entries.values())


def run_fetch_loop(
    entry_queue: list[BibEntry],
    store: "object",  # FileStore — typed as object to avoid import
    fetch_preprint: bool,
    fetch_source: bool,
    dry_run: bool,
    pdf_fetcher: Callable[[str], bytes] | None,
    source_fetcher: Callable[[str], bytes] | None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Iterate *entry_queue* and download arXiv materials into *store*.

    Returns ``(fetched, skipped, failed)`` lists.
    """
    from pynakes.fetch import ArxivFetchError, download_arxiv_materials  # local import
    from pynakes.importer import entry_arxiv_id  # local import

    fetched: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for entry in entry_queue:
        if not entry.key.strip():
            skipped.append({"key": entry.key, "reason": "empty key"})
            continue

        arxiv_id = entry_arxiv_id(entry)
        if arxiv_id is None:
            skipped.append({"key": entry.key, "reason": "no arXiv id"})
            continue

        presence = store.presence_for(entry.key)
        all_present = True
        if fetch_preprint and not presence.preprint_pdf:
            all_present = False
        if fetch_source and not presence.preprint_source:
            all_present = False
        if all_present:
            skipped.append({"key": entry.key, "reason": "materials already present"})
            continue

        if dry_run:
            skipped.append({"key": entry.key, "reason": "would fetch (use --dry-run to preview)"})
            continue

        try:
            result = download_arxiv_materials(
                store,
                entry.key,
                arxiv_id,
                pdf=fetch_preprint,
                source=fetch_source,
                pdf_fetcher=pdf_fetcher,
                source_fetcher=source_fetcher,
            )
            fetched.append(result.to_dict())
        except ArxivFetchError as exc:
            failed.append({"key": entry.key, "error": str(exc)})

    return fetched, skipped, failed
