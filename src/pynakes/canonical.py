"""Canonical whole-file layout formatting for BibTeX/BibLaTeX files.

Canonical layout is an *explicitly requested whole-file rewrite*; all other
modifying operations continue to use surgical edits and preserve unrelated
source text.  The canonical formatter is deterministic and idempotent: a
second pass over its own output produces no changes.

BibTeX/BibLaTeX and TeX awareness:
    Wrapping never changes brace grouping, capitalization protection,
    macros, quoted/braced atoms, ``#`` concatenation, names, URLs, or
    field meaning.  The value text is emitted verbatim inside its brace
    wrapper; only the structural envelope (whitespace, line breaks,
    commas) is canonicalized.
"""

from __future__ import annotations

from dataclasses import dataclass

from pynakes.bibtex_parser import parse_raw_string_definition
from pynakes.bibtex_writer import _quote_field_value, render_entry
from pynakes.model import BibEntry, BibFile

# ---------------------------------------------------------------------------
# Layout configuration
# ---------------------------------------------------------------------------

# Canonical field ordering per entry type.  Fields not in the table are
# appended after the known fields in their original insertion order.
_FIELD_ORDER: dict[str, list[str]] = {
    "article": [
        "author",
        "title",
        "journal",
        "year",
        "volume",
        "number",
        "pages",
        "month",
        "doi",
        "url",
        "note",
        "abstract",
    ],
    "book": [
        "author",
        "editor",
        "title",
        "publisher",
        "year",
        "volume",
        "series",
        "address",
        "edition",
        "month",
        "doi",
        "url",
        "note",
        "isbn",
        "abstract",
    ],
    "inproceedings": [
        "author",
        "title",
        "booktitle",
        "year",
        "editor",
        "pages",
        "volume",
        "series",
        "address",
        "publisher",
        "organization",
        "month",
        "doi",
        "url",
        "note",
        "abstract",
    ],
    "incollection": [
        "author",
        "title",
        "booktitle",
        "year",
        "editor",
        "pages",
        "volume",
        "series",
        "address",
        "publisher",
        "month",
        "doi",
        "url",
        "note",
        "abstract",
    ],
    "phdthesis": [
        "author",
        "title",
        "school",
        "year",
        "address",
        "month",
        "doi",
        "url",
        "note",
        "abstract",
    ],
    "mastersthesis": [
        "author",
        "title",
        "school",
        "year",
        "address",
        "month",
        "doi",
        "url",
        "note",
        "abstract",
    ],
    "techreport": [
        "author",
        "title",
        "institution",
        "year",
        "type",
        "number",
        "address",
        "month",
        "doi",
        "url",
        "note",
        "abstract",
    ],
    "misc": [
        "author",
        "title",
        "year",
        "howpublished",
        "month",
        "url",
        "note",
        "abstract",
    ],
    "proceedings": [
        "editor",
        "title",
        "year",
        "volume",
        "series",
        "address",
        "publisher",
        "organization",
        "month",
        "doi",
        "url",
        "note",
        "abstract",
    ],
    "unpublished": [
        "author",
        "title",
        "year",
        "month",
        "note",
        "url",
        "abstract",
    ],
}

# Fields that are structural and should not be reordered (always stay at
# their original position if present).
_STRUCTURAL_FIELDS = frozenset({"crossref", "xdata", "xref"})


@dataclass(frozen=True)
class CanonicalLayout:
    """Configuration for canonical whole-file layout formatting.

    ``indent`` is the string used for one level of field indentation (default:
    two spaces).  ``tabular`` controls whether fields are aligned on ``=`` in a
    tabular fashion.  ``trailing_comma`` adds a trailing comma after the last
    field.  ``blank_line_entries`` inserts a blank line between consecutive
    entries. Field values are never wrapped because doing so can alter source
    expressions.
    """

    indent: str = "  "
    tabular: bool = False
    trailing_comma: bool = True
    blank_line_entries: bool = True
    sort_fields: bool = True


_DEFAULT_LAYOUT = CanonicalLayout()


# ---------------------------------------------------------------------------
# Entry-level canonical formatting
# ---------------------------------------------------------------------------


def _sorted_fields(entry: BibEntry, layout: CanonicalLayout) -> list[tuple[str, str]]:
    """Return *entry*'s fields in canonical order.

    Known fields for the entry type come first in the canonical order; any
    remaining fields follow in their original dict-insertion order.  Structural
    fields (``crossref``, ``xdata``, ``xref``) are always emitted first so
    inheritance relationships are visible.
    """
    if not layout.sort_fields:
        return list(entry.fields.items())

    entry_type_lower = entry.type.lower()
    known_order = _FIELD_ORDER.get(entry_type_lower, [])
    rank = {name: index for index, name in enumerate(known_order)}

    structural: list[tuple[str, str]] = []
    canonical: list[tuple[str, str]] = []
    extras: list[tuple[str, str]] = []
    seen: set[str] = set()

    for name, value in entry.fields.items():
        if name.lower() in _STRUCTURAL_FIELDS:
            structural.append((name, value))
            seen.add(name.lower())
            continue
        if name.lower() in known_order:
            canonical.append((name, value))
            seen.add(name.lower())
        else:
            extras.append((name, value))
            seen.add(name.lower())

    canonical.sort(key=lambda item: rank[item[0].lower()])

    return structural + canonical + extras


def _align_width(fields: list[tuple[str, str]]) -> int:
    """Compute the column width for tabular ``=`` alignment."""
    if not fields:
        return 0
    return max(len(name) for name, _ in fields)


def format_entry(
    entry: BibEntry,
    layout: CanonicalLayout | None = None,
    line_ending: str = "\n",
) -> str:
    """Format one BibEntry with the canonical layout.

    The entry header is ``@type{key,`` and the closing brace is on its own
    line.  Fields are one-per-line, indented, with ``=`` separation.
    """
    if layout is None:
        layout = _DEFAULT_LAYOUT

    semantic_fields = _sorted_fields(entry, layout)
    fields = [
        (name, entry.field_expressions.get(name, _quote_field_value(value)))
        for name, value in semantic_fields
    ]
    return render_entry(
        entry,
        fields,
        line_ending=line_ending,
        indent=layout.indent,
        tabular=layout.tabular,
        trailing_comma=layout.trailing_comma,
    )


# ---------------------------------------------------------------------------
# Whole-file canonical formatting
# ---------------------------------------------------------------------------


def write_bib_canonical(
    lib: BibFile,
    layout: CanonicalLayout | None = None,
) -> str:
    """Serialize *lib* with canonical whole-file layout.

    This is the explicit whole-file rewrite path.  Unlike :func:`write_bib`,
    which preserves source layout for byte-for-byte round-trips, this function
    always produces a deterministic, canonical output.  Comments, ``@string``
    declarations, ``@preamble``, metadata blocks, and entries are all rendered
    in a deterministic order.

    Deterministic ordering:
        1. ``pynakes-meta`` comment blocks (consolidated)
        2. ``jabref-meta`` comment blocks (one per key)
        3. Other ``@comment`` blocks
        4. ``@string`` declarations (alphabetical by key)
        5. ``@preamble`` blocks
        6. ``@entry`` blocks (in their original order)

    Within each entry, fields follow the canonical field-order table.  The
    output is idempotent: formatting twice gives the same result.
    """
    if layout is None:
        layout = _DEFAULT_LAYOUT

    le = lib.line_ending
    parts: list[str] = []

    # Preserve non-whitespace source text that is not a parsed top-level block.
    # Canonical formatting owns surrounding whitespace and block placement, but
    # it must never silently discard text the round-trip parser retained.
    raw_source: list[str] = []
    for gap, kind, ref in lib.source_layout:
        if gap.strip():
            raw_source.append(gap.strip("\r\n"))
        if kind == "raw":
            raw_source.append(str(ref).strip("\r\n"))
    for fragment in raw_source:
        parts.append(fragment)
        parts.append(le * 2)

    # Partition comments into metadata vs. plain.
    pynakes_comments: list[str] = []
    jabref_comments: list[str] = []
    plain_comments: list[str] = []

    for comment in lib.raw_comments:
        stripped = comment.strip()
        if stripped.lower().startswith("@comment{pynakes-meta:"):
            pynakes_comments.append(comment)
        elif stripped.lower().startswith("@comment{jabref-meta:"):
            jabref_comments.append(comment)
        else:
            plain_comments.append(comment)

    # Emit pynakes-meta first (consolidated), then jabref-meta, then plain.
    for comment in pynakes_comments:
        parts.append(comment)
        parts.append(le * 2)
    for comment in jabref_comments:
        parts.append(comment)
        parts.append(le * 2)
    for comment in plain_comments:
        parts.append(comment)
        parts.append(le * 2)

    # @string declarations, alphabetical by key. Keep every source declaration,
    # including duplicate keys, rather than collapsing them through ``strings``.
    if lib.raw_strings or lib.strings:
        declarations: list[tuple[str, int, str]] = []
        represented: set[str] = set()
        for index, raw in enumerate(lib.raw_strings):
            parsed = parse_raw_string_definition(raw)
            key = parsed[0] if parsed is not None else ""
            if parsed is not None:
                represented.add(key.lower())
            declarations.append((key.casefold(), index, raw))
        for key, value in lib.strings.items():
            if key.lower() not in represented:
                declarations.append(
                    (key.casefold(), len(declarations), f"@string{{{key} = {{{value}}}}}")
                )
        for _key, _index, raw in sorted(declarations):
            parts.append(raw)
            parts.append(le * 2)

    # @preamble blocks.
    for preamble_text in lib.preamble:
        parts.append(preamble_text)
        parts.append(le * 2)

    # Entries.
    entries = list(lib.entries.values())
    for idx, entry in enumerate(entries):
        entry_text = format_entry(entry, layout, le)
        parts.append(entry_text)
        if idx < len(entries) - 1 and layout.blank_line_entries:
            parts.append(le * 2)
        else:
            parts.append(le)

    text = "".join(parts)
    trailing = lib.source_trailing.lstrip("\r\n")
    if trailing.strip():
        if text:
            text = text.rstrip("\r\n") + le * 2
        text += trailing
    if text and not text.endswith(le):
        text += le
    return text
