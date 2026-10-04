"""Compact per-entry summaries for scanning several references at once.

A single-key ``ref show`` prints every stored field, which is the right answer
when one entry is already the subject. Deciding *which* of a dozen candidate
keys is the subject is a different question: it needs what the work is, who
wrote it, when, where it appeared, and how to resolve it — for each candidate,
in one pass. :func:`entry_summary` selects exactly those fields, and
:func:`abstract_excerpt` shortens an abstract to a scannable line.

Selection is deterministic and derived only from the fields it is given: no
network access, no heuristics beyond the documented preference orders below,
and no value rewriting.
"""

from collections.abc import Mapping

from pynakes._text_utils import fold_field_names
from pynakes.model import BibEntry

#: Venue-like fields, in preference order. The first one an entry carries is
#: included; the rest are omitted, so an ``@article`` shows its journal and an
#: ``@inproceedings`` its proceedings without either drowning the summary.
VENUE_FIELDS = (
    "journaltitle",
    "journal",
    "booktitle",
    "eventtitle",
    "school",
    "institution",
    "organization",
    "publisher",
    "howpublished",
)

#: Identifier fields, all of which are included when present, because each one
#: is a different way to resolve the same work.
IDENTIFIER_FIELDS = ("doi", "eprint", "isbn", "url")

#: Alternative fields tried in order for the creator and the date. Only the
#: first present alternative appears, under its own field name.
_CREATOR_FIELDS = ("author", "editor")
_DATE_FIELDS = ("year", "date")

#: Default cut-off for :func:`abstract_excerpt`, in characters.
ABSTRACT_EXCERPT_CHARS = 280


def _first_present(fields: Mapping[str, str], names: tuple[str, ...]) -> tuple[str, str] | None:
    for name in names:
        value = fields.get(name)
        if value and value.strip():
            return name, value
    return None


def entry_summary(
    entry: BibEntry,
    fields: Mapping[str, str] | None = None,
    *,
    include_abstract: bool = False,
) -> dict[str, str | None]:
    """Return the triage summary of one entry, as an ordered field mapping.

    The summary holds the title, the first present of
    ``author``/``editor``, the first present of ``year``/``date``, the first
    present :data:`VENUE_FIELDS` entry, and every present
    :data:`IDENTIFIER_FIELDS` entry, in that order. Fields the entry does not
    carry are omitted, and values are returned verbatim.

    Pass ``fields`` to summarize a mapping other than ``entry.fields`` — the
    crossref/xdata-resolved fields, for example. Field names are matched
    case-insensitively and reported in their canonical lowercase spelling, so
    the result is stable regardless of how the source file spells them.

    With ``include_abstract`` the summary always ends with an ``abstract``
    entry, whose value is ``None`` when the entry stores no abstract. That
    distinguishes "this reference has no abstract" from "the abstract was not
    requested", which a caller triaging candidates needs to tell apart.
    """
    source = entry.fields if fields is None else fields
    lookup = fold_field_names(source)

    summary: dict[str, str | None] = {}
    for alternatives in (("title",), _CREATOR_FIELDS, _DATE_FIELDS, VENUE_FIELDS):
        found = _first_present(lookup, alternatives)
        if found is not None:
            summary[found[0]] = found[1]

    for name in IDENTIFIER_FIELDS:
        value = lookup.get(name)
        if value and value.strip():
            summary[name] = value

    if include_abstract:
        abstract = lookup.get("abstract")
        summary["abstract"] = abstract if abstract and abstract.strip() else None

    return summary


def abstract_excerpt(value: str | None, limit: int = ABSTRACT_EXCERPT_CHARS) -> str:
    """Return ``value`` collapsed to one line and cut to ``limit`` characters.

    Runs of whitespace — including the line breaks a wrapped ``.bib`` value
    carries — collapse to single spaces so the result occupies one terminal
    line per entry. A value longer than ``limit`` is cut at that many
    characters and marked with a trailing ellipsis; a shorter one is returned
    whole. An empty or absent value returns the empty string.
    """
    if limit < 0:
        raise ValueError("Abstract excerpt limit must be non-negative")
    collapsed = " ".join((value or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"
