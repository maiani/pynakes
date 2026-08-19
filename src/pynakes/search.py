"""Read-only search over entries in a parsed bibliography.

Search is term-based: whitespace-separated terms are ANDed, quoted phrases stay
together, and a ``field:`` prefix scopes a term. Matching is exact (substring)
by default and optionally fuzzy, and every hit is explained — which field, which
term, exact or fuzzy, how strongly, and the surrounding text. Entry *selection*
is a separate concern handled by the shared ``--where`` grammar in
:mod:`pynakes.query`, which this module accepts as a filter.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pynakes.model import BibEntry, BibFile
from pynakes.query import FUZZY_THRESHOLD, fuzzy_score


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
class FieldMatch:
    """Why one field of an entry matched: which term hit it, how, and how well.

    ``kind`` is ``"exact"`` for a substring hit and ``"fuzzy"`` for a
    similarity hit; ``score`` is 1.0 for exact matches and the normalized
    similarity (see :func:`pynakes.query.fuzzy_score`) otherwise. ``excerpt``
    is the surrounding text, so a caller can show *what* matched without
    re-searching the value.
    """

    field: str
    term: str
    kind: str
    score: float
    excerpt: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the field match to a JSON-friendly dict."""
        return {
            "field": self.field,
            "term": self.term,
            "kind": self.kind,
            "score": round(self.score, 4),
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class SearchResult:
    """One entry matched by :func:`search_entries`.

    ``matched_fields`` names the fields that matched, in first-hit order;
    ``matches`` explains each hit individually, and ``score`` is the weakest
    term score (every term must match, so the weakest one bounds the result).
    """

    key: str
    type: str
    matched_fields: list[str]
    fields: dict[str, str]
    matches: tuple[FieldMatch, ...] = ()
    score: float = 1.0

    def to_dict(self) -> dict[str, object]:
        """Serialize the match to a JSON-friendly dict."""
        return {
            "key": self.key,
            "type": self.type,
            "matched_fields": self.matched_fields,
            "fields": dict(self.fields),
            "score": round(self.score, 4),
            "matches": [match.to_dict() for match in self.matches],
        }


#: Relevance tiers for :func:`_rank_results`, strongest first. A result's rank
#: is the best (lowest) tier among its ``matched_fields``; fields not listed
#: fall in the middle tier, below ``author`` and above the weak free-text
#: fields ``groups``/``abstract``.
_STRONG_FIELD_TIERS = ("key", "title", "author")
_WEAK_FIELDS = frozenset({"groups", "abstract"})
_DEFAULT_TIER = len(_STRONG_FIELD_TIERS)
_WEAK_TIER = _DEFAULT_TIER + 1


def _field_tier(field: str) -> int:
    if field in _STRONG_FIELD_TIERS:
        return _STRONG_FIELD_TIERS.index(field)
    if field in _WEAK_FIELDS:
        return _WEAK_TIER
    return _DEFAULT_TIER


def _rank_results(results: list[SearchResult]) -> list[SearchResult]:
    """Stably sort matches by relevance: strongest matched field first.

    Within a tier, a stronger match score wins, so an exact hit outranks a
    fuzzy one on the same field. Remaining ties keep their relative order, so
    this is a pure reordering of ``results`` — a no-op when every match has the
    same best-matched-field tier and score.
    """
    return sorted(
        results,
        key=lambda result: (
            min(_field_tier(field) for field in result.matched_fields),
            -result.score,
        ),
    )


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
    extra_fields: Iterable[str] | None = None,
    where: Callable[[BibEntry], bool] | None = None,
    case_sensitive: bool = False,
    fuzzy: bool = False,
    limit: int | None = None,
    rank: bool = True,
) -> list[SearchResult]:
    """Return entries whose searchable text matches all query terms.

    Free terms search the citation key, entry type, and stored fields. Fielded
    terms search only their target. ``fields`` restricts stored fields included
    in free-text search and output; ``key`` and ``type`` remain searchable.
    ``extra_fields`` names fields reported in every result regardless of that
    restriction, so a caller can display a field — an abstract, say — without
    widening what the query searches.

    An empty ``query`` selects by predicate alone: every entry accepted by
    ``where`` is returned, with no matched fields and no match explanations,
    in file order. This is the read-only path for the selector grammar —
    "which entries have no DOI" is a question about a set, not a text match —
    and it requires ``where``, since an empty query with no predicate would
    match the whole library and is rejected.

    With ``fuzzy=True`` a term that has no substring hit still matches a field
    whose normalized similarity reaches :data:`pynakes.query.FUZZY_THRESHOLD`,
    which finds misspelled and inflected titles. Every match — exact or fuzzy —
    is explained in :attr:`SearchResult.matches`.

    By default (``rank=True``) matches are ordered by relevance — the
    strongest matched field wins, in the order key > title > author > other
    fields > groups/abstract, then the stronger match score — with remaining
    ties broken by file order. Pass ``rank=False`` to keep the raw file order
    instead (also lets ``limit`` short-circuit the scan once enough matches are
    found).
    """
    if limit is not None and limit < 0:
        raise ValueError("Search limit must be non-negative")

    # An empty query is a predicate-only selection; on its own it would match
    # every entry, so it is only meaningful together with ``where``.
    terms = parse_search_query(query) if query.strip() else []
    if not terms and where is None:
        raise ValueError("Search needs a query or a where predicate")
    # Relevance ranking compares matched fields, so it has no meaning without
    # query terms: a predicate-only selection is always returned in file order.
    rank = rank and bool(terms)

    field_filter = {name.lower() for name in fields} if fields is not None else None
    always = {name.lower() for name in extra_fields or ()}
    results: list[SearchResult] = []

    for entry in lib.entries.values():
        if where is not None and not where(entry):
            continue

        if terms:
            match = _match_entry(entry, terms, field_filter, case_sensitive, fuzzy)
            if match is None:
                continue
            matched_fields, matches, score = match
        else:
            # Selected by predicate: nothing was matched, so nothing is explained.
            matched_fields, matches, score = [], (), 0.0
        results.append(
            SearchResult(
                key=entry.key,
                type=entry.type,
                matched_fields=matched_fields,
                fields=_output_fields(entry, field_filter, always),
                matches=matches,
                score=score,
            )
        )
        if limit is not None and not rank and len(results) >= limit:
            break

    if rank:
        results = _rank_results(results)
        if limit is not None:
            results = results[:limit]

    return results


def _output_fields(
    entry: BibEntry, field_filter: set[str] | None, always: Iterable[str] = ()
) -> dict[str, str]:
    if field_filter is None:
        return dict(entry.fields)
    reported = field_filter.union(always)
    return {name: value for name, value in entry.fields.items() if name.lower() in reported}


def _match_entry(
    entry: BibEntry,
    terms: list[SearchTerm],
    field_filter: set[str] | None,
    case_sensitive: bool,
    fuzzy: bool,
) -> tuple[list[str], tuple[FieldMatch, ...], float] | None:
    """Return the matched fields, their explanations, and the weakest term score."""
    matched: list[str] = []
    explanations: list[FieldMatch] = []
    score = 1.0
    for term in terms:
        hits = _term_matches(entry, term, field_filter, case_sensitive, fuzzy)
        if not hits:
            return None
        score = min(score, max(hit.score for hit in hits))
        explanations.extend(hits)
        for hit in hits:
            if hit.field not in matched:
                matched.append(hit.field)
    return matched, tuple(explanations), score


def _term_matches(
    entry: BibEntry,
    term: SearchTerm,
    field_filter: set[str] | None,
    case_sensitive: bool,
    fuzzy: bool,
) -> list[FieldMatch]:
    hits: list[FieldMatch] = []
    for field, value in _candidate_values(entry, term.field, field_filter):
        position = _find(value, term.value, case_sensitive=case_sensitive)
        if position is not None:
            hits.append(
                FieldMatch(
                    field=field,
                    term=term.value,
                    kind="exact",
                    score=1.0,
                    excerpt=_excerpt(value, position, position + len(term.value)),
                )
            )
            continue
        if not fuzzy:
            continue
        score = fuzzy_score(value, term.value)
        if score >= FUZZY_THRESHOLD:
            hits.append(
                FieldMatch(
                    field=field,
                    term=term.value,
                    kind="fuzzy",
                    score=score,
                    excerpt=_excerpt(value, 0, len(value)),
                )
            )
    return hits


def _candidate_values(
    entry: BibEntry, field: str | None, field_filter: set[str] | None
) -> list[tuple[str, str]]:
    if field == "key":
        return [("key", entry.key)]
    if field == "type":
        return [("type", entry.type)]
    if field is not None:
        normalized = field.lower()
        if field_filter is not None and normalized not in field_filter:
            return []
        value = next((v for k, v in entry.fields.items() if k.lower() == normalized), None)
        return [(normalized, value)] if value is not None else []

    values = [("key", entry.key), ("type", entry.type)]
    values.extend(
        (name, value)
        for name, value in entry.fields.items()
        if field_filter is None or name.lower() in field_filter
    )
    return values


def _find(haystack: str, needle: str, *, case_sensitive: bool) -> int | None:
    """Return where ``needle`` starts in ``haystack``, or ``None``."""
    if case_sensitive:
        position = haystack.find(needle)
    else:
        position = haystack.casefold().find(needle.casefold())
    return None if position < 0 else position


#: Context kept on each side of a match in :attr:`FieldMatch.excerpt`.
_EXCERPT_CONTEXT = 30


def _excerpt(value: str, start: int, end: int) -> str:
    """Return the matched span of ``value`` with a little surrounding context."""
    left = max(0, start - _EXCERPT_CONTEXT)
    right = min(len(value), end + _EXCERPT_CONTEXT)
    text = " ".join(value[left:right].split())
    return f"{'…' if left else ''}{text}{'…' if right < len(value) else ''}"
