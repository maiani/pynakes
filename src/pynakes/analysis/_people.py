"""The people an entry lists, as the ``authors`` and ``coauthors`` analyses count them.

One reading of an ``author`` field shared by the summary and network APIs in
:mod:`pynakes.analysis`, so a person the ``authors`` section counts is the
same person the co-author network links: each name is normalized to
``Last, First`` form (:func:`pynakes.authors.normalize_name_list`) and compared
brace-free, spaced, and case-folded. ``others`` (and ``et al.``) marks a
truncated list; it is recorded, never counted as a person.

ORCID identifiers are read from the BibLaTeX named data annotation
``author+an:orcid`` (``1="0000-0002-1825-0097"; 3="..."``), whose item numbers
are positions in the author list. They are evidence for reports; they never
merge two names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pynakes._text_utils import entry_year, fold_field_names
from pynakes.authors import normalize_name_list, split_name_list
from pynakes.model import BibEntry

#: The named annotation that carries ORCID iDs for the author list.
ORCID_ANNOTATION = "author+an:orcid"

_YEAR_RE = re.compile(r"\d{4}")
_ORCID_RE = re.compile(r"(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.IGNORECASE)
_ANNOTATION_ITEM_RE = re.compile(r"^\s*(\d+)\s*=\s*\"?\s*([^\"]*?)\s*\"?\s*$")


def fold(value: str) -> str:
    """Return the grouping key of a display value: brace-free, spaced, case-folded."""
    return " ".join(value.replace("{", "").replace("}", "").split()).casefold()


def year_of(entry: BibEntry) -> str | None:
    """Return the entry's four-digit year, as the ``years`` section reads it."""
    match = _YEAR_RE.search(entry_year(entry) or "")
    return match.group(0) if match else None


@dataclass
class EntryPeople:
    """The distinct people one entry lists, in author-list order.

    ``people`` holds ``(key, name, spelling)`` triples: the grouping key, the
    normalized name, and the spelling as written. A person listed twice in one
    entry appears once. ``orcids`` maps keys to the ORCID annotated on them,
    and ``invalid_orcids`` the annotation items that could not be read.
    """

    people: list[tuple[str, str, str]] = field(default_factory=list)
    others: bool = False
    orcids: dict[str, str] = field(default_factory=dict)
    invalid_orcids: list[str] = field(default_factory=list)

    @property
    def keys(self) -> list[str]:
        """Return the grouping keys of the listed people, in list order."""
        return [key for key, _name, _spelling in self.people]


def entry_people(entry: BibEntry) -> EntryPeople:
    """Return the :class:`EntryPeople` of ``entry``'s ``author`` field."""
    folded = fold_field_names(entry.fields)
    result = EntryPeople()
    positions: dict[int, str] = {}
    for position, person in enumerate(split_name_list(folded.get("author") or ""), start=1):
        name = normalize_name_list(person, "jabref").strip()
        if not name:
            continue
        if name == "others":
            result.others = True
            continue
        key = fold(name)
        positions[position] = key
        if key not in {existing for existing, _name, _spelling in result.people}:
            result.people.append((key, name, " ".join(person.split())))
    annotation = folded.get(ORCID_ANNOTATION) or ""
    for item in annotation.split(";"):
        if not item.strip():
            continue
        orcid = _annotation_orcid(item)
        if orcid is None or orcid[0] not in positions:
            result.invalid_orcids.append(item.strip())
            continue
        result.orcids.setdefault(positions[orcid[0]], orcid[1])
    return result


def _annotation_orcid(item: str) -> tuple[int, str] | None:
    """Return ``(position, orcid)`` for one ``N="iD"`` annotation item, or ``None``."""
    match = _ANNOTATION_ITEM_RE.match(item)
    if match is None:
        return None
    orcid = _ORCID_RE.fullmatch(match.group(2).strip())
    if orcid is None:
        return None
    return int(match.group(1)), orcid.group(1).upper()
