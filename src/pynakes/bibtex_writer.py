"""BibTeX file writer with round-trip preservation."""

from pynakes.model import BibEntry, BibFile


def write_bib(lib: BibFile) -> str:
    """Serialize BibFile to BibTeX text.

    Uses raw_content for unmodified entries (zero-diff guarantee).
    Reconstructs modified entries from fields, preserving field order.

    Args:
        lib: BibFile to serialize

    Returns:
        BibTeX formatted text
    """
    le = lib.line_ending
    output_parts = []

    # Write comments at top
    for comment in lib.raw_comments:
        output_parts.append(comment)
    if lib.raw_comments:
        output_parts.append("")

    # Parsed @string definitions retain their original expression syntax. New
    # in-memory definitions fall back to a safe brace-quoted representation.
    if lib.raw_strings:
        output_parts.extend(lib.raw_strings)
        output_parts.append("")
    elif lib.strings:
        for key, value in lib.strings.items():
            output_parts.append(f"@string{{{key} = {{{value}}}}}")
        output_parts.append("")

    # Write @preamble
    for preamble in lib.preamble:
        output_parts.append(preamble)
    if lib.preamble:
        output_parts.append("")

    # Write entries
    for entry in lib.entries.values():
        if entry.raw_content and not entry.modified:
            # Use raw content for unmodified entries (byte-stable round-trip)
            output_parts.append(entry.raw_content)
        else:
            # Reconstruct modified entries
            output_parts.append(_reconstruct_entry(entry, le))

    # Join with the library's line ending
    text = le.join(output_parts)

    # Ensure file ends with a newline
    if text and not text.endswith(le):
        text += le

    return text


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
