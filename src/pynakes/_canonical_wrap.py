"""Opt-in value wrapping for the canonical formatter.

Wrapping never changes what a value means: delimiters, brace grouping,
capitalization protection, macros, ``#`` concatenation, and URLs stay as
written. Prose breaks between words and name lists between names; an
expression that cannot be wrapped safely is kept byte-exact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pynakes.canonical import CanonicalLayout, WrapValues
    from pynakes.model import BibEntry


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
