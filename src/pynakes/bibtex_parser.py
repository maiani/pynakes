"""BibTeX file parser with round-trip preservation."""

import logging
import re
from typing import Optional

from pynakes.metadata import metadata_blocks_to_dict, parse_metadata_comment
from pynakes.model import (
    BibEntry,
    BibFile,
    EntryStore,
    MetadataBlock,
    resolve_field_value,
    resolve_string_definitions,
)

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


def parse_bib(text: str) -> BibFile:
    """Parse BibTeX text into a BibFile.

    Preserves formatting and metadata for round-trip fidelity. Duplicate
    citation keys are preserved (not an error): they are surfaced via
    ``library.entries.duplicate_keys()`` and reported by the linter.

    Args:
        text: BibTeX file content as string

    Returns:
        BibFile with parsed entries

    Raises:
        ParseError: If BibTeX is structurally malformed (e.g. unbalanced braces)
    """
    line_ending = detect_line_ending(text)

    entries = EntryStore()
    strings: dict[str, str] = {}
    raw_strings: list[str] = []
    preambles: list[str] = []
    raw_comments: list[str] = []
    jabref_metadata_blocks: list[MetadataBlock] = []
    pynakes_metadata_blocks: list[MetadataBlock] = []

    position = 0
    while position < len(text):
        char = text[position]
        if char == "%" and not _is_escaped(text, position):
            line_end = _line_end(text, position)
            raw_comments.append(text[position:line_end])
            position = line_end
            continue
        if char != "@":
            position += 1
            continue

        header = _TOP_LEVEL_HEADER.match(text, position)
        if header is None:
            position += 1
            continue

        entry_type = header.group("type")
        normalized_type = entry_type.lower()
        opener = header.group("opener")
        block_end = _find_block_end(text, header.start("opener"))
        if block_end is None:
            line = _line_number(text, position)
            message = "Unmatched braces" if opener == "{" else "Unmatched parentheses"
            raise ParseError(f"{message} in {normalized_type} block", line)

        raw_block = text[position:block_end]
        body = text[header.end() : block_end - 1]
        line_num = _line_number(text, position)

        if normalized_type == "string":
            key, value = _parse_string_def(body)
            if key is not None and value is not None:
                strings[key] = value
                raw_strings.append(raw_block)
        elif normalized_type == "preamble":
            # ``preamble`` deliberately retains its source delimiter and
            # formatting; it has no field/key structure to normalize.
            preambles.append(raw_block)
        elif normalized_type == "comment":
            _record_comment(
                raw_block,
                body,
                raw_comments,
                jabref_metadata_blocks,
                pynakes_metadata_blocks,
            )
        else:
            entry = _parse_entry(entry_type, body, raw_block)
            if entry.key in entries:
                logger.warning(
                    "Duplicate citation key %r (line %d); preserving both entries",
                    entry.key,
                    line_num,
                )
            entries.add(entry)

        position = block_end

    resolved_strings = resolve_string_definitions(strings)
    for entry in entries.values():
        entry.fields = {
            name: resolve_field_value(value, resolved_strings)
            for name, value in entry.fields.items()
        }

    return BibFile(
        entries=entries,
        strings=resolved_strings,
        raw_strings=raw_strings,
        preamble=preambles,
        raw_comments=raw_comments,
        jabref_metadata=metadata_blocks_to_dict(jabref_metadata_blocks),
        jabref_metadata_blocks=jabref_metadata_blocks,
        pynakes_metadata=metadata_blocks_to_dict(pynakes_metadata_blocks),
        pynakes_metadata_blocks=pynakes_metadata_blocks,
        line_ending=line_ending,
    )


_TOP_LEVEL_HEADER = re.compile(
    r"@(?P<type>[A-Za-z][A-Za-z0-9_:-]*)\s*(?P<opener>[{(])", re.IGNORECASE
)


def _parse_entry(entry_type: str, body: str, raw_content: str) -> BibEntry:
    """Parse an entry body after its outer delimiter has been scanned."""
    key_part, fields_part = _split_once_top_level(_strip_tex_comments(body), ",")
    key = key_part.strip()
    fields = _parse_fields(fields_part) if fields_part is not None else {}
    return BibEntry(key=key, type=entry_type, fields=fields, raw_content=raw_content)


def _parse_fields(content: str) -> dict[str, str]:
    """Extract field assignments, respecting nested braces and quoted values."""
    fields: dict[str, str] = {}
    for part in _split_top_level(content, ","):
        name, value = _split_once_top_level(part, "=")
        field_name = name.strip().lower()
        if field_name:
            fields[field_name] = value.strip() if value is not None else ""
    return fields


def _parse_string_def(body: str) -> tuple[Optional[str], Optional[str]]:
    """Parse the body of a ``@string`` declaration."""
    key, value = _split_once_top_level(_strip_tex_comments(body), "=")
    key = key.strip()
    if not key or value is None:
        return None, None
    # Keep the complete value expression until all definitions have been
    # collected: it may concatenate literals and macros declared later.
    return key, value.strip()


def _record_comment(
    raw_comment: str,
    body: str,
    raw_comments: list[str],
    jabref_metadata_blocks: list[MetadataBlock],
    pynakes_metadata_blocks: list[MetadataBlock],
) -> None:
    """Store one ``@comment`` block and classify any metadata it contains."""
    comment_index = len(raw_comments)
    raw_comments.append(raw_comment)
    for block in parse_metadata_comment(
        body,
        raw=raw_comment,
        comment_index=comment_index,
    ):
        if block.namespace == "pynakes":
            pynakes_metadata_blocks.append(block)
        else:
            jabref_metadata_blocks.append(block)


def _find_block_end(text: str, opener_index: int) -> int | None:
    """Return the position after a balanced top-level BibTeX block.

    BibTeX permits both ``{...}`` and ``(...)`` outer delimiters. Braces in a
    quoted value do not affect the enclosing block, while parentheses inside a
    braced value are ordinary text. TeX comments are likewise ignored for
    structural scanning.
    """
    opener = text[opener_index]
    if opener not in "{(":
        return None

    brace_depth = 1 if opener == "{" else 0
    paren_depth = 1 if opener == "(" else 0
    in_quotes = False
    in_comment = False

    for index in range(opener_index + 1, len(text)):
        char = text[index]
        if in_comment:
            if char in "\r\n":
                in_comment = False
            continue
        if char == "%" and not in_quotes and not _is_escaped(text, index):
            in_comment = True
            continue

        quote_allowed = (opener == "{" and brace_depth == 1) or (opener == "(" and brace_depth == 0)
        if char == '"' and quote_allowed and not _is_escaped(text, index):
            in_quotes = not in_quotes
            continue
        if in_quotes:
            continue

        if brace_depth:
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
                if brace_depth == 0 and opener == "{":
                    return index + 1
            continue

        if opener == "(":
            if char == "{":
                brace_depth = 1
            elif char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
                if paren_depth == 0:
                    return index + 1
    return None


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split text on one separator outside braced/quoted value syntax."""
    parts: list[str] = []
    start = 0
    brace_depth = 0
    paren_depth = 0
    in_quotes = False
    in_comment = False

    for index, char in enumerate(text):
        if in_comment:
            if char in "\r\n":
                in_comment = False
            continue
        if char == "%" and not in_quotes and not _is_escaped(text, index):
            in_comment = True
            continue
        if char == '"' and brace_depth == 0 and not _is_escaped(text, index):
            in_quotes = not in_quotes
            continue
        if in_quotes:
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}" and brace_depth:
            brace_depth -= 1
        elif brace_depth == 0:
            if char == "(":
                paren_depth += 1
            elif char == ")" and paren_depth:
                paren_depth -= 1
            elif char == separator and paren_depth == 0:
                parts.append(text[start:index])
                start = index + 1
    parts.append(text[start:])
    return parts


def _split_once_top_level(text: str, separator: str) -> tuple[str, str | None]:
    """Split *text* at its first top-level separator, if it has one."""
    parts = _split_top_level(text, separator)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], separator.join(parts[1:])


def _strip_tex_comments(text: str) -> str:
    """Remove unescaped TeX comments while retaining line boundaries."""
    output: list[str] = []
    in_comment = False
    for index, char in enumerate(text):
        if in_comment:
            if char in "\r\n":
                in_comment = False
                output.append(char)
            continue
        if char == "%" and not _is_escaped(text, index):
            in_comment = True
            continue
        output.append(char)
    return "".join(output)


def _is_escaped(text: str, index: int) -> bool:
    """Whether the character at *index* has an odd number of backslashes."""
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return bool(backslashes % 2)


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
