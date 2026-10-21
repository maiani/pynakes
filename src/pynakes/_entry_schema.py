"""Field suggestions for entry creation, not an exhaustive style data model.

Required fields remain owned by ``_lint_required``. These optional suggestions
cover common editing fields from the BibTeX and BibLaTeX entry types; unknown
fields are always retained. Custom bibliography styles may use other fields.
"""

from pynakes._lint_required import _BIBLATEX_REQUIREMENT_ALIASES

_BIBTEX = {
    "article": "volume number pages month note",
    "book": "editor volume number series address edition month note",
    "booklet": "author title howpublished address month year note",
    "inbook": "chapter pages volume number series type address edition month note",
    "incollection": "editor publisher volume number series type chapter pages address edition month note",
    "inproceedings": "editor volume number series pages address month organization publisher note",
    "manual": "author organization address edition month year note",
    "mastersthesis": "type address month note",
    "phdthesis": "type address month note",
    "thesis": "type address month note",
    "proceedings": "title year editor volume number series address month organization publisher note",
    "techreport": "type number address month note",
    "misc": "author title howpublished month year note",
    "unpublished": "month year note",
}
_BIBLATEX = {
    "article": "subtitle translator annotator commentator version volume number issue series pages eid month note issn",
    "book": "editor subtitle translator annotator commentator volume part edition series number publisher location isbn pagetotal note",
    "mvbook": "editor subtitle translator edition volumes series number publisher location isbn note",
    "inbook": "editor translator subtitle bookauthor booksubtitle volume part edition series number publisher location chapter pages isbn note",
    "booklet": "subtitle howpublished type location note pagetotal",
    "collection": "subtitle translator volume part edition series number publisher location isbn note",
    "mvcollection": "subtitle edition volumes series number publisher location isbn note",
    "incollection": "subtitle translator booksubtitle volume part edition series number publisher location chapter pages isbn note",
    "dataset": "subtitle version organization publisher location number note",
    "manual": "subtitle edition series number version organization publisher location isbn pagetotal note",
    "misc": "subtitle howpublished type version organization location note",
    "online": "subtitle version organization urldate note",
    "patent": "subtitle holder type version location note",
    "periodical": "subtitle volume number issue series issn note",
    "proceedings": "editor subtitle eventtitle eventdate venue volume part series number organization publisher location isbn note",
    "mvproceedings": "editor subtitle eventtitle eventdate venue volumes series number organization publisher location isbn note",
    "inproceedings": "editor subtitle booksubtitle eventtitle eventdate venue volume part series number organization publisher location chapter pages isbn note",
    "report": "subtitle number version location isrn pagetotal note",
    "thesis": "subtitle location isbn pagetotal note",
    "unpublished": "subtitle howpublished eventtitle eventdate venue location note",
}


_SUGGESTION_ALIASES = {
    "bibtex": {"conference": "inproceedings"},
    "biblatex": {
        **_BIBLATEX_REQUIREMENT_ALIASES,
        "mastersthesis": "thesis",
        "phdthesis": "thesis",
        "techreport": "report",
    },
}
_SUGGESTION_TABLES = {"bibtex": _BIBTEX, "biblatex": _BIBLATEX}
_EXTRA_FIELDS = {
    "bibtex": "doi url eprint archivePrefix primaryClass crossref keywords abstract file groups",
    "biblatex": "doi url urldate eprint eprinttype eprintclass crossref xdata keywords abstract file groups",
}


def optional_field_suggestions(entry_type: str, dialect: str) -> tuple[bool, list[str]]:
    """Return whether the type is known and its ordered editing suggestions."""
    name = _SUGGESTION_ALIASES[dialect].get(entry_type, entry_type)
    table = _SUGGESTION_TABLES[dialect]
    if name not in table:
        return False, []
    return True, list(dict.fromkeys((table[name] + " " + _EXTRA_FIELDS[dialect]).split()))


def known_entry_types(dialect: str) -> list[str]:
    """Return supported suggestion types, including compatibility aliases."""
    return sorted(set(_SUGGESTION_TABLES[dialect]) | set(_SUGGESTION_ALIASES[dialect]))
