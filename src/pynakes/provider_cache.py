"""Provider-response cache, in memory by default and on disk only when asked.

Caching to disk is opt-in. A ``--online`` run that was not given
``--cache-file`` memoizes provider responses for the life of the process and
discards them with it, so it leaves nothing in the user's folder — the same rule
the rest of pynakes follows for network access, applied to disk. Memoizing still
pays for itself within a single run, which asks the same providers about the same
identifier more than once.

Given a path, the cache is exactly one JSONL file. Records are append-only
lines::

    {"body": "...", "format": "bib", "id": "10.5555/example", "namespace": "doi"}

A later record for the same ``(namespace, id, format)`` supersedes an earlier
one, so refreshing an entry is an append rather than a rewrite. The file is
compacted in place once it holds substantially more lines than live records. A
truncated final line — the only tear a single append can produce — is skipped on
load instead of raising, because a cache miss is always recoverable.

Identifiers are stored in plain text, so the file is readable and greppable,
covered by one ``.gitignore`` line, and removable with one ``rm``.

Nothing here expires a record. A cache is a snapshot the caller asked to keep,
and provider metadata does change, so a long-lived cache should be deleted (or
pointed somewhere disposable) rather than trusted indefinitely.
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from pynakes._atomic import match_mode, replace_file

CACHE_FORMATS = ("json", "bib", "xml")

# Compaction fires once the file carries more than this multiple of the live
# record count, plus a small constant so tiny caches are not rewritten per put.
_COMPACT_FACTOR = 2
_COMPACT_SLACK = 32

_RecordKey = tuple[str, str, str]


def _check_format(fmt: str) -> str:
    if fmt not in CACHE_FORMATS:
        raise ValueError(f"Unsupported provider cache format: {fmt!r}")
    return fmt


def _record_key(record: dict[str, str]) -> _RecordKey:
    return (record["namespace"], record["id"].lower(), record["format"])


def _encode(record: dict[str, str]) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def _decode(line: str) -> dict[str, str] | None:
    """Parse one stored line, returning ``None`` for anything unusable."""
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    fields = ("namespace", "id", "format", "body")
    if not all(isinstance(record.get(field), str) for field in fields):
        return None
    if record["format"] not in CACHE_FORMATS:
        return None
    return {field: record[field] for field in fields}


class ProviderCache:
    """Append-only store of provider responses, optionally backed by a file.

    One instance owns one file, or no file at all when ``path`` is ``None`` — in
    which case it is a plain in-process memo that writes nothing. Construct via
    :func:`open_cache` rather than directly, so a process shares a single
    instance (and therefore a single read) per cache path.
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._records: dict[_RecordKey, dict[str, str]] = {}
        self._lines = 0
        self._lock = threading.Lock()
        self._load()

    # --- lookup -----------------------------------------------------------

    def get(self, namespace: str, identifier: str, fmt: str = "json") -> str | None:
        """Return the cached body for one identifier, or ``None`` when absent."""
        with self._lock:
            record = self._records.get((namespace, identifier.lower(), _check_format(fmt)))
            return None if record is None else record["body"]

    def put(self, namespace: str, identifier: str, fmt: str, body: str) -> None:
        """Store one provider response, superseding any earlier copy."""
        key = (namespace, identifier.lower(), _check_format(fmt))
        with self._lock:
            existing = self._records.get(key)
            if existing is not None and existing["body"] == body:
                return
            record = {"namespace": namespace, "id": identifier, "format": fmt, "body": body}
            self._records[key] = record
            self._append(record)

    def drop(self, namespace: str, identifier: str, fmt: str) -> bool:
        """Forget one cached response; returns whether anything was cached."""
        key = (namespace, identifier.lower(), _check_format(fmt))
        with self._lock:
            if self._records.pop(key, None) is None:
                return False
            self._compact()
            return True

    # --- maintenance ------------------------------------------------------

    def stats(self) -> dict[str, object]:
        """Describe what this cache currently holds."""
        with self._lock:
            by_namespace: dict[str, int] = {}
            for namespace, _, _ in self._records:
                by_namespace[namespace] = by_namespace.get(namespace, 0) + 1
            on_disk = self.path is not None and self.path.is_file()
            return {
                "path": None if self.path is None else str(self.path),
                "exists": on_disk,
                "records": len(self._records),
                "bytes": self.path.stat().st_size if on_disk else 0,
                "namespaces": dict(sorted(by_namespace.items())),
            }

    def clear(self) -> int:
        """Remove the cache file, returning how many records it held."""
        with self._lock:
            removed = len(self._records)
            self._records.clear()
            self._lines = 0
            if self.path is not None:
                self.path.unlink(missing_ok=True)
            return removed

    def compact(self) -> int:
        """Rewrite the file with one line per live record; returns lines saved."""
        with self._lock:
            saved = self._lines - len(self._records)
            self._compact()
            return max(saved, 0)

    # --- storage ----------------------------------------------------------

    def _load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        with self.path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                self._lines += 1
                record = _decode(line)
                if record is not None:
                    self._records[_record_key(record)] = record

    def _append(self, record: dict[str, str]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_encode(record) + "\n")
        self._lines += 1
        if self._lines > _COMPACT_FACTOR * len(self._records) + _COMPACT_SLACK:
            self._compact()

    def _compact(self) -> None:
        if self.path is None:
            return
        if not self._records:
            self.path.unlink(missing_ok=True)
            self._lines = 0
            return
        text = "".join(_encode(record) + "\n" for _, record in sorted(self._records.items()))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(self.path, text)
        self._lines = len(self._records)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",  # records end in "\n"; no CRLF translation on Windows
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    )
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            tmp.write(text)
            tmp.flush()
        match_mode(tmp_path, path)
        replace_file(tmp_path, path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


# --- process-wide instances -------------------------------------------------

_INSTANCES: dict[Path | None, ProviderCache] = {}
_INSTANCES_LOCK = threading.Lock()


def open_cache(location: str | Path | None) -> ProviderCache:
    """Return the cache at ``location``, or the in-process memo when ``None``.

    ``None`` — no ``--cache-file`` — is not "no cache": it is a memo that writes
    nothing to disk, so a run still asks each provider about a given identifier
    once and still leaves the user's folder untouched.

    Instances are memoized per path, so a single ``--online`` run reads a cache
    file once no matter how many identifiers it looks up — including when
    those lookups run concurrently across worker threads (see
    ``verify``/``enrich``'s ``--concurrency``): construction and every access
    below are guarded by locks, since :class:`ProviderCache` itself has no
    notion of a single caller.
    """
    path = None if location is None else Path(location).expanduser()
    if path is not None and path.is_dir():
        raise ValueError(f"Provider cache path is a directory, not a file: {path}")
    with _INSTANCES_LOCK:
        cache = _INSTANCES.get(path)
        if cache is None:
            cache = ProviderCache(path)
            _INSTANCES[path] = cache
    return cache


def reset_instances() -> None:
    """Forget memoized instances. Test seam; a CLI process never needs this."""
    _INSTANCES.clear()
