"""Which field holds a given piece of metadata, per entry type and dialect.

Two questions recur across enrichment and reference import, and both were
previously answered inline wherever they came up:

*Where does a* container *title belong?* The journal for an article, the book
for a chapter, nowhere at all for a monograph whose own ``title`` is the
container. Provider metadata does not answer this — DOI content negotiation
renders a book chapter's container into ``journal`` regardless of the work's
actual type — so a consumer that copies remote ``journal`` into local
``journal`` writes a book title into a field BibTeX styles only read for
articles. Routing every container write through :func:`container_field` keeps
the decision in one place and keyed on the *local* entry type, which the user
controls, rather than on whatever shape the provider returned.

*What is an eprint's provenance called?* BibTeX and BibLaTeX disagree
(``archivePrefix`` vs ``eprinttype``), and so did three call sites here, which
meant the same arXiv work picked up differently-spelled fields depending on
whether it was imported by arXiv id or by its registered DOI.

:data:`ARTICLE_LIKE` and :data:`BOOK_PART_LIKE` follow the BibLaTeX manual's
entry-type aliases (section 2.1.1), so ``suppperiodical`` resolves like
``article`` and ``inreference`` like ``incollection``.
"""

from __future__ import annotations

from typing import NamedTuple

# Types whose container is a periodical: the container title goes in
# ``journal`` (BibTeX) or ``journaltitle`` (BibLaTeX).
ARTICLE_LIKE = frozenset(
    {
        "article",
        "periodical",
        "review",
        "suppperiodical",
    }
)

# Types that are a *part of* a larger book or volume: the container title goes
# in ``booktitle``. ``proceedings`` and ``book`` are deliberately absent — their
# own ``title`` is the container, so they take no container field at all.
BOOK_PART_LIKE = frozenset(
    {
        "bookinbook",
        "conference",
        "inbook",
        "incollection",
        "inproceedings",
        "inreference",
        "suppbook",
        "suppcollection",
    }
)

# Field names that already hold a container title, in the order a reader should
# prefer them. Used to decide whether an entry *has* a container before writing.
CONTAINER_FIELDS = ("journal", "journaltitle", "booktitle")


def is_biblatex(dialect: str) -> bool:
    """Whether ``dialect`` names BibLaTeX rather than BibTeX."""
    return dialect.strip().lower() == "biblatex"


def container_field(entry_type: str, *, dialect: str = "bibtex") -> str | None:
    """Return the field holding the container title for ``entry_type``.

    ``None`` means the type has no container field, and a container title
    obtained from a provider should be dropped rather than written somewhere it
    does not belong (``@book``, ``@misc``, ``@phdthesis``, ``@proceedings``).
    """
    etype = entry_type.strip().lower()
    if etype in ARTICLE_LIKE:
        return "journaltitle" if is_biblatex(dialect) else "journal"
    if etype in BOOK_PART_LIKE:
        return "booktitle"
    return None


def has_container(fields: dict[str, str]) -> bool:
    """Whether ``fields`` already records a container title under any spelling.

    Checked across all of :data:`CONTAINER_FIELDS` rather than the one field
    :func:`container_field` would write, so an entry carrying ``booktitle`` is
    not given a redundant ``journal`` naming the same volume.
    """
    lowered = {name.lower(): value for name, value in fields.items()}
    return any((lowered.get(name) or "").strip() for name in CONTAINER_FIELDS)


class EprintFields(NamedTuple):
    """The field names and archive value an eprint's provenance uses."""

    eprint: str
    archive: str
    archive_value: str
    eprint_class: str


def eprint_fields(dialect: str, archive: str = "arXiv") -> EprintFields:
    """Return eprint provenance field names for ``dialect``.

    BibTeX spells these ``eprint``/``archivePrefix``/``primaryClass`` — the
    casing arXiv itself publishes, and what REVTeX and IEEEtran document —
    while BibLaTeX uses ``eprint``/``eprinttype``/``eprintclass`` with a
    lowercased archive name.
    """
    if is_biblatex(dialect):
        return EprintFields("eprint", "eprinttype", archive.lower(), "eprintclass")
    return EprintFields("eprint", "archivePrefix", archive, "primaryClass")


def preprint_entry_type(dialect: str) -> str:
    """Return the entry type an unpublished eprint takes in ``dialect``.

    A preprint has no journal, so ``@article`` guarantees a ``lint`` error;
    ``@misc`` with eprint provenance is the BibTeX convention, and BibLaTeX
    provides ``@online`` for exactly this.
    """
    return "online" if is_biblatex(dialect) else "misc"
