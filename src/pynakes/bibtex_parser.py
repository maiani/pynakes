"""BibTeX file parser with round-trip preservation."""

import logging
import re
from typing import Optional

from pynakes.model import BibEntry, BibLibrary, EntryCollection

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """Exception raised when parsing BibTeX fails."""

    def __init__(self, message: str, line: Optional[int] = None, file: Optional[str] = None):
        self.message = message
        self.line = line
        self.file = file
        super().__init__(f"{message}" + (f" at line {line}" if line else ""))


def detect_line_ending(text: str) -> str:
    """Detect line ending style from text.

    Note: encoding is detected from raw bytes in :mod:`pynakes.io` before
    decoding; by the time we hold a ``str`` the encoding decision is already
    made, so there is no encoding detection here.
    """
    if "\r\n" in text:
        return "\r\n"
    elif "\r" in text:
        return "\r"
    return "\n"


def parse_bib(text: str) -> BibLibrary:
    """Parse BibTeX text into a BibLibrary.

    Preserves formatting and metadata for round-trip fidelity. Duplicate
    citation keys are preserved (not an error): they are surfaced via
    ``library.entries.duplicate_keys()`` and reported by the linter.

    Args:
        text: BibTeX file content as string

    Returns:
        BibLibrary with parsed entries

    Raises:
        ParseError: If BibTeX is structurally malformed (e.g. unbalanced braces)
    """
    line_ending = detect_line_ending(text)

    entries = EntryCollection()
    strings: dict[str, str] = {}
    preambles: list[str] = []
    raw_comments: list[str] = []
    jabref_metadata: dict[str, str] = {}

    lines = text.split(line_ending)

    i = 0
    while i < len(lines):
        line_num = i + 1
        line = lines[i].strip()

        if not line or line.startswith("%"):
            if line.startswith("%"):
                raw_comments.append(line)
            i += 1
            continue

        if line.lower().startswith("@string"):
            # Collect full @string across lines if needed
            full_line = line
            j = i
            brace_count = line.count("{") - line.count("}")
            while j < len(lines) - 1 and brace_count > 0:
                j += 1
                full_line += line_ending + lines[j]
                brace_count += lines[j].count("{") - lines[j].count("}")

            key, value = _parse_string_def(full_line)
            if key is not None and value is not None:
                strings[key] = value
            i = j + 1
            continue

        if line.lower().startswith("@preamble"):
            preamble_text = _extract_preamble(line, i, line_ending, lines)
            if preamble_text:
                preambles.append(preamble_text)
            i += 1
            continue

        if line.lower().startswith("@comment"):
            comment_text = _extract_balanced_value(line, 8, i, line_ending, lines)
            if comment_text:
                raw_comments.append(f"@comment{{{comment_text}}}")
                jabref_metadata.update(_parse_jabref_metadata(comment_text))
            i += 1
            continue

        if line.startswith("@"):
            entry, lines_consumed = _parse_entry(line, i, line_ending, lines)
            if entry:
                if entry.key in entries:
                    logger.warning(
                        "Duplicate citation key %r (line %d); preserving both entries",
                        entry.key,
                        line_num,
                    )
                entries.add(entry)
                i += lines_consumed
            else:
                i += 1
            continue

        i += 1

    return BibLibrary(
        entries=entries,
        strings=strings,
        preamble=preambles,
        raw_comments=raw_comments,
        jabref_metadata=jabref_metadata,
        line_ending=line_ending,
    )


def _parse_jabref_metadata(comment_text: str) -> dict[str, str]:
    """Return structured metadata for a JabRef ``@comment`` block."""
    prefix = "jabref-meta:"
    stripped = comment_text.strip()
    if stripped.startswith("{"):
        stripped = stripped[1:].strip()
    if not stripped.lower().startswith(prefix):
        return {}

    body = stripped[len(prefix) :].strip()
    if not body:
        return {}

    key, sep, value = body.partition(":")
    if not sep:
        return {}
    return {key.strip(): value.strip()}


def _parse_entry(
    first_line: str, start_line_idx: int, line_ending: str, lines: list[str]
) -> tuple[Optional[BibEntry], int]:
    """Parse a single BibTeX entry across multiple lines.

    Returns:
        (BibEntry, lines_consumed) or (None, 0) on error
    """
    # Extract entry type and key
    match = re.match(r"@(\w+)\s*{\s*([^,]+),", first_line, re.IGNORECASE)
    if not match:
        return None, 0

    entry_type = match.group(1)
    key = match.group(2).strip()

    # Collect full entry text
    full_text = first_line
    i = start_line_idx + 1
    brace_count = first_line.count("{") - first_line.count("}")

    while i < len(lines) and brace_count > 0:
        next_line = lines[i]
        full_text += line_ending + next_line
        brace_count += next_line.count("{") - next_line.count("}")
        i += 1

    if brace_count != 0:
        raise ParseError(f"Unmatched braces in entry {key}", start_line_idx + 1)

    # Parse fields (field order is preserved by dict insertion order)
    fields = _parse_fields(full_text)

    entry = BibEntry(
        key=key,
        type=entry_type,
        fields=fields,
        raw_content=full_text,
        modified=False,
    )

    return entry, i - start_line_idx


def _parse_fields(entry_text: str) -> dict[str, str]:
    """Extract field=value pairs from entry text, preserving order."""
    fields: dict[str, str] = {}

    # Remove entry type and key part
    match = re.match(r"@\w+\s*{\s*[^,]+,\s*", entry_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return fields

    content = entry_text[match.end() : -1].strip()

    # Split by top-level commas
    parts = _split_fields(content)

    for part in parts:
        part = part.strip()
        if "=" not in part:
            continue

        field_name, field_value = part.split("=", 1)
        field_name = field_name.strip().lower()
        field_value = _unquote_value(field_value.strip())

        # Preserve the field even if its value is empty (e.g. ``note = {}``);
        # discard only nameless fragments.
        if field_name:
            fields[field_name] = field_value

    return fields


def _split_fields(content: str) -> list[str]:
    """Split field assignments by top-level commas."""
    parts = []
    current = ""
    depth = 0
    in_quotes = False

    for char in content:
        if char == '"' and (not current or current[-1] != "\\"):
            in_quotes = not in_quotes
        elif not in_quotes:
            if char in "{(":
                depth += 1
            elif char in "})":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(current)
                current = ""
                continue

        current += char

    if current.strip():
        parts.append(current)

    return parts


def _unquote_value(value: str) -> str:
    """Remove quotes from field value."""
    value = value.strip()

    # Remove outer braces
    if value.startswith("{") and value.endswith("}"):
        return value[1:-1]

    # Remove outer quotes
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    return value


def _parse_string_def(line: str) -> tuple[Optional[str], Optional[str]]:
    """Parse @string definition."""
    # Match @string{key = value}
    match = re.match(r"@string\s*\{\s*(\w+)\s*=\s*(.+)\s*\}", line, re.IGNORECASE | re.DOTALL)
    if not match:
        return None, None

    key = match.group(1)
    value_str = match.group(2).strip()
    value = _unquote_value(value_str)

    return key, value


def _extract_preamble(
    line: str, line_idx: int, line_ending: str, lines: list[str]
) -> Optional[str]:
    """Extract @preamble content."""
    match = re.match(r"@preamble\s*{\s*", line, re.IGNORECASE)
    if not match:
        return None

    content = _extract_balanced_value(line, match.end() - 1, line_idx, line_ending, lines)
    return f"@preamble{{{content}}}" if content is not None else None


def _extract_balanced_value(
    line: str, start_pos: int, line_idx: int, line_ending: str, lines: list[str]
) -> Optional[str]:
    """Extract content within balanced braces from starting position."""
    content = ""
    brace_count = 0
    i = start_pos
    current_line = line

    while i < len(current_line):
        char = current_line[i]
        if char == "{":
            if brace_count > 0:
                content += char
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                return content
            content += char
        else:
            content += char
        i += 1

    # Continue to next lines
    line_idx += 1
    while line_idx < len(lines) and brace_count > 0:
        current_line = lines[line_idx]
        for char in current_line:
            if char == "{":
                if brace_count > 0:
                    content += char
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return content
                content += char
            else:
                content += char
        content += line_ending
        line_idx += 1

    return content if brace_count == 0 else None
