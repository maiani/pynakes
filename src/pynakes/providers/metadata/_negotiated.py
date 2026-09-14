"""Repairs to registrar-rendered BibTeX from DOI content negotiation.

``https://doi.org/<doi>`` with ``Accept: application/x-bibtex`` hands back
BibTeX written by whichever registrar owns the prefix, and the registrars do
not agree with each other — or with themselves. Observed from one session
against live DOIs:

* Two arXiv deposits under the same ``10.48550/arXiv.*`` prefix come back as
  ``@misc`` and ``@article``. The ``@article`` has no journal to supply, so it
  fails pynakes' own ``lint`` the moment it is imported.
* A book chapter arrives as ``@misc`` carrying its book title in ``journal``,
  which is the field ``@article`` styles read and book styles ignore.
* A reference book arrives as ``@misc`` despite Crossref's own JSON typing it
  ``reference-book``.
* arXiv records repeat a keyword verbatim (``FOS: Physical sciences`` twice)
  and none carry ``eprint``/``archiveprefix``, though the arXiv id is right
  there in the DOI.
* Page ranges keep Unicode en-dashes where BibTeX wants ``--``.

Everything here is derived from fields the record already carries, so refining
an import costs no extra request and stays deterministic and offline — the
same rule the rest of pynakes follows for network access. The registrar's own
values are preserved wherever they are usable; this only repairs what is
demonstrably wrong for the target format.
"""

from __future__ import annotations

import re

from pynakes._identifiers import normalize_arxiv
from pynakes.entry_types import (
    CONTAINER_FIELDS,
    eprint_fields,
    is_biblatex,
    preprint_entry_type,
)
from pynakes.formatters import normalize_page_numbers
from pynakes.providers.records import ReferenceMetadata

ARXIV_DOI_PREFIX = "10.48550/arxiv."

# ``Quantum Physics (quant-ph)`` -> ``quant-ph``. arXiv's DataCite keywords
# carry the primary category in parentheses; nothing else in the list does.
_CATEGORY = re.compile(r"\(([a-z-]+(?:\.[A-Za-z-]+)?)\)")


def refine(metadata: ReferenceMetadata, *, dialect: str = "bibtex") -> ReferenceMetadata:
    """Return ``metadata`` with registrar quirks repaired, in place."""
    _dedupe_keywords(metadata.fields)
    _normalize_pages(metadata.fields, metadata.field_expressions)
    if _is_arxiv(metadata):
        _refine_arxiv(metadata, dialect=dialect)
    else:
        _refine_untyped(metadata, dialect=dialect)
    return metadata


# --- shared repairs ---------------------------------------------------------


def _dedupe_keywords(fields: dict[str, str]) -> None:
    """Drop repeated keywords, preserving first-seen order.

    DataCite renders arXiv's subject list with duplicates (``FOS: Physical
    sciences`` twice in every record); nothing downstream benefits from the
    repeat, and a keyword list is order-significant to readers but not
    multiplicity-significant.
    """
    value = fields.get("keywords", "")
    if not value:
        return
    seen: list[str] = []
    for keyword in value.split(","):
        cleaned = keyword.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    fields["keywords"] = ", ".join(seen)


def _normalize_pages(fields: dict[str, str], expressions: dict[str, str]) -> None:
    """Rewrite en/em-dash page ranges to BibTeX's ``--``.

    Crossref renders ``3–56`` with U+2013. It survives UTF-8 + ``inputenc`` but
    breaks under 8-bit ``bibtex`` with some styles, and is invisible in a diff,
    so it propagates silently once imported.
    """
    value = fields.get("pages", "")
    if not value:
        return
    normalized = normalize_page_numbers(value)
    if normalized != value:
        fields["pages"] = normalized
        expressions["pages"] = f"{{{normalized}}}"


# --- arXiv deposits ---------------------------------------------------------


def _is_arxiv(metadata: ReferenceMetadata) -> bool:
    doi = metadata.fields.get("doi", "") or metadata.identifiers.get("doi", "")
    if doi.strip().lower().startswith(ARXIV_DOI_PREFIX):
        return True
    return metadata.fields.get("publisher", "").strip().lower() == "arxiv"


def _refine_arxiv(metadata: ReferenceMetadata, *, dialect: str) -> None:
    """Give every arXiv deposit the same shape, whatever type DataCite chose.

    A preprint is not a journal article: it has no journal, so ``@article``
    guarantees a ``lint`` error on import. The eprint fields come from
    :func:`~pynakes.entry_types.eprint_fields`, the same source the arXiv-id
    import path uses, so one work imported either way looks identical.
    """
    fields = metadata.fields
    expressions = metadata.field_expressions
    metadata.entry_type = preprint_entry_type(dialect)

    arxiv_id = _arxiv_id(metadata)
    if arxiv_id:
        names = eprint_fields(dialect)
        _set(fields, expressions, names.eprint, arxiv_id)
        _set(fields, expressions, names.archive, names.archive_value)
        if category := _primary_class(fields.get("keywords", "")):
            _set(fields, expressions, names.eprint_class, category)
        canonical = f"10.48550/arXiv.{arxiv_id}"
        if fields.get("doi", "") != canonical:
            _set(fields, expressions, "doi", canonical)
            metadata.identifiers["doi"] = canonical

    # ``journal = {arXiv}`` names the repository, not a periodical. It is the
    # field that made these records lint as journal articles in the first place.
    for name in CONTAINER_FIELDS:
        if fields.get(name, "").strip().lower() == "arxiv":
            fields.pop(name, None)
            expressions.pop(name, None)


def _arxiv_id(metadata: ReferenceMetadata) -> str | None:
    """Recover the arXiv id, preferring the correctly-cased one in ``url``.

    DataCite upper-cases the DOI (``10.48550/ARXIV.QUANT-PH/9807006``) but
    leaves ``url`` alone, and legacy ids carry a case-sensitive archive name.
    """
    url = metadata.fields.get("url", "")
    if "arxiv.org/abs/" in url:
        candidate = normalize_arxiv(url.split("arxiv.org/abs/", 1)[1].strip().rstrip("/"))
        if candidate:
            return candidate
    doi = (metadata.fields.get("doi", "") or metadata.identifiers.get("doi", "")).strip()
    if doi.lower().startswith(ARXIV_DOI_PREFIX):
        return normalize_arxiv(doi[len(ARXIV_DOI_PREFIX) :])
    return None


def _primary_class(keywords: str) -> str | None:
    match = _CATEGORY.search(keywords)
    return match.group(1) if match else None


# --- untyped Crossref records -----------------------------------------------


def _refine_untyped(metadata: ReferenceMetadata, *, dialect: str) -> None:
    """Recover a real entry type for a record the registrar rendered ``@misc``.

    Crossref renders every subtype it has no BibTeX mapping for as ``@misc``,
    including whole books (``reference-book``) and book chapters (``other``).
    The distinguishing evidence is already in the record: a chapter names the
    volume that contains it, a book names only itself.
    """
    if metadata.entry_type != "misc":
        return
    fields = metadata.fields
    container = next(
        (fields[name] for name in CONTAINER_FIELDS if fields.get(name)),
        "",
    ).strip()

    if container and (fields.get("pages", "").strip() or fields.get("isbn", "").strip()):
        metadata.entry_type = _chapter_type(fields, dialect)
        for name in ("journal", "journaltitle"):
            fields.pop(name, None)
            metadata.field_expressions.pop(name, None)
        _set(fields, metadata.field_expressions, "booktitle", container)
        return

    if not container and fields.get("isbn", "").strip() and fields.get("publisher", "").strip():
        metadata.entry_type = "book"


def _chapter_type(fields: dict[str, str], dialect: str) -> str:
    """Return the entry type for a chapter, given what the record actually has.

    ``@incollection`` asserts a contribution to an *edited* collection, and
    BibLaTeX accordingly requires its ``editor``. Crossref rarely supplies one,
    so claiming ``@incollection`` there would trade the lint error this module
    exists to prevent for a different one. ``@inbook`` — a self-contained part
    of a book — is satisfied by what the record does carry, and asserts less.
    Plain BibTeX does not require an editor, so it keeps the more precise type.
    """
    if is_biblatex(dialect) and not fields.get("editor", "").strip():
        return "inbook"
    return "incollection"


def _set(fields: dict[str, str], expressions: dict[str, str], name: str, value: str) -> None:
    fields[name] = value
    expressions[name] = f"{{{value}}}"
