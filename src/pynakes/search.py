"""Read-only search over entries in a parsed bibliography."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pynakes.model import BibEntry, BibFile


@dataclass(frozen=True)
class SearchTerm:
    """One compiled search term.

    ``field`` is ``None`` for whole-entry text search, or a lower-case field
    name. The special field names ``key`` and ``type`` target the citation key
    and entry type.
    """

    value: str
    field: str | None = None


@dataclass(frozen=True)
class SearchResult:
    """One entry matched by :func:`search_entries`."""

    key: str
    type: str
    matched_fields: list[str]
    fields: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        """Serialize the match to a JSON-friendly dict."""
        return {
            "key": self.key,
            "type": self.type,
            "matched_fields": self.matched_fields,
            "fields": dict(self.fields),
        }


def parse_search_query(query: str) -> list[SearchTerm]:
    """Parse a free-text search query.

    Terms are whitespace-separated and ANDed. Quoted phrases stay together.
    Prefix a term with ``field:`` to search only that field, for example
    ``title:learning`` or ``author:"Jane Example"``. The prefixes ``key:`` and
    ``type:`` target citation keys and entry types. Escapes and quote handling
    follow shell-like :mod:`shlex` rules.

    Raises:
        ValueError: if the query is empty or has malformed quoting.
    """
    try:
        parts = shlex.split(query)
    except ValueError as exc:
        raise ValueError(f"Invalid search query: {exc}") from exc
    if not parts:
        raise ValueError("Search query must not be empty")

    terms: list[SearchTerm] = []
    for part in parts:
        field, sep, value = part.partition(":")
        if sep and field and value:
            terms.append(SearchTerm(value=value, field=field.lower()))
        else:
            terms.append(SearchTerm(value=part))
    return terms


def search_entries(
    lib: BibFile,
    query: str,
    *,
    fields: Iterable[str] | None = None,
    where: Callable[[BibEntry], bool] | None = None,
    case_sensitive: bool = False,
    limit: int | None = None,
) -> list[SearchResult]:
    """Return entries whose searchable text matches all query terms.

    Free terms search the citation key, entry type, and stored fields. Fielded
    terms search only their target. ``fields`` restricts stored fields included
    in free-text search and output; ``key`` and ``type`` remain searchable.
    """
    if limit is not None and limit < 0:
        raise ValueError("Search limit must be non-negative")

    terms = parse_search_query(query)
    field_filter = {name.lower() for name in fields} if fields is not None else None
    results: list[SearchResult] = []

    for entry in lib.entries.values():
        if where is not None and not where(entry):
            continue

        match = _match_entry(entry, terms, field_filter, case_sensitive)
        if match is None:
            continue
        results.append(
            SearchResult(
                key=entry.key,
                type=entry.type,
                matched_fields=match,
                fields=_output_fields(entry, field_filter),
            )
        )
        if limit is not None and len(results) >= limit:
            break

    return results


def _output_fields(entry: BibEntry, field_filter: set[str] | None) -> dict[str, str]:
    if field_filter is None:
        return dict(entry.fields)
    return {name: value for name, value in entry.fields.items() if name.lower() in field_filter}


def _match_entry(
    entry: BibEntry,
    terms: list[SearchTerm],
    field_filter: set[str] | None,
    case_sensitive: bool,
) -> list[str] | None:
    matched: list[str] = []
    for term in terms:
        fields = _term_matches(entry, term, field_filter, case_sensitive)
        if not fields:
            return None
        for field in fields:
            if field not in matched:
                matched.append(field)
    return matched


def _term_matches(
    entry: BibEntry,
    term: SearchTerm,
    field_filter: set[str] | None,
    case_sensitive: bool,
) -> list[str]:
    candidates = _candidate_values(entry, term.field, field_filter)
    return [
        field
        for field, value in candidates
        if _contains(value, term.value, case_sensitive=case_sensitive)
    ]


def _candidate_values(
    entry: BibEntry, field: str | None, field_filter: set[str] | None
) -> list[tuple[str, str]]:
    if field == "key":
        return [("key", entry.key)]
    if field == "type":
        return [("type", entry.type)]
    if field is not None:
        if field_filter is not None and field not in field_filter:
            return []
        value = entry.fields.get(field)
        return [(field, value)] if value is not None else []

    values = [("key", entry.key), ("type", entry.type)]
    values.extend(
        (name, value)
        for name, value in entry.fields.items()
        if field_filter is None or name.lower() in field_filter
    )
    return values


def _contains(haystack: str, needle: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return needle in haystack
    return needle.casefold() in haystack.casefold()
