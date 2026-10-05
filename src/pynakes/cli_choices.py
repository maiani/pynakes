"""The enumerated values the command line's options accept.

Each is a ``StrEnum`` so Typer validates the value, lists the choices in help,
and ``capabilities`` reports them. The values mirror engine constants (lint
categories, interchange formats, author and journal styles); a test keeps the
two in step, so an engine addition cannot silently become unreachable here.
"""

from enum import StrEnum


class Switch(StrEnum):
    """A normalization step: defer to the library's metadata, or force it on or off."""

    METADATA = "metadata"
    ON = "on"
    OFF = "off"


class AuthorStyle(StrEnum):
    METADATA = "metadata"
    BIBLATEX = "biblatex"
    BIBTEX = "bibtex"
    CONSERVATIVE = "conservative"
    JABREF = "jabref"
    NONE = "none"


class JournalStyle(StrEnum):
    METADATA = "metadata"
    ABBREVIATED = "abbreviated"
    FULL = "full"
    NONE = "none"


class JournalSource(StrEnum):
    METADATA = "metadata"
    JABREF = "jabref"
    NONE = "none"


class Dialect(StrEnum):
    BIBLATEX = "biblatex"
    BIBTEX = "bibtex"


class ConvertTarget(StrEnum):
    """``convert --to``: a dialect (in place) or an interchange format (export)."""

    BIBLATEX = "biblatex"
    BIBTEX = "bibtex"
    CSL_JSON = "csl-json"
    RIS = "ris"
    MODS = "mods"
    ENDNOTE = "endnote"
    CSV = "csv"


class ImportFormat(StrEnum):
    """``convert --from``: an interchange format read into BibTeX."""

    CSL_JSON = "csl-json"
    RIS = "ris"
    MODS = "mods"
    ENDNOTE = "endnote"


class KeySource(StrEnum):
    """``ref import --key-source``: where an imported entry's key comes from."""

    GENERATED = "generated"
    PROVIDER = "provider"


class LintCategory(StrEnum):
    CORRECTNESS = "correctness"
    CONTENT = "content"
    LAYOUT = "layout"
    CONSISTENCY = "consistency"
    PROFILE = "profile"


class GroupContext(StrEnum):
    """How a group's membership relates to its parent's (JabRef's hierarchical context)."""

    INDEPENDENT = "independent"
    REFINING = "refining"
    INCLUDING = "including"


#: JabRef's numeric code for each :class:`GroupContext`.
GROUP_CONTEXT_CODES = {
    GroupContext.INDEPENDENT: 0,
    GroupContext.REFINING: 1,
    GroupContext.INCLUDING: 2,
}


class Namespace(StrEnum):
    """The metadata comment a key is written to."""

    JABREF = "jabref"
    PYNAKES = "pynakes"


class Material(StrEnum):
    """``asset fetch --material``: one kind of Pinax material."""

    PREPRINT = "preprint"
    PUBLISHED = "published"
    SOURCE = "source"
    SUPPLEMENT = "supplement"
    BEST_PDF = "best-pdf"
