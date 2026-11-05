"""Required fields per entry type, for each supported dialect.

The tables are transcriptions of the formats' own specifications, kept apart
from the checks in :mod:`pynakes.lint` that read them: they are reference data
with a citable source, they change only when a specification does, and
interactive entry editing consults them through the same function so prompting
and linting cannot disagree about what an entry type needs.

BibLaTeX requirements and entry-type aliases follow the official BibLaTeX
manual on CTAN, section 2.1 "Entry Types":
https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf
"""

from __future__ import annotations

RequiredRules = dict[str, list[tuple[str, ...]]]

# Required fields by entry type. Each requirement is a tuple of acceptable field
# names (any one satisfies it), to tolerate compatibility aliases such as
# journal/journaltitle, year/date, and school/institution.
_BIBTEX_REQUIRED: RequiredRules = {
    "article": [("author",), ("title",), ("journal", "journaltitle"), ("year", "date")],
    "book": [("author", "editor"), ("title",), ("publisher",), ("year", "date")],
    "inbook": [("author", "editor"), ("title",), ("publisher",), ("year", "date")],
    "incollection": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "inproceedings": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "conference": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "manual": [("title",)],
    "phdthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "mastersthesis": [("author",), ("title",), ("school", "institution"), ("year", "date")],
    "thesis": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "techreport": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "unpublished": [("author",), ("title",), ("note",)],
}

_BIBLATEX_REQUIRED: RequiredRules = {
    # BibLaTeX default data model, section 2.1.1 "Entry Types".
    # Source of truth: the official BibLaTeX manual from CTAN, section 2.1:
    # https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf
    "article": [("author",), ("title",), ("journaltitle", "journal"), ("year", "date")],
    "book": [("author",), ("title",), ("year", "date")],
    "mvbook": [("author",), ("title",), ("year", "date")],
    "inbook": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "booklet": [("author", "editor"), ("title",), ("year", "date")],
    "collection": [("editor",), ("title",), ("year", "date")],
    "mvcollection": [("editor",), ("title",), ("year", "date")],
    "incollection": [("author",), ("title",), ("editor",), ("booktitle",), ("year", "date")],
    "dataset": [("author", "editor"), ("title",), ("year", "date")],
    "manual": [("author", "editor"), ("title",), ("year", "date")],
    "misc": [("author", "editor"), ("title",), ("year", "date")],
    "online": [("author", "editor"), ("title",), ("year", "date"), ("doi", "eprint", "url")],
    "patent": [("author",), ("title",), ("number",), ("year", "date")],
    "periodical": [("editor",), ("title",), ("year", "date")],
    "proceedings": [("title",), ("year", "date")],
    "mvproceedings": [("title",), ("year", "date")],
    "inproceedings": [("author",), ("title",), ("booktitle",), ("year", "date")],
    "report": [("author",), ("title",), ("type",), ("institution", "school"), ("year", "date")],
    "thesis": [("author",), ("title",), ("type",), ("institution", "school"), ("year", "date")],
    "unpublished": [("author",), ("title",), ("year", "date")],
}

_BIBLATEX_REQUIREMENT_ALIASES: dict[str, str] = {
    # Soft aliases from the BibLaTeX manual, section 2.1.1.
    "bookinbook": "inbook",
    "suppbook": "inbook",
    "suppcollection": "incollection",
    "suppperiodical": "article",
    "reference": "collection",
    "mvreference": "mvcollection",
    "inreference": "incollection",
    "review": "article",
    "software": "misc",
    # Hard aliases from the BibLaTeX manual, section 2.1.2. These are resolved by biber.
    "conference": "inproceedings",
    "electronic": "online",
    "www": "online",
}

_BIBLATEX_ALIAS_REQUIRED: RequiredRules = {
    "mastersthesis": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "phdthesis": [("author",), ("title",), ("institution", "school"), ("year", "date")],
    "techreport": [("author",), ("title",), ("institution", "school"), ("year", "date")],
}


def required_field_rules(entry_type: str, dialect: str) -> tuple[tuple[str, ...], ...]:
    """Return built-in required fields for ``entry_type`` in ``dialect``.

    Each returned tuple contains interchangeable field names, any one of which
    satisfies that requirement. The immutable result is also used by
    interactive entry editing so prompting and lint validation share one source
    of truth.

    For BibLaTeX, derived from the official BibLaTeX manual on CTAN, section 2.1:
    https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf
    """
    etype = entry_type.lower()
    if dialect != "biblatex":
        return tuple(_BIBTEX_REQUIRED.get(etype, []))
    if etype in _BIBLATEX_ALIAS_REQUIRED:
        return tuple(_BIBLATEX_ALIAS_REQUIRED[etype])
    return tuple(_BIBLATEX_REQUIRED.get(_BIBLATEX_REQUIREMENT_ALIASES.get(etype, etype), []))
