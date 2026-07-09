"""BibTeX file writer with round-trip preservation."""

from pynakes.model import BibEntry, BibFile


def write_bib(lib: BibFile) -> str:
    """Serialize a :class:`BibFile` to BibTeX text.

    Rendering is driven entirely by an ordered *layout* of top-level blocks. For
    a parsed library whose block structure is unchanged, the layout captured at
    parse time is reused verbatim — preserving the exact source ordering and the
    whitespace between blocks, so an unmodified file round-trips byte-for-byte
    and an in-place edit changes only the edited entry. For an in-memory or
    structurally changed library the layout is derived in canonical order.
    """
    layout, trailing = _effective_layout(lib)
    text = _render_layout(lib, layout, trailing)
    le = lib.line_ending
    if text and not text.endswith(le):
        text += le
    return text


def _effective_layout(lib: BibFile) -> tuple[list, str]:
    """Return the layout to render and the trailing text after the last block.

    The preserved source layout is reused only while it still describes exactly
    the library's current blocks; once entries or declarations are added or
    removed those recorded positions are stale, so a canonical layout is
    derived instead.
    """
    if _source_layout_matches(lib):
        return lib.source_layout, lib.source_trailing
    return _canonical_layout(lib), ""


def _source_layout_matches(lib: BibFile) -> bool:
    """Whether the captured source layout still matches the library's blocks."""
    if not lib.source_layout:
        return False

    comments = strings = preambles = 0
    entries: list[BibEntry] = []
    for _gap, kind, ref in lib.source_layout:
        if kind == "comment":
            comments += 1
        elif kind == "string":
            strings += 1
        elif kind == "preamble":
            preambles += 1
        elif kind == "entry":
            entries.append(ref)
        # "raw" segments carry their own text and are always renderable.

    if (comments, strings, preambles) != (
        len(lib.raw_comments),
        len(lib.raw_strings),
        len(lib.preamble),
    ):
        return False

    current = lib.entries.values()
    if len(entries) != len(current):
        return False
    return all(a is b for a, b in zip(entries, current))


def _canonical_layout(lib: BibFile) -> list:
    """Derive an ordered layout for a library without usable source positions.

    Blocks are emitted as comments, ``@string`` declarations, ``@preamble``,
    then entries — each separated from the previous by a blank line, matching
    the conventional JabRef arrangement.
    """
    le = lib.line_ending
    segments: list[tuple[str, str, object]] = []

    def add(kind: str, ref: object) -> None:
        gap = "" if not segments else le * 2
        segments.append((gap, kind, ref))

    for index in range(len(lib.raw_comments)):
        add("comment", index)

    if lib.raw_strings:
        for index in range(len(lib.raw_strings)):
            add("string", index)
    elif lib.strings:
        # In-memory definitions have no source expression; fall back to a safe
        # brace-quoted representation rendered verbatim.
        for key, value in lib.strings.items():
            add("raw", f"@string{{{key} = {{{value}}}}}")

    for index in range(len(lib.preamble)):
        add("preamble", index)

    for entry in lib.entries.values():
        add("entry", entry)

    return segments


def _render_layout(lib: BibFile, layout: list[tuple[str, str, object]], trailing: str) -> str:
    """Render an ordered layout to text by concatenating gaps and block content.

    Unmodified entries emit their preserved ``raw_content``; modified ones are
    reconstructed from their fields. Comments, ``@string`` declarations, and
    ``@preamble`` blocks are written verbatim from their source lists.
    """
    le = lib.line_ending
    parts: list[str] = []
    for gap, kind, ref in layout:
        parts.append(gap)
        if kind == "entry":
            if ref.raw_content and not ref.modified:
                parts.append(ref.raw_content)
            else:
                parts.append(_reconstruct_entry(ref, le))
        elif kind == "comment":
            parts.append(lib.raw_comments[ref])
        elif kind == "string":
            parts.append(lib.raw_strings[ref])
        elif kind == "preamble":
            parts.append(lib.preamble[ref])
        elif kind == "raw":
            parts.append(ref)
    parts.append(trailing)
    return "".join(parts)


def _reconstruct_entry(entry: BibEntry, line_ending: str = "\n") -> str:
    """Reconstruct a BibTeX entry from its fields.

    Field order is preserved (dict insertion order); fields are not reordered.

    Args:
        entry: BibEntry to reconstruct
        line_ending: Line ending to join lines with

    Returns:
        Formatted BibTeX entry
    """
    lines = [f"@{entry.type}{{{entry.key},"]

    field_items = list(entry.fields.items())
    for i, (field_name, field_value) in enumerate(field_items):
        quoted_value = _quote_field_value(field_value)
        # Add comma after every field except the last
        comma = "," if i < len(field_items) - 1 else ""
        lines.append(f"  {field_name} = {quoted_value}{comma}")

    lines.append("}")

    return line_ending.join(lines)


def _quote_field_value(value: str) -> str:
    """Brace-quote a field value for BibTeX.

    Wraps the value in a single pair of braces. Inner braces (e.g. the
    capitalization-protection braces in ``The {DNA} Helix``) are preserved
    verbatim, since BibTeX treats braces as literal grouping rather than
    characters needing escape. Values from the parser are already
    brace-balanced, so this round-trips faithfully.

    Args:
        value: Unquoted field value

    Returns:
        Brace-quoted value
    """
    return f"{{{value}}}"
