"""Bounded reads: field projection, text limits, and snapshot-checked pages.

A caller with a limited budget — an agent's context window, a terminal, a
network response — needs to read a selection of entries in pieces and still be
able to tell three situations apart:

* **missing** — the bibliography has no value for something that was asked for;
* **omitted** — a value exists but was left out on request (a field outside
  ``select``) or cut short (a value longer than ``max_chars``);
* **not yet read** — the selection continues on a later page.

This module holds the primitives shared by every bounded read (``ref show
--key``, ``ref show --where``, ``search``): :func:`project_fields` selects and
truncates field values and reports what it left out, and :func:`paginate`
slices a deterministic sequence into pages whose cursors carry a digest of the
snapshot they were issued for. Resuming a cursor against a changed library is
refused (:class:`StaleCursorError`) rather than silently skipping or repeating
entries.

Limits count characters of the stored source text — never model-dependent
tokens — and truncation never rewrites a value beyond cutting it: the returned
text is a prefix of the stored value.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

__all__ = [
    "CursorError",
    "FieldProjection",
    "Page",
    "StaleCursorError",
    "TruncatedValue",
    "decode_cursor",
    "encode_cursor",
    "paginate",
    "parse_field_selection",
    "project_fields",
    "request_digest",
    "truncate_text",
]

T = TypeVar("T")

#: Prefix of every cursor this version issues; a later format gets a new one.
_CURSOR_PREFIX = "c1."
#: Hex digits kept from the snapshot and request digests inside a cursor.
_DIGEST_CHARS = 16


class CursorError(ValueError):
    """A cursor is malformed, or belongs to a different request."""


class StaleCursorError(Exception):
    """A cursor was issued for a snapshot of the library that no longer exists."""

    def __init__(self, issued: str, current: str | None) -> None:
        self.issued = issued
        self.current = current
        super().__init__(
            "The library changed since this cursor was issued; "
            "restart from the first page to read the current snapshot"
        )


# --- text and field projection ------------------------------------------------


@dataclass(frozen=True)
class TruncatedValue:
    """One value cut by ``max_chars``: its stored length and the length returned."""

    length: int
    returned: int

    def to_dict(self) -> dict[str, int]:
        """Serialize to a JSON-friendly dict."""
        return {"length": self.length, "returned": self.returned}


def truncate_text(value: str, max_chars: int | None) -> tuple[str, TruncatedValue | None]:
    """Return ``value`` cut to ``max_chars`` characters, and how it was cut.

    The result is always a prefix of ``value``; nothing is appended, so the
    returned text stays source data. The second item is ``None`` when the
    value was returned whole.
    """
    if max_chars is None or len(value) <= max_chars:
        return value, None
    return value[:max_chars], TruncatedValue(length=len(value), returned=max_chars)


@dataclass(frozen=True)
class FieldProjection:
    """The fields of one entry as a bounded read returns them.

    ``fields`` maps each returned field to its (possibly truncated) value, or to
    ``None`` for a requested field the entry does not carry. ``missing`` names
    those requested-but-absent fields; ``omitted`` names stored fields left out
    because they were not selected; ``truncated`` describes every value that was
    cut by the text limit.
    """

    fields: dict[str, str | None]
    missing: list[str] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)
    truncated: dict[str, TruncatedValue] = field(default_factory=dict)


def parse_field_selection(values: Iterable[str] | None) -> tuple[str, ...] | None:
    """Split repeated/comma-separated field names into a lower-case selection.

    Returns ``None`` when nothing was given (every field is selected). Names
    keep the order given; a repeated name appears once.

    Raises:
        ValueError: if values were given but name no field.
    """
    if values is None:
        return None
    names: list[str] = []
    for value in values:
        for name in value.split(","):
            lowered = name.strip().lower()
            if lowered and lowered not in names:
                names.append(lowered)
    if not names:
        raise ValueError("A field selection needs at least one field name")
    return tuple(names)


def project_fields(
    fields: Mapping[str, str],
    select: Sequence[str] | None = None,
    max_chars: int | None = None,
) -> FieldProjection:
    """Select and truncate one entry's fields.

    With ``select`` (lower-case names, as :func:`parse_field_selection`
    returns them) only those fields are returned, in that order, matched
    case-insensitively and reported under their stored spelling; a selected
    field the entry lacks is returned as ``None`` and listed in ``missing``.
    Without it every stored field is returned in source order.
    """
    if max_chars is not None and max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    truncated: dict[str, TruncatedValue] = {}

    def bounded(name: str, value: str) -> str:
        text, cut = truncate_text(value, max_chars)
        if cut is not None:
            truncated[name] = cut
        return text

    if select is None:
        return FieldProjection(
            fields={name: bounded(name, value) for name, value in fields.items()},
            truncated=truncated,
        )

    by_lower: dict[str, str] = {}
    for name in fields:
        by_lower.setdefault(name.lower(), name)
    selected: dict[str, str | None] = {}
    missing: list[str] = []
    for name in select:
        stored = by_lower.get(name)
        if stored is None:
            selected[name] = None
            missing.append(name)
        else:
            selected[stored] = bounded(stored, fields[stored])
    wanted = set(select)
    omitted = [name for name in fields if name.lower() not in wanted]
    return FieldProjection(selected, missing, omitted, truncated)


# --- pagination -----------------------------------------------------------------


def request_digest(**parts: object) -> str:
    """Return a short, stable digest identifying one read request.

    A cursor carries it so that a cursor from one selection cannot be replayed
    against another. Pass every part that decides *which* items are read and in
    what order — not the projection or the limits, which may change between
    pages.
    """
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def encode_cursor(*, snapshot: str | None, request: str, offset: int) -> str:
    """Return the opaque cursor that resumes ``request`` at ``offset``."""
    payload = {
        "o": offset,
        "r": request,
        "s": (snapshot or "")[:_DIGEST_CHARS],
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_cursor(cursor: str, *, snapshot: str | None, request: str) -> int:
    """Return the offset a cursor resumes at, after checking it still applies.

    Raises:
        CursorError: if the cursor is malformed or was issued for another request.
        StaleCursorError: if the library changed since the cursor was issued.
    """
    token = cursor.strip()
    if not token.startswith(_CURSOR_PREFIX):
        raise CursorError("Unrecognized cursor; pass a next_cursor value exactly as returned")
    body = token[len(_CURSOR_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise CursorError("Malformed cursor; pass a next_cursor value exactly as returned") from exc
    if not isinstance(payload, dict):
        raise CursorError("Malformed cursor; pass a next_cursor value exactly as returned")
    offset, issued_request, issued_snapshot = payload.get("o"), payload.get("r"), payload.get("s")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise CursorError("Malformed cursor; pass a next_cursor value exactly as returned")
    if not isinstance(issued_request, str) or not isinstance(issued_snapshot, str):
        raise CursorError("Malformed cursor; pass a next_cursor value exactly as returned")
    # A changed library is reported first: restarting is the answer either way.
    if issued_snapshot != (snapshot or "")[:_DIGEST_CHARS]:
        raise StaleCursorError(issued_snapshot, snapshot)
    if issued_request != request:
        raise CursorError(
            "This cursor belongs to a different selection; resume with the same "
            "selection that returned it"
        )
    return offset


@dataclass(frozen=True)
class Page:
    """Where one page sits in its selection, and how to read the next one.

    ``total`` counts every item the selection holds in this snapshot, so
    ``offset + returned == total`` exactly when the page is the last one;
    ``next_cursor`` is ``None`` then and ``complete`` is ``True``.
    """

    offset: int
    limit: int | None
    returned: int
    total: int
    next_cursor: str | None

    @property
    def complete(self) -> bool:
        """Whether this page reaches the end of the selection."""
        return self.next_cursor is None

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON-friendly dict."""
        return {
            "offset": self.offset,
            "limit": self.limit,
            "returned": self.returned,
            "total": self.total,
            "complete": self.complete,
            "next_cursor": self.next_cursor,
        }


def paginate(
    items: Sequence[T],
    *,
    limit: int | None,
    cursor: str | None,
    snapshot: str | None,
    request: str,
) -> tuple[list[T], Page]:
    """Return one page of ``items`` and its :class:`Page` description.

    ``items`` must be the whole selection in a deterministic order for this
    snapshot; the page starts at the cursor's offset (or the beginning) and
    holds at most ``limit`` items (all remaining items when ``limit`` is
    ``None``). ``limit=0`` reads no items and only reports ``total``, with a
    cursor at the same offset. A cursor past the end yields an empty, complete
    page.

    Raises:
        ValueError: if ``limit`` is negative.
        CursorError: if the cursor is malformed or from another request.
        StaleCursorError: if the snapshot changed since the cursor was issued.
    """
    if limit is not None and limit < 0:
        raise ValueError("A page limit must not be negative")
    offset = decode_cursor(cursor, snapshot=snapshot, request=request) if cursor else 0
    end = len(items) if limit is None else min(len(items), offset + limit)
    page = list(items[offset:end]) if offset < len(items) else []
    next_cursor = (
        encode_cursor(snapshot=snapshot, request=request, offset=end) if end < len(items) else None
    )
    return page, Page(
        offset=offset,
        limit=limit,
        returned=len(page),
        total=len(items),
        next_cursor=next_cursor,
    )
