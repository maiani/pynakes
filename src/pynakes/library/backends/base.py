"""Source-neutral records, read protocols, pagination and query filtering.

Construct backends explicitly. Reads never change source records. Native file
references are snapshot-scoped occurrences; Zotero references use instance/item
identity. Neither a citation key nor a DOI is a source record's primary key.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Generic, Protocol, TypeVar

from pynakes.bounded import decode_cursor, encode_cursor, request_digest
from pynakes.model import BibEntry


class SourceError(ValueError):
    """A source is unavailable, malformed, unsupported or inconsistent."""


class SourceUnavailable(SourceError):
    """The explicitly selected source could not be read safely."""


class SourceChanged(SourceError):
    """The source identity or revision differs from the observed snapshot."""


class SourceMissing(SourceError):
    """The requested source occurrence no longer exists."""


class SourceUnsupported(SourceError):
    """The source cannot provide the requested capability or projection."""


@dataclass(frozen=True)
class ItemRef:
    """Source-scoped record identity, independent of the target citation key."""

    source: str
    key: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class Revision:
    """Opaque change token; comparable only inside its entire namespace."""

    source: str
    token: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ReferenceView:
    """Immutable citation projection; unsupported content stays explicit.

    ``native_json`` is populated only by an explicit native expansion. ``fields``
    are BibTeX-ready citation fields, not a lossless replacement for source data.
    """

    ref: ItemRef
    revision: Revision
    native_type: str
    entry_type: str | None
    fields: tuple[tuple[str, str], ...]
    citation_key: str | None = None
    identifiers: tuple[tuple[str, str], ...] = ()
    issues: tuple[str, ...] = ()
    native_json: str | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["fields"] = dict(self.fields)
        if self.native_json is None:
            result.pop("native_json")
        else:
            result["native"] = json.loads(result.pop("native_json"))
        return result


class _Serializable(Protocol):
    def to_dict(self) -> dict: ...


T = TypeVar("T", bound=_Serializable)


@dataclass(frozen=True)
class ReadPage(Generic[T]):
    """A bounded page. ``source_total`` includes skipped non-reference items.

    A page can be empty while ``next_cursor`` is set. ``complete`` describes
    coverage/diagnostics, not exhaustion of pagination. Revisions are observations,
    not a distributed database transaction.
    """

    items: tuple[T, ...]
    revision: Revision
    next_cursor: str | None
    source_total: int
    scanned: int
    skipped: int = 0
    issues: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {
            "items": [x.to_dict() for x in self.items],
            "revision": asdict(self.revision),
            "next_cursor": self.next_cursor,
            "source_total": self.source_total,
            "scanned": self.scanned,
            "skipped": self.skipped,
            "complete": self.complete,
            "issues": list(self.issues),
        }


class LibraryBackend(Protocol):
    """Minimal read boundary; source mutation is deliberately absent."""

    def describe(self) -> dict: ...
    def scan(self, *, limit: int = 50, cursor: str | None = None) -> ReadPage[ReferenceView]: ...
    def get(
        self, ref: ItemRef, *, expected_revision: Revision | None = None, native: bool = False
    ) -> ReferenceView: ...


def _page_start(limit: int, cursor: str | None, revision: Revision, request: str) -> int:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Page limit must be between 1 and 100")
    return decode_cursor(cursor, snapshot=revision.digest, request=request) if cursor else 0


def _next_cursor(
    start: int, count: int, total: int, revision: Revision, request: str
) -> str | None:
    return (
        encode_cursor(offset=start + count, snapshot=revision.digest, request=request)
        if start + count < total
        else None
    )


def search_page(
    backend: LibraryBackend, where: str, *, limit: int = 50, cursor: str | None = None
) -> ReadPage[ReferenceView]:
    """Evaluate the native query grammar over one bounded projection page.

    This is a filtered source page, not a global ranking or match count. Continue
    until no cursor remains to exhaust the source. No Zotero quick-search pushdown
    or implicit full-library scan occurs.
    """
    return _search_page(backend.scan, where, limit=limit, cursor=cursor)


def _search_page(
    scan: Callable[..., ReadPage[ReferenceView]],
    where: str,
    *,
    limit: int,
    cursor: str | None,
) -> ReadPage[ReferenceView]:
    """Filter a scoped scan, retaining its own cursor and freshness contract."""
    from pynakes.query import parse_query

    predicate = parse_query(where)
    scan_cursor = None
    query_digest = request_digest(where=where, limit=limit)
    if cursor:
        try:
            if len(cursor) > 8192:
                raise ValueError("Oversized cursor")
            decoded = json.loads(base64.b64decode(cursor, validate=True))
            if decoded["query"] != query_digest or not isinstance(decoded["cursor"], str):
                raise ValueError("Cursor belongs to another query")
            scan_cursor = decoded["cursor"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Invalid search cursor or changed query") from exc
    page = scan(limit=limit, cursor=scan_cursor)
    next_cursor = (
        base64.b64encode(
            json.dumps({"query": query_digest, "cursor": page.next_cursor}).encode()
        ).decode()
        if page.next_cursor
        else None
    )
    items = tuple(
        r
        for r in page.items
        if r.entry_type is not None
        and predicate.matches(
            BibEntry(key=r.citation_key or "", type=r.entry_type, fields=dict(r.fields))
        )
    )
    return ReadPage(
        items,
        page.revision,
        next_cursor,
        page.source_total,
        page.scanned,
        page.skipped + len(page.items) - len(items),
        page.issues,
    )
