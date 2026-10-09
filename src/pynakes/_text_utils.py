"""Shared low-level text helpers for BibTeX parsing and processing.

This module holds primitives that are reused across several modules — in
particular the brace-depth / quote-tracking scanner that appears wherever
BibTeX values need to be split at their top level (outside any delimited
group).
"""

import re
from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pynakes.model import BibEntry

_YEAR_RE = re.compile(r"\d{4}")


def fold_field_names(fields: Mapping[str, str]) -> dict[str, str]:
    """Return ``fields`` keyed by lowercase name, since BibTeX names ignore case.

    A parsed entry's names are already lowercase; a hand-built mapping may not be.
    """
    return {name.lower(): value for name, value in fields.items()}


def find_field_name(fields: Mapping[str, str], name: str) -> str | None:
    """Return the key under which ``fields`` stores ``name``, ignoring case."""
    if name in fields:
        return name
    lowered = name.lower()
    return next((key for key in fields if key.lower() == lowered), None)


def entry_year(entry: "BibEntry") -> str:
    """Return the four-digit year an entry carries, or an empty string.

    Checks ``year`` then ``date``; the first four consecutive digits win.
    """
    raw = entry.fields.get("year") or entry.fields.get("date") or ""
    match = _YEAR_RE.search(raw)
    return match.group(0) if match else ""


def _is_escaped(text: str, index: int) -> bool:
    """Return True when the character at *index* is preceded by an odd number of backslashes."""
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return bool(backslashes % 2)


def iter_toplevel_splits(
    text: str,
    *,
    separators: str = ",",
    strip: bool = True,
) -> list[str]:
    """Split *text* on any character in *separators* that lies at brace/quote depth zero.

    The scanner tracks:

    * Brace depth — ``{`` increments, ``}`` decrements.  Characters inside
      braces are never treated as separators regardless of depth.
    * Double-quote regions — a ``"`` at brace depth 0 that is not escaped by a
      preceding odd number of backslashes toggles an *in-quotes* flag; characters
      inside a quoted region are likewise invisible to the separator test.
    * Backslash escaping — ``\\"`` does **not** toggle the flag because the
      backslash count is even; ``\\"`` does toggle it.  This matches BibTeX's
      own escape semantics (handled via :func:`_is_escaped`).

    Parameters
    ----------
    text:
        The BibTeX value expression (or fragment) to split.
    separators:
        A string of characters any one of which acts as a separator.  The
        default is ``","`` for comma-splitting; pass ``"#"`` for
        ``@string`` concatenation splitting.
    strip:
        When ``True`` (the default) each resulting part is stripped of
        leading/trailing whitespace before being added to the list.  Empty
        tails are suppressed.

    Returns
    -------
    list[str]
        The list of parts.  Always contains at least one element (the whole
        text, possibly empty, when no top-level separator is found).
    """
    parts: list[str] = []
    depth = 0
    in_quotes = False
    start = 0
    i = 0

    while i < len(text):
        ch = text[i]
        if ch == '"' and depth == 0 and not _is_escaped(text, i):
            in_quotes = not in_quotes
        elif not in_quotes:
            if ch == "{":
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
            elif depth == 0 and ch in separators:
                part = text[start:i]
                parts.append(part.strip() if strip else part)
                start = i + 1
        i += 1

    tail = text[start:]
    tail = tail.strip() if strip else tail
    if tail or not parts:
        parts.append(tail)
    return parts


def _normalize_text(value: str) -> str:
    """Lowercase, replace ``&`` with ``and``, strip non-alphanumeric, collapse whitespace.

    Used as a normalisation key for fuzzy comparisons across dedupe, integrity,
    and journal-title matching. Brace characters are removed first so LaTeX
    protection does not affect equality.
    """
    lowered = value.replace("{", "").replace("}", "").replace("&", "and").lower()
    return " ".join("".join(ch for ch in lowered if ch.isalnum() or ch.isspace()).split())


def title_similarity(left: str, right: str) -> float:
    """Return how alike two titles are, from 0 to 1, after :func:`_normalize_text`.

    The one similarity measure for deciding whether two titles name the same
    work, shared by dedupe evidence and integrity checks. Normalizing is
    idempotent, so already-normalized fingerprints score the same.
    """
    return SequenceMatcher(None, _normalize_text(left), _normalize_text(right)).ratio()


def _split_escaped(value: str, delimiter: str) -> list[str]:
    """Split ``value`` on unescaped ``delimiter`` characters."""
    parts: list[str] = []
    current: list[str] = []
    escaped = False

    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == delimiter:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)

    parts.append("".join(current).strip())
    return parts


def _line_end(text: str, start: int) -> int:
    """Return the position just after the current physical line."""
    newline = text.find("\n", start)
    if newline != -1:
        return newline + 1
    carriage_return = text.find("\r", start)
    return carriage_return + 1 if carriage_return != -1 else len(text)


def _count_line_breaks(segment: str) -> int:
    """Count the line breaks in *segment*: ``\\n``, ``\\r\\n``, and a lone ``\\r``."""
    return segment.count("\n") + segment.count("\r") - segment.count("\r\n")


class LineCounter:
    """One-based line numbers for positions in one text, in linear total time.

    Each query counts only the line breaks since the previous one, so numbering
    every block of a file in order costs one pass over it, where counting from
    the start for each block cost one pass per block. A query behind the last
    one starts over from the beginning. Line breaks are ``\\n``, ``\\r\\n``,
    and a lone ``\\r`` — the ones editors number lines by, so a reported line
    is the line an editor shows. A position counts the breaks *before* it, so a
    match starting mid-line — a second ``@entry`` after the previous block's
    closing brace, a ``\\cite`` in running text — reports its own line.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._position = 0
        self._line = 1

    def at(self, position: int) -> int:
        """Return the line *position* is on."""
        if position < self._position:
            self._position, self._line = 0, 1
        segment = self._text[self._position : position]
        self._line += _count_line_breaks(segment)
        if segment.startswith("\n") and self._text[self._position - 1 : self._position] == "\r":
            # The ``\\r`` of a ``\\r\\n`` ended the last segment and was counted there.
            self._line -= 1
        self._position = position
        return self._line


def strip_meta_terminator(value: str) -> str:
    """Return *value* without surrounding whitespace or a trailing ``;``.

    Both ``jabref-meta`` and ``pynakes-meta`` values may carry a trailing
    semicolon terminator; this strips it (and surrounding whitespace) so
    callers compare and store the bare payload.  Centralizes an idiom shared
    by the metadata, key-pattern, model, and filestore layers.
    """
    return value.strip().rstrip(";").strip()
