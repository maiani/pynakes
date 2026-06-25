"""BibLaTeX cross-reference inheritance (``crossref``, ``xdata``, ``xref``, sets).

This module implements the *read-only* field-inheritance contract pynakes
guarantees. Inherited values are a semantic view used by field readers (lint,
key generation, …); they are never written back into a ``BibEntry``.

The contract matches biber's default data-model inheritance (validated against
``biber --tool --output-resolve``):

- **xdata** — the referenced ``@xdata`` entries' fields are injected verbatim
  (same field names), supporting multiple comma-separated targets and chains.
- **crossref** — fields inherit by the same name, *except* the title family,
  which is remapped according to the parent's entry type: a multivolume parent
  (``mvbook``/``mvcollection``/``mvproceedings``/``mvreference``) maps
  ``title``/``subtitle``/``titleaddon`` to ``maintitle``/…; a single-volume
  container (``book``/``collection``/``proceedings``/``reference``) maps them to
  ``booktitle``/…; a ``periodical`` maps ``title``/``subtitle`` to
  ``journaltitle``/``journalsubtitle``. A remapped source field is *not* also
  inherited under its original name.
- **xref** — establishes a reference only; **no** fields are inherited.
- **@set / entryset** — set members do not inherit from the set; opaque.

Precedence is *own > xdata > crossref*: an entry's own fields always win, xdata
fills fields the entry lacks, and crossref fills only what remains. Missing
parents and cyclic references contribute no inheritance.
"""

from collections.abc import Callable, Mapping
from typing import Optional, Protocol


class _Entry(Protocol):
    """Structural type for the entry shape this module reads (duck-typed)."""

    type: str
    fields: Mapping[str, str]


Lookup = Callable[[str], Optional[_Entry]]

# Title-family remappings, selected by the *parent* entry type. A source field
# named here is inherited only under its mapped target name, never its own.
_MAIN_MAP = {"title": "maintitle", "subtitle": "mainsubtitle", "titleaddon": "maintitleaddon"}
_BOOK_MAP = {"title": "booktitle", "subtitle": "booksubtitle", "titleaddon": "booktitleaddon"}
_JOURNAL_MAP = {"title": "journaltitle", "subtitle": "journalsubtitle"}

_PARENT_TITLE_MAP: dict[str, dict[str, str]] = {
    "mvbook": _MAIN_MAP,
    "mvcollection": _MAIN_MAP,
    "mvproceedings": _MAIN_MAP,
    "mvreference": _MAIN_MAP,
    "book": _BOOK_MAP,
    "collection": _BOOK_MAP,
    "proceedings": _BOOK_MAP,
    "reference": _BOOK_MAP,
    "periodical": _JOURNAL_MAP,
}

# Linking and control fields that crossref/xdata never propagate to a child.
_NEVER_INHERIT = frozenset(
    {
        "crossref",
        "xref",
        "xdata",
        "entryset",
        "entrysubtype",
        "execute",
        "ids",
        "label",
        "options",
        "presort",
        "related",
        "relatedoptions",
        "relatedstring",
        "relatedtype",
        "shorthand",
        "shorthandintro",
        "sortkey",
    }
)


def _split_refs(value: str) -> list[str]:
    """Split a comma-separated reference list (e.g. an ``xdata`` field)."""
    return [part.strip() for part in value.split(",") if part.strip()]


def resolve_entry_fields(entry: _Entry, lookup: Lookup) -> dict[str, str]:
    """Return *entry*'s fields with xdata and crossref inheritance applied.

    ``lookup`` maps a citation key to its entry (or ``None``). The returned dict
    is a fresh read-only view; the source entries are never mutated.
    """
    return _resolve(entry, lookup, frozenset())


def _resolve(entry: _Entry, lookup: Lookup, seen: frozenset[int]) -> dict[str, str]:
    if id(entry) in seen:
        # A cycle contributes only the entry's own fields, no inheritance.
        return dict(entry.fields)
    seen = seen | {id(entry)}

    result = dict(entry.fields)

    for ref in _split_refs(entry.fields.get("xdata", "")):
        parent = lookup(ref)
        if parent is not None:
            for name, value in _xdata_fields(parent, lookup, seen).items():
                result.setdefault(name, value)

    crossref = entry.fields.get("crossref", "").strip()
    parent = lookup(crossref) if crossref else None
    if parent is not None:
        for name, value in _crossref_fields(parent, entry.type, lookup, seen).items():
            result.setdefault(name, value)

    return result


def _xdata_fields(entry: _Entry, lookup: Lookup, seen: frozenset[int]) -> dict[str, str]:
    """Fields contributed by an ``@xdata`` entry: verbatim, chains supported."""
    if id(entry) in seen:
        return {}
    seen = seen | {id(entry)}

    result: dict[str, str] = {}
    for ref in _split_refs(entry.fields.get("xdata", "")):
        nested = lookup(ref)
        if nested is not None:
            for name, value in _xdata_fields(nested, lookup, seen).items():
                result.setdefault(name, value)
    # The entry's own fields override anything from its nested xdata.
    for name, value in entry.fields.items():
        if name not in _NEVER_INHERIT:
            result[name] = value
    return result


def _crossref_fields(
    parent: _Entry, child_type: str, lookup: Lookup, seen: frozenset[int]
) -> dict[str, str]:
    """Fields a child inherits from its ``crossref`` parent, with title remap."""
    presolved = _resolve(parent, lookup, seen)
    title_map = _PARENT_TITLE_MAP.get(parent.type.lower(), {})

    result: dict[str, str] = {}
    for name, value in presolved.items():
        if name in _NEVER_INHERIT:
            continue
        if name in title_map:
            # Inherited only under the mapped name, never its own.
            result[title_map[name]] = value
        else:
            result[name] = value
    return result
