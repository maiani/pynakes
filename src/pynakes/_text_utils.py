"""Shared low-level text helpers for BibTeX parsing and processing.

This module holds primitives that are reused across several modules — in
particular the brace-depth / quote-tracking scanner that appears wherever
BibTeX values need to be split at their top level (outside any delimited
group).
"""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pynakes.model import BibEntry

_YEAR_RE = re.compile(r"\d{4}")


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


def _line_number(text: str, position: int) -> int:
    """Return the one-based line number at *position* for any line ending."""
    return len(text[:position].splitlines()) + 1


def strip_jabref_terminator(value: str) -> str:
    """Return *value* without surrounding whitespace or JabRef's trailing ``;``.

    JabRef terminates each ``jabref-meta`` value with a semicolon; this strips
    that terminator (and surrounding whitespace) so callers compare and store
    the bare payload. Centralizes an idiom shared by the metadata, key-pattern,
    model, and filestore layers.
    """
    return value.strip().rstrip(";").strip()
