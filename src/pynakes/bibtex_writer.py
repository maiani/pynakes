"""BibTeX file writer with round-trip preservation."""

from pynakes._entry_comments import entry_comments
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
    the conventional BibTeX arrangement. A comment attached to an entry is
    written directly above it instead (see :mod:`pynakes._entry_comments`), and
    a blanked comment slot is skipped.
    """
    le = lib.line_ending
    segments: list[tuple[str, str, object]] = []
    attached_texts, attached_indices = entry_comments(lib)

    def add(kind: str, ref: object, gap: str | None = None) -> None:
        if gap is None:
            gap = "" if not segments else le * 2
            _gap, last_kind, last_ref = segments[-1] if segments else ("", "", None)
            if last_kind == "comment" and lib.raw_comments[last_ref].endswith("\n"):
                # A ``%`` comment carries its own newline; count it toward the gap.
                gap = le
        segments.append((gap, kind, ref))

    for index, comment in enumerate(lib.raw_comments):
        if comment.strip() and index not in attached_indices:
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
        run = attached_texts.get(id(entry), [])
        for position, comment in enumerate(run):
            add("raw", comment.rstrip("\r\n"), None if position == 0 else le)
        add("entry", entry, le if run else None)

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
    fields = [(name, _quote_field_value(value)) for name, value in entry.fields.items()]
    return render_entry(entry, fields, line_ending=line_ending, trailing_comma=False)


def render_entry(
    entry: BibEntry,
    fields: list[tuple[str, str]],
    *,
    line_ending: str = "\n",
    indent: str = "  ",
    tabular: bool = False,
    trailing_comma: bool = True,
    entry_type: str | None = None,
) -> str:
    """Render one entry from already-delimited field expressions.

    ``entry_type`` overrides the rendered type, which the canonical formatter
    uses to emit the case-insensitive entry type in its configured case.
    Ordinary edits keep the entry's own spelling.
    """
    lines = [f"@{entry_type or entry.type}{{{entry.key},"]
    width = max((len(name) for name, _ in fields), default=0) if tabular else 0
    for index, (name, expression) in enumerate(fields):
        pad = " " * (width - len(name)) if width else ""
        comma = "," if trailing_comma or index < len(fields) - 1 else ""
        lines.append(f"{indent}{name}{pad} = {expression}{comma}")
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
