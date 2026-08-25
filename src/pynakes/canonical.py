"""Canonical whole-file layout formatting for BibTeX/BibLaTeX files.

Canonical layout is an *explicitly requested whole-file rewrite*; all other
modifying operations continue to use surgical edits and preserve unrelated
source text.  The canonical formatter is deterministic and idempotent: a
second pass over its own output produces no changes.

BibTeX/BibLaTeX and TeX awareness:
    Value wrapping is opt-in and never changes delimiters, brace grouping,
    capitalization protection, macros, ``#`` concatenation, URLs, or field
    meaning. Unsafe expression categories remain byte-exact.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pynakes.bibtex_parser import parse_bib, parse_raw_string_definition
from pynakes.bibtex_writer import _quote_field_value, render_entry
from pynakes.editing import raw_field_names
from pynakes.metadata import library_sort_order, metadata_bool, metadata_value
from pynakes.model import BibEntry, BibFile

__all__ = [
    "ALIGNMENTS",
    "BLOCK_ORDERS",
    "ENTRY_ORDERS",
    "FIELD_ORDERS",
    "WRAP_VALUE_MODES",
    "Alignment",
    "BlockOrder",
    "CanonicalLayout",
    "EntryOrder",
    "FieldOrder",
    "FormatLintError",
    "WrapValues",
    "format_entry",
    "format_selected_entries",
    "layout_from_metadata",
    "validate_format_input",
    "write_bib_canonical",
]

Alignment = Literal["compact", "equals"]
FieldOrder = Literal["preferred", "preserve", "alphabetical"]
EntryOrder = Literal["preserve", "key", "profile"]
BlockOrder = Literal["preserve", "canonical"]
WrapValues = Literal["off", "stable", "canonical"]

ALIGNMENTS = ("compact", "equals")
FIELD_ORDERS = ("preferred", "preserve", "alphabetical")
ENTRY_ORDERS = ("preserve", "key", "profile")
BLOCK_ORDERS = ("preserve", "canonical")
WRAP_VALUE_MODES = ("off", "stable", "canonical")

# ---------------------------------------------------------------------------
# Layout configuration
# ---------------------------------------------------------------------------

# Pynakes' preferred field ordering per entry type. BibTeX and BibLaTeX do not
# assign semantic meaning to field order; this is a deterministic readability
# convention, not an external standard. It keeps inheritance links first (see
# ``_STRUCTURAL_FIELDS``), then identifies the work and its publication context,
# then places identifiers/access fields and annotations toward the end. Fields
# absent from the table retain their original relative order after known fields.
_FIELD_ORDER: dict[str, list[str]] = {
    "article": [
        "author",
        "title",
        "journal",
        "year",
        "volume",
        "number",
        "pages",
        "numpages",
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
    """Configuration for canonical whole-file layout formatting."""

    indent: str = "  "
    alignment: Alignment = "compact"
    trailing_comma: bool = True
    blank_line_entries: bool = True
    field_order: FieldOrder = "preferred"
    entry_order: EntryOrder = "preserve"
    block_order: BlockOrder = "canonical"
    wrap_values: WrapValues = "off"
    line_width: int = 100

    def __post_init__(self) -> None:
        if not self.indent:
            raise ValueError("format indent must be a non-empty string")
        _validate_choice("alignment", self.alignment, ALIGNMENTS)
        _validate_choice("field order", self.field_order, FIELD_ORDERS)
        _validate_choice("entry order", self.entry_order, ENTRY_ORDERS)
        _validate_choice("block order", self.block_order, BLOCK_ORDERS)
        _validate_choice("wrap-values mode", self.wrap_values, WRAP_VALUE_MODES)
        if self.line_width < 20:
            raise ValueError("format line width must be at least 20")


class FormatLintError(ValueError):
    """Raised when lint errors make canonical formatting unsafe."""

    def __init__(self, issues) -> None:
        self.issues = list(issues)
        summary = "; ".join(issue.message for issue in self.issues[:3])
        if len(self.issues) > 3:
            summary += f"; and {len(self.issues) - 3} more"
        super().__init__(f"format refused because lint reported errors: {summary}")


def _validate_choice(label: str, value: str, choices: tuple[str, ...]) -> None:
    if value not in choices:
        raise ValueError(f"Invalid format {label} {value!r}; choose {', '.join(choices)}")


def validate_format_input(lib: BibFile) -> list:
    """Run lint and refuse findings that imply a lossy canonical rewrite.

    Bibliographic-quality errors such as a missing required field do not make a
    layout rewrite unsafe. They remain visible through ``pynakes lint`` but do
    not prevent formatting an incomplete draft.
    """
    from pynakes.lint import lint

    issues = lint(lib)
    errors = [issue for issue in issues if issue.type == "duplicate_field"]
    if errors:
        raise FormatLintError(errors)
    return issues


def _metadata_choice(lib: BibFile, key: str, default: str, choices: tuple[str, ...]) -> str:
    value = metadata_value(lib, key)
    if value is None:
        return default
    normalized = value.strip().lower()
    _validate_choice(key, normalized, choices)
    return normalized


def layout_from_metadata(
    lib: BibFile,
    *,
    indent: str | None = None,
    alignment: Alignment | None = None,
    trailing_comma: bool | None = None,
    blank_line_entries: bool | None = None,
    field_order: FieldOrder | None = None,
    entry_order: EntryOrder | None = None,
    block_order: BlockOrder | None = None,
    wrap_values: WrapValues | None = None,
    line_width: int | None = None,
) -> CanonicalLayout:
    """Resolve portable ``format-*`` metadata, with explicit arguments winning."""
    raw_indent = metadata_value(lib, "format-indent")
    profile_indent = CanonicalLayout.indent
    if raw_indent is not None:
        token = raw_indent.strip()
        if token.lower() == "tab":
            profile_indent = "\t"
        elif token.isdigit():
            profile_indent = " " * int(token)
        else:
            profile_indent = raw_indent

    raw_width = metadata_value(lib, "format-line-width")
    profile_width = CanonicalLayout.line_width if raw_width is None else int(raw_width.strip())
    return CanonicalLayout(
        indent=profile_indent if indent is None else indent,
        alignment=(
            _metadata_choice(lib, "format-alignment", "compact", ALIGNMENTS)
            if alignment is None
            else alignment
        ),
        trailing_comma=(
            metadata_bool(metadata_value(lib, "format-trailing-comma"), True)
            if trailing_comma is None
            else trailing_comma
        ),
        blank_line_entries=(
            metadata_bool(metadata_value(lib, "format-blank-lines"), True)
            if blank_line_entries is None
            else blank_line_entries
        ),
        field_order=(
            _metadata_choice(lib, "format-field-order", "preferred", FIELD_ORDERS)
            if field_order is None
            else field_order
        ),
        entry_order=(
            _metadata_choice(lib, "format-entry-order", "preserve", ENTRY_ORDERS)
            if entry_order is None
            else entry_order
        ),
        block_order=(
            _metadata_choice(lib, "format-block-order", "canonical", BLOCK_ORDERS)
            if block_order is None
            else block_order
        ),
        wrap_values=(
            _metadata_choice(lib, "format-wrap-values", "off", WRAP_VALUE_MODES)
            if wrap_values is None
            else wrap_values
        ),
        line_width=profile_width if line_width is None else line_width,
    )


_DEFAULT_LAYOUT = CanonicalLayout()


# ---------------------------------------------------------------------------
# Entry-level canonical formatting
# ---------------------------------------------------------------------------


def _sorted_fields(entry: BibEntry, layout: CanonicalLayout) -> list[tuple[str, str]]:
    """Return *entry*'s fields in pynakes' preferred order.

    This order is a deterministic readability convention, not a requirement of
    BibTeX, BibLaTeX, or JabRef. Known fields for the entry type come first in
    the preferred order; any remaining fields follow in their original
    dict-insertion order. Structural fields (``crossref``, ``xdata``, ``xref``)
    are always emitted first so inheritance relationships are visible.
    """
    policy = layout.field_order
    if policy == "preserve":
        return list(entry.fields.items())
    if policy == "alphabetical":
        structural = [
            item for item in entry.fields.items() if item[0].lower() in _STRUCTURAL_FIELDS
        ]
        ordinary = [
            item for item in entry.fields.items() if item[0].lower() not in _STRUCTURAL_FIELDS
        ]
        ordinary.sort(key=lambda item: item[0].casefold())
        return structural + ordinary

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
    fields: list[tuple[str, str]] = [
        (name, entry.field_expressions.get(name, _quote_field_value(value)))
        for name, value in semantic_fields
    ]
    if layout.wrap_values != "off":
        return _render_wrapped_entry(entry, fields, layout, line_ending)
    return render_entry(
        entry,
        fields,
        line_ending=line_ending,
        indent=layout.indent,
        tabular=layout.alignment == "equals",
        trailing_comma=layout.trailing_comma,
        entry_type=entry.type.lower(),
    )


_VERBATIM_FIELDS = frozenset(
    {"url", "doi", "eprint", "file", "isbn", "issn", "urldate", "howpublished"}
)
_DATE_FIELDS = frozenset({"date", "year", "month", "day", "eventdate", "origdate"})
_NAME_FIELDS = frozenset(
    {"author", "editor", "translator", "bookauthor", "commentator", "annotator"}
)


def _render_wrapped_entry(
    entry: BibEntry,
    fields: list[tuple[str, str]],
    layout: CanonicalLayout,
    line_ending: str,
) -> str:
    """Render an entry with opt-in, expression-preserving value wrapping."""
    width = max((len(name) for name, _ in fields), default=0) if layout.alignment == "equals" else 0
    # Entry types are case-insensitive in BibTeX, so canonical layout lowercases
    # them exactly as the parser already lowercases field names.
    lines = [f"@{entry.type.lower()}{{{entry.key},"]
    for index, (name, expression) in enumerate(fields):
        pad = " " * (width - len(name)) if width else ""
        prefix = f"{layout.indent}{name}{pad} = "
        comma = "," if layout.trailing_comma or index < len(fields) - 1 else ""
        wrapped = _wrap_expression(
            name,
            expression,
            prefix=prefix,
            comma=comma,
            mode=layout.wrap_values,
            line_width=layout.line_width,
        )
        lines.extend(wrapped)
    lines.append("}")
    return line_ending.join(lines)


def _wrap_expression(
    field_name: str,
    expression: str,
    *,
    prefix: str,
    comma: str,
    mode: WrapValues,
    line_width: int,
) -> list[str]:
    """Wrap one safe literal expression, preserving its outer delimiter."""
    normalized_name = field_name.lower()
    if (
        normalized_name in _VERBATIM_FIELDS
        or normalized_name in _DATE_FIELDS
        or _has_top_level_concat(expression)
    ):
        return [f"{prefix}{expression}{comma}"]

    delimited = _literal_inner(expression)
    if delimited is None:
        return [f"{prefix}{expression}{comma}"]
    opener, inner, closer = delimited
    if normalized_name in _NAME_FIELDS:
        chunks, authored_breaks = _split_names(inner)
    else:
        chunks, authored_breaks = _split_prose(inner)
    if len(chunks) <= 1:
        return [f"{prefix}{expression}{comma}"]

    continuation = " " * (len(prefix) + len(opener))
    current = f"{prefix}{opener}{chunks[0]}"
    lines: list[str] = []
    for index, chunk in enumerate(chunks[1:], start=1):
        candidate = f"{current} {chunk}"
        keep_authored = mode == "stable" and authored_breaks[index - 1]
        if keep_authored or len(candidate) + len(closer) + len(comma) > line_width:
            lines.append(current)
            current = f"{continuation}{chunk}"
        else:
            current = candidate
    lines.append(f"{current}{closer}{comma}")
    return lines


def _literal_inner(expression: str) -> tuple[str, str, str] | None:
    stripped = expression.strip()
    if len(stripped) < 2:
        return None
    if stripped[0] == "{" and stripped[-1] == "}" and _balanced_braces(stripped[1:-1]):
        return "{", stripped[1:-1], "}"
    if stripped[0] == '"' and stripped[-1] == '"' and _balanced_braces(stripped[1:-1]):
        return '"', stripped[1:-1], '"'
    return None


def _balanced_braces(value: str) -> bool:
    depth = 0
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _has_top_level_concat(expression: str) -> bool:
    depth = 0
    in_quotes = False
    escaped = False
    for char in expression:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"' and depth == 0:
            in_quotes = not in_quotes
        elif not in_quotes and char == "{":
            depth += 1
        elif not in_quotes and char == "}":
            depth -= 1
        elif not in_quotes and depth == 0 and char == "#":
            return True
    return False


def _split_prose(value: str) -> tuple[list[str], list[bool]]:
    """Split at brace/math-top-level whitespace and remember authored newlines."""
    chunks: list[str] = []
    breaks: list[bool] = []
    current: list[str] = []
    pending_whitespace: list[str] = []
    brace_depth = 0
    in_math = False
    escaped = False

    for char in value:
        if not char.isspace() and pending_whitespace:
            if chunks:
                breaks.append(any(item in "\r\n" for item in pending_whitespace))
            pending_whitespace.clear()
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char.isspace() and brace_depth == 0 and not in_math:
            if current:
                chunks.append("".join(current))
                current = []
            pending_whitespace.append(char)
            continue
        current.append(char)
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
        elif char == "$" and brace_depth == 0:
            in_math = not in_math
    if current:
        chunks.append("".join(current))
    # There is one boundary marker for every adjacent pair.
    return chunks, (breaks + [False] * max(0, len(chunks) - 1 - len(breaks)))


def _split_names(value: str) -> tuple[list[str], list[bool]]:
    """Split a name list only at top-level ``and`` separators."""
    pieces, separators = _split_prose(value)
    if len(pieces) <= 1:
        return pieces, separators
    names: list[str] = []
    boundaries: list[bool] = []
    current: list[str] = []
    for index, piece in enumerate(pieces):
        if piece.lower() == "and" and current and index + 1 < len(pieces):
            names.append(" ".join([*current, "and"]))
            boundaries.append(separators[index] if index < len(separators) else False)
            current = []
        else:
            current.append(piece)
    if current:
        names.append(" ".join(current))
    return names, boundaries[: max(0, len(names) - 1)]


# ---------------------------------------------------------------------------
# Whole-file canonical formatting
# ---------------------------------------------------------------------------


def _assert_representable(lib: BibFile) -> None:
    for entry in lib.entries.values():
        if entry.raw_content is None:
            continue
        names = raw_field_names(entry.raw_content)
        normalized = [name.lower() for name in names]
        duplicates = sorted({name for name in normalized if normalized.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"format cannot losslessly represent repeated field(s) in entry "
                f"{entry.key!r}: {', '.join(duplicates)}"
            )


def _semantic_signature(lib: BibFile, *, normalize_whitespace: bool) -> Counter:
    def value_signature(value: str) -> str:
        return " ".join(value.split()) if normalize_whitespace else value

    entries = [
        (
            entry.key,
            # Compared case-insensitively: an entry type carries no case
            # semantics, so recasing it is not a semantic change.
            entry.type.lower(),
            tuple(sorted((name, value_signature(value)) for name, value in entry.fields.items())),
        )
        for entry in lib.entries.values()
    ]
    return Counter(entries)


def _validate_formatted_semantics(lib: BibFile, text: str, layout: CanonicalLayout) -> None:
    """Reparse formatter output and verify the represented bibliography is unchanged."""
    reparsed = parse_bib(text)
    normalize_whitespace = layout.wrap_values != "off"
    if _semantic_signature(lib, normalize_whitespace=normalize_whitespace) != _semantic_signature(
        reparsed, normalize_whitespace=normalize_whitespace
    ):
        raise ValueError("format safety check failed: canonical output changed entry semantics")

    def raw_blocks(values: list[str]) -> Counter:
        return Counter(value.strip("\r\n") for value in values)

    if raw_blocks(lib.raw_strings) != raw_blocks(reparsed.raw_strings):
        raise ValueError(
            "format safety check failed: canonical output changed @string declarations"
        )
    if raw_blocks(lib.preamble) != raw_blocks(reparsed.preamble):
        raise ValueError("format safety check failed: canonical output changed @preamble blocks")
    if raw_blocks(lib.raw_comments) != raw_blocks(reparsed.raw_comments):
        raise ValueError("format safety check failed: canonical output changed @comment blocks")


def format_selected_entries(
    lib: BibFile,
    layout: CanonicalLayout | None = None,
    predicate: Callable[[BibEntry], bool] | None = None,
) -> int:
    """Reformat the entries matching ``predicate`` in place; return how many matched.

    This is the *selection* counterpart to :func:`write_bib_canonical`. A
    selection cannot own whole-file decisions — block placement, entry order,
    blank lines between entries — so this rewrites only the layout *inside* each
    matching entry, by replacing its ``raw_content``. Every other byte of the
    file, including unmatched entries, is left exactly as it was, which keeps
    the diff to the entries the caller asked for.
    """
    if layout is None:
        layout = _DEFAULT_LAYOUT
    # An entry's semantic values come from the library's ``@string`` namespace, so
    # the per-entry safety check has to reparse it in that context, not in
    # isolation, or a macro reference would look like a changed value.
    strings = "".join(f"{raw.strip()}{lib.line_ending}" for raw in lib.raw_strings)
    matched = 0
    for entry in lib.entries.values():
        if predicate is not None and not predicate(entry):
            continue
        matched += 1
        text = format_entry(entry, layout, lib.line_ending)
        _validate_formatted_entry(entry, text, layout, strings)
        if entry.raw_content != text:
            # ``field_expressions`` deliberately keeps the source spelling of each
            # value: layout owns indentation, order, commas, and wrapping, and
            # re-deriving expressions from wrapped output would let a second pass
            # wrap already-wrapped text.
            entry.raw_content = text
    return matched


def _validate_formatted_entry(
    entry: BibEntry,
    text: str,
    layout: CanonicalLayout,
    strings: str = "",
) -> None:
    """Verify that reformatting one entry changed its layout only."""
    normalize_whitespace = layout.wrap_values != "off"
    expected = _semantic_signature(
        BibFile(entries=[entry]), normalize_whitespace=normalize_whitespace
    )
    actual = _semantic_signature(
        parse_bib(f"{strings}{text}"), normalize_whitespace=normalize_whitespace
    )
    if expected != actual:
        raise ValueError(
            f"format safety check failed: layout rewrite changed entry {entry.key!r} semantics"
        )


def _ordered_entries(
    lib: BibFile,
    layout: CanonicalLayout,
    entries: list[BibEntry] | None = None,
) -> list[BibEntry]:
    selected = list(lib.entries.values()) if entries is None else list(entries)
    if layout.entry_order == "preserve":
        return selected
    criteria = (
        [("key", False)] if layout.entry_order == "key" else list(library_sort_order(lib) or [])
    )
    if not criteria:
        return selected

    # Reuse normalize's tested stable sorting and crossref-parent ordering on a
    # temporary store so formatting never mutates the live bibliography model.
    from pynakes.normalize import sort_entries

    temporary = BibFile(entries=selected)
    sort_entries(temporary, criteria)
    return list(temporary.entries.values())


def _write_preserved_blocks(lib: BibFile, layout: CanonicalLayout) -> str:
    """Format entries while preserving top-level block positions as barriers."""
    le = lib.line_ending
    blocks: list[tuple[str, str]] = []
    entry_run: list[BibEntry] = []
    emitted_entries: set[int] = set()

    def flush_entries() -> None:
        if not entry_run:
            return
        for entry in _ordered_entries(lib, layout, entry_run):
            blocks.append(("entry", format_entry(entry, layout, le)))
            emitted_entries.add(id(entry))
        entry_run.clear()

    for gap, kind, ref in lib.source_layout:
        if gap.strip():
            flush_entries()
            blocks.append(("raw", gap.strip("\r\n")))
        if kind == "entry" and isinstance(ref, BibEntry):
            entry_run.append(ref)
            continue
        flush_entries()
        if kind == "comment" and isinstance(ref, int) and ref < len(lib.raw_comments):
            blocks.append(("comment", lib.raw_comments[ref]))
        elif kind == "string" and isinstance(ref, int) and ref < len(lib.raw_strings):
            blocks.append(("string", lib.raw_strings[ref]))
        elif kind == "preamble" and isinstance(ref, int) and ref < len(lib.preamble):
            blocks.append(("preamble", lib.preamble[ref]))
        elif kind == "raw":
            blocks.append(("raw", str(ref)))
    flush_entries()

    missing = [entry for entry in lib.entries.values() if id(entry) not in emitted_entries]
    for entry in _ordered_entries(lib, layout, missing):
        blocks.append(("entry", format_entry(entry, layout, le)))

    trailing = lib.source_trailing.strip("\r\n")
    if trailing:
        blocks.append(("raw", trailing))
    if not blocks:
        return ""

    parts: list[str] = []
    previous_kind: str | None = None
    for kind, text in blocks:
        clean = text.strip("\r\n")
        if not clean:
            continue
        if parts:
            consecutive_entries = previous_kind == "entry" and kind == "entry"
            parts.append(le * (2 if not consecutive_entries or layout.blank_line_entries else 1))
        parts.append(clean)
        previous_kind = kind
    return "".join(parts) + le


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

    With ``block_order="canonical"``, deterministic ordering is:
        1. ``pynakes-meta`` comment blocks (consolidated)
        2. Other ``@comment`` blocks
        3. ``@string`` declarations (alphabetical by key)
        4. ``@preamble`` blocks
        5. ``@entry`` blocks (in their original order)
        6. ``jabref-meta`` comment blocks (one per key)

    With ``block_order="preserve"``, non-entry blocks remain in source order and
    act as barriers for entry sorting. Within each entry, fields follow the
    selected field-order policy. The output is idempotent: formatting twice
    gives the same result.
    """
    if layout is None:
        layout = _DEFAULT_LAYOUT
    _assert_representable(lib)
    if layout.block_order == "preserve" and lib.source_layout:
        text = _write_preserved_blocks(lib, layout)
        _validate_formatted_semantics(lib, text, layout)
        return text

    le = lib.line_ending
    parts: list[str] = []

    def is_jabref_layout_segment(segment: tuple[str, str, object]) -> bool:
        _gap, kind, ref = segment
        if kind != "comment" or not isinstance(ref, int):
            return False
        try:
            comment = lib.raw_comments[ref]
        except IndexError:
            return False
        return comment.strip().lower().startswith("@comment{jabref-meta:")

    # A previous canonical pass places JabRef comments last. Any retained text
    # immediately before that trailing metadata section is represented by the
    # parser as a layout gap, rather than ``source_trailing``. Keep that text at
    # the end of the bibliography body so another pass is idempotent.
    trailing_jabref_start = len(lib.source_layout)
    while trailing_jabref_start and is_jabref_layout_segment(
        lib.source_layout[trailing_jabref_start - 1]
    ):
        trailing_jabref_start -= 1
    has_trailing_jabref_section = trailing_jabref_start < len(lib.source_layout)
    pre_jabref_source: list[str] = []

    # Preserve non-whitespace source text that is not a parsed top-level block.
    # Canonical formatting owns surrounding whitespace and block placement, but
    # it must never silently discard text the round-trip parser retained.
    raw_source: list[str] = []
    for index, (gap, kind, ref) in enumerate(lib.source_layout):
        if gap.strip():
            target = (
                pre_jabref_source
                if has_trailing_jabref_section and index >= trailing_jabref_start
                else raw_source
            )
            target.append(gap.strip("\r\n"))
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

    # Emit pynakes-native metadata first, followed by ordinary comments.
    # JabRef metadata is emitted after the bibliography body below, matching
    # JabRef's trailing metadata convention.
    for comment in pynakes_comments:
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
    entries = _ordered_entries(lib, layout)
    for idx, entry in enumerate(entries):
        entry_text = format_entry(entry, layout, le)
        parts.append(entry_text)
        if idx < len(entries) - 1 and layout.blank_line_entries:
            parts.append(le * 2)
        else:
            parts.append(le)

    text = "".join(parts)
    trailing_source = [*pre_jabref_source]
    trailing = lib.source_trailing.lstrip("\r\n")
    if trailing.strip():
        trailing_source.append(trailing)
    for fragment in trailing_source:
        if text:
            text = text.rstrip("\r\n") + le * 2
        text += fragment

    for comment in jabref_comments:
        if text:
            text = text.rstrip("\r\n") + le * 2
        text += comment.strip("\r\n")

    if text and not text.endswith(le):
        text += le
    _validate_formatted_semantics(lib, text, layout)
    return text
