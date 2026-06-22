"""Surgical, minimal-diff editing of BibTeX entry text.

These helpers operate on a single entry's ``raw_content`` so that only the
changed field (or key) appears in a diff; everything else — field order,
spacing, capitalization-protection braces, blank lines — is preserved
byte-for-byte. When an entry has no ``raw_content`` (e.g. one constructed in
memory), the edit instead marks it ``modified`` so the writer reconstructs it.

The two layers:

* Pure string functions (``set_raw_field``, ``remove_raw_field``,
  ``rename_raw_field``, ``set_raw_key``, ``splice_into_text``) edit raw text.
* Entry-level helpers (``set_entry_field``, ``remove_entry_field``, ...) keep an
  entry's ``fields`` dict and its ``raw_content`` in sync, returning ``True``
  when something actually changed.
"""

import re
from collections.abc import Callable, Iterable
from typing import Optional, Union

from pynakes.model import BibEntry

# Entry header: ``@type{ key ,`` — groups the part before the key, the key, and
# the trailing comma so the key can be swapped without touching anything else.
# The key group is ``*`` (not ``+``) so an empty key (``@article{,``) can be
# filled in by ``keys generate``.
_HEADER_RE = re.compile(r"(@\w+\s*\{\s*)([^,\s]*)(\s*,)")

# The leading ``@type`` token, so the entry type can be swapped without touching
# the key, braces, or anything else.
_TYPE_RE = re.compile(r"(@)(\w+)")


# --- locating a field within raw entry text --------------------------------


def _scan_value_end(raw: str, pos: int) -> int:
    """Return the index just past the field value starting at ``pos``.

    Handles brace-delimited values (with nesting), quoted values, and bare
    words/numbers (terminated by a comma, closing brace, or line ending).
    """
    if pos >= len(raw):
        return pos
    ch = raw[pos]
    if ch == "{":
        depth = 0
        i = pos
        while i < len(raw):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return len(raw)
    if ch == '"':
        i = pos + 1
        while i < len(raw):
            if raw[i] == '"':
                return i + 1
            i += 1
        return len(raw)
    i = pos
    while i < len(raw) and raw[i] not in ",}\r\n":
        i += 1
    return i


def _find_field(raw: str, field_name: str) -> Optional[tuple[int, int, int]]:
    """Locate a field assignment in raw entry text.

    Returns ``(name_start, value_start, value_end)`` for the first real
    assignment of ``field_name`` (one whose name begins right after the entry's
    opening brace or a field-separating comma), or ``None`` if absent. Matching
    is case-insensitive; the name in ``raw`` has the same length as
    ``field_name`` because they share the same letters.
    """
    for m in re.finditer(re.escape(field_name) + r"\s*=\s*", raw, re.IGNORECASE):
        # Reject matches inside a value: the name must be preceded only by
        # whitespace back to a "{" or "," (i.e. it starts a field assignment).
        k = m.start() - 1
        while k >= 0 and raw[k] in " \t\r\n":
            k -= 1
        if k < 0 or raw[k] in "{,":
            return m.start(), m.end(), _scan_value_end(raw, m.end())
    return None


# --- pure raw-text edits ---------------------------------------------------


def set_raw_field(raw: str, field_name: str, new_value: str) -> str:
    """Set ``field_name = {new_value}`` in raw entry text.

    Replaces the value in place if the field exists; otherwise inserts the
    field just before the entry's closing brace (adding a trailing comma to the
    previous last field if needed).
    """
    found = _find_field(raw, field_name)
    if found:
        _, value_start, value_end = found
        return raw[:value_start] + "{" + new_value + "}" + raw[value_end:]

    line_ending = "\r\n" if "\r\n" in raw else "\n"
    close = raw.rfind("}")
    if close == -1:
        return raw
    body = raw[:close].rstrip()
    if not body.endswith(","):
        body += ","
    return f"{body}{line_ending}  {field_name} = {{{new_value}}}{line_ending}{raw[close:]}"


def remove_raw_field(raw: str, field_name: str) -> str:
    """Remove a field assignment (and its line) from raw entry text."""
    found = _find_field(raw, field_name)
    if not found:
        return raw
    name_start, _, value_end = found

    end = value_end
    if end < len(raw) and raw[end] == ",":
        end += 1

    start = name_start
    while start > 0 and raw[start - 1] in " \t":
        start -= 1
    if start > 0 and raw[start - 1] == "\n":
        start -= 1
        if start > 0 and raw[start - 1] == "\r":
            start -= 1

    return raw[:start] + raw[end:]


def rename_raw_field(raw: str, old_name: str, new_name: str) -> str:
    """Rename a field (keeping its value and position) in raw entry text."""
    found = _find_field(raw, old_name)
    if not found:
        return raw
    name_start, _, _ = found
    return raw[:name_start] + new_name + raw[name_start + len(old_name) :]


def set_raw_key(raw: str, new_key: str) -> str:
    """Replace the citation key in an entry's header."""
    return _HEADER_RE.sub(lambda m: f"{m.group(1)}{new_key}{m.group(3)}", raw, count=1)


def set_raw_type(raw: str, new_type: str) -> str:
    """Replace the entry type (the ``@type`` token) in an entry's header."""
    return _TYPE_RE.sub(lambda m: f"{m.group(1)}{new_type}", raw, count=1)


def splice_into_text(original_text: str, edits: Iterable[tuple[str, str]]) -> Union[str, None]:
    """Splice surgically-edited entry blocks back into the original file text.

    Each edit is ``(old_raw, new_raw)``. Replacing each entry's exact original
    block in the source preserves all other formatting (inter-entry blank
    lines, comment spacing), yielding a minimal diff. Returns ``None`` if any
    block cannot be located, so the caller can fall back to re-serialization.
    """
    text = original_text
    for old_raw, new_raw in edits:
        if old_raw == new_raw:
            continue
        if not old_raw or old_raw not in text:
            return None
        text = text.replace(old_raw, new_raw, 1)
    return text


# --- entry-level edits (keep fields dict and raw_content in sync) -----------


def _apply(entry: BibEntry, editor: Callable[[str], str]) -> None:
    if entry.raw_content:
        entry.raw_content = editor(entry.raw_content)
    else:
        entry.modified = True


def set_entry_field(entry: BibEntry, name: str, value: str) -> bool:
    """Set a field to an exact value. Returns ``True`` if it changed."""
    if entry.fields.get(name) == value:
        return False
    entry.fields[name] = value
    _apply(entry, lambda raw: set_raw_field(raw, name, value))
    return True


def remove_entry_field(entry: BibEntry, name: str) -> bool:
    """Remove a field. Returns ``True`` if the field was present."""
    if name not in entry.fields:
        return False
    del entry.fields[name]
    _apply(entry, lambda raw: remove_raw_field(raw, name))
    return True


def rename_entry_field(entry: BibEntry, old: str, new: str) -> bool:
    """Rename a field, preserving its value and position. Returns ``True`` if changed."""
    if old not in entry.fields or old == new:
        return False
    # Rebuild the dict so the renamed field keeps its original position.
    entry.fields = {(new if k == old else k): v for k, v in entry.fields.items()}
    _apply(entry, lambda raw: rename_raw_field(raw, old, new))
    return True


def set_entry_type(entry: BibEntry, new_type: str) -> bool:
    """Change an entry's type (e.g. ``phdthesis`` → ``thesis``). Returns ``True`` if changed."""
    if entry.type == new_type:
        return False
    entry.type = new_type
    _apply(entry, lambda raw: set_raw_type(raw, new_type))
    return True


def rename_entry_key(entry: BibEntry, new_key: str) -> bool:
    """Change an entry's citation key. Returns ``True`` if changed."""
    if entry.key == new_key:
        return False
    entry.key = new_key
    _apply(entry, lambda raw: set_raw_key(raw, new_key))
    return True


def append_delimited_field(entry: BibEntry, name: str, value: str, delim: str, join: str) -> bool:
    """Append ``value`` to a delimited field, de-duplicating. Returns ``True`` if changed."""
    existing = entry.fields.get(name, "")
    items = [p.strip() for p in existing.split(delim) if p.strip()]
    if value in items:
        return False
    items.append(value)
    new_value = join.join(items)
    entry.fields[name] = new_value
    _apply(entry, lambda raw: set_raw_field(raw, name, new_value))
    return True
