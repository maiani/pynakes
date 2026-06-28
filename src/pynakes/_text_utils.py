"""Shared low-level text helpers for BibTeX parsing and processing.

This module holds primitives that are reused across several modules — in
particular the brace-depth / quote-tracking scanner that appears wherever
BibTeX values need to be split at their top level (outside any delimited
group).
"""


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
