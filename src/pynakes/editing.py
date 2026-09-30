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

from pynakes._text_utils import _is_escaped
from pynakes.model import BibEntry

# Entry header: ``@type{ key ,`` / ``@type( key ,`` — groups the part before the key, the key, and
# the trailing comma so the key can be swapped without touching anything else.
# The key group is ``*`` (not ``+``) so an empty key (``@article{,``) can be
# filled in by ``keys generate``.
_HEADER_RE = re.compile(r"(@[A-Za-z][A-Za-z0-9_:-]*\s*[{(]\s*)([^,\s]*)(\s*,)")

# The leading ``@type`` token, so the entry type can be swapped without touching
# the key, braces, or anything else.
_TYPE_RE = re.compile(r"(@)([A-Za-z][A-Za-z0-9_:-]*)")
_FIELD_NAME_RE = re.compile(r"([A-Za-z][A-Za-z0-9_:-]*)\s*=")


# --- locating a field within raw entry text --------------------------------


def _scan_value_end(raw: str, pos: int) -> int:
    """Return the index just past the field value starting at ``pos``.

    Handles brace-delimited values (with nesting), quoted values, and bare
    words/numbers (terminated by a comma or closing delimiter).
    """
    if pos >= len(raw):
        return pos

    # A value may concatenate braced, quoted, and bare atoms. Scan the whole
    # expression rather than stopping after its first atom (for example,
    # ``prefix # {suffix}``).
    brace_depth = 0
    in_quotes = False
    i = pos
    while i < len(raw):
        char = raw[i]
        if char == '"' and not _is_escaped(raw, i) and brace_depth == 0:
            in_quotes = not in_quotes
            if not in_quotes and _next_nonspace(raw, i + 1) != "#":
                return i + 1
        elif not in_quotes:
            if char == "{":
                brace_depth += 1
            elif char == "}" and brace_depth:
                brace_depth -= 1
                if brace_depth == 0 and _next_nonspace(raw, i + 1) != "#":
                    return i + 1
            elif brace_depth == 0 and char in ",})":
                return i
            elif brace_depth == 0 and char == "%" and not _is_escaped(raw, i):
                # A field-level TeX comment ends a bare value; the parser
                # ignores it, so the value stops at the last character before.
                end = i
                while end > pos and raw[end - 1].isspace():
                    end -= 1
                return end
        i += 1
    return len(raw)


def _next_nonspace(raw: str, pos: int) -> str | None:
    """Return the next non-whitespace character after ``pos``."""
    i = pos
    while i < len(raw) and raw[i].isspace():
        i += 1
    return raw[i] if i < len(raw) else None


_ASSIGNMENT_RE = re.compile(r"\s*=\s*")


def _find_field(raw: str, field_name: str) -> tuple[int, int, int] | None:
    """Locate a field assignment in raw entry text.

    Returns ``(name_start, value_start, value_end)`` for the first top-level
    assignment of ``field_name``, or ``None`` if absent. The first occurrence
    is the one BibTeX reads when a field is repeated. Matching is
    case-insensitive. Text inside a braced or quoted value, or inside a
    field-level ``%`` comment, is never mistaken for an assignment.
    """
    wanted = field_name.lower()
    for name_start, name_end in _raw_field_name_spans(raw):
        if raw[name_start:name_end].lower() != wanted:
            continue
        assignment = _ASSIGNMENT_RE.match(raw, name_end)
        if assignment is None:
            continue
        value_start = assignment.end()
        return name_start, value_start, _scan_value_end(raw, value_start)
    return None


def _skip_comment(raw: str, i: int) -> int:
    """Return the index of the line break that ends a ``%`` comment at ``i``."""
    while i < len(raw) and raw[i] not in "\r\n":
        i += 1
    return i


def _raw_field_name_spans(raw: str) -> list[tuple[int, int]]:
    """Return spans of field names in an entry's top-level assignments.

    A regex alone would also find ``name =`` text inside a braced or quoted
    value, or in a commented-out line. This small scanner stays at the entry
    body's top level and skips field-level ``%`` comments exactly as the
    parser does, so it is safe to use for field edits and lint findings.
    """
    header = re.match(r"@[A-Za-z][A-Za-z0-9_:-]*\s*[{(]\s*[^,]*,", raw, re.IGNORECASE | re.DOTALL)
    if not header:
        return []

    spans: list[tuple[int, int]] = []
    depth = 0
    in_quotes = False
    i = header.end()
    while i < len(raw):
        char = raw[i]
        if in_quotes:
            if char == '"' and (i == 0 or raw[i - 1] != "\\"):
                in_quotes = False
            i += 1
            continue
        if char == '"':
            in_quotes = True
            i += 1
            continue
        if char == "%" and depth == 0 and not _is_escaped(raw, i):
            i = _skip_comment(raw, i)
            continue
        if char == "{":
            depth += 1
            i += 1
            continue
        if char in "})":
            if depth == 0:
                break
            depth -= 1
            i += 1
            continue
        if depth == 0:
            match = _FIELD_NAME_RE.match(raw, i)
            if match:
                spans.append((match.start(1), match.end(1)))
                i = match.end()
                continue
        i += 1
    return spans


def raw_field_names(raw: str) -> list[str]:
    """Return the source spelling of each top-level field name in ``raw``."""
    return [raw[start:end] for start, end in _raw_field_name_spans(raw)]


def raw_field_value(raw: str, field_name: str) -> str | None:
    """Return a field's unmodified source value, including ``#`` expressions.

    The parsed ``BibEntry.fields`` mapping contains resolved values, so lint
    checks that depend on BibTeX expression syntax must inspect ``raw_content``
    instead.  ``None`` means the assignment could not be located.
    """
    found = _find_field(raw, field_name)
    if found is None:
        return None
    _, value_start, value_end = found
    return raw[value_start:value_end].strip()


def _normalize_raw_field_names(raw: str) -> tuple[str, int]:
    """Lowercase field names in raw entry text, preserving all other bytes."""
    replacements = [
        (start, end, raw[start:end].lower())
        for start, end in _raw_field_name_spans(raw)
        if raw[start:end] != raw[start:end].lower()
    ]
    for start, end, replacement in reversed(replacements):
        raw = raw[:start] + replacement + raw[end:]
    return raw, len(replacements)


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

    line_ending = "\r\n" if "\r\n" in raw else ("\r" if "\r" in raw else "\n")
    close = _outer_close_position(raw)
    if close is None:
        return raw
    body = raw[:close].rstrip()
    last = _last_significant_index(body)
    if last is not None and body[last] != ",":
        # Put the separator straight after the last value, not at the end of
        # the body: a trailing ``% comment`` would otherwise swallow it.
        body = body[: last + 1] + "," + body[last + 1 :]
    return f"{body}{line_ending}  {field_name} = {{{new_value}}}{line_ending}{raw[close:]}"


def _last_significant_index(body: str) -> int | None:
    """Return the index of the last character the parser reads in ``body``.

    ``body`` is an entry without its closing delimiter. Whitespace and
    field-level ``%`` comments are skipped, since neither is part of a value.
    """
    opener = re.match(r"@[A-Za-z][A-Za-z0-9_:-]*\s*[{(]", body)
    if opener is None:
        return None
    last: int | None = None
    depth = 0
    in_quotes = False
    i = opener.end()
    while i < len(body):
        char = body[i]
        if not in_quotes and depth == 0 and char == "%" and not _is_escaped(body, i):
            i = _skip_comment(body, i)
            continue
        if char == '"' and depth == 0 and not _is_escaped(body, i):
            in_quotes = not in_quotes
        elif not in_quotes and char == "{":
            depth += 1
        elif not in_quotes and char == "}" and depth:
            depth -= 1
        if not char.isspace():
            last = i
        i += 1
    return last


def set_raw_field_expression(raw: str, field_name: str, expression: str) -> str:
    """Replace an existing field value with an exact BibTeX expression.

    Unlike :func:`set_raw_field`, this does not add braces around
    ``expression``. It is for syntax-aware repairs such as replacing the
    invalid bare month name ``june`` with the predefined ``jun`` macro.
    """
    found = _find_field(raw, field_name)
    if found is None:
        return raw
    _, value_start, value_end = found
    return raw[:value_start] + expression + raw[value_end:]


def _outer_close_position(raw: str) -> int | None:
    """Locate an entry's final ``}`` or ``)`` without inspecting field values."""
    close = len(raw) - 1
    while close >= 0 and raw[close].isspace():
        close -= 1
    return close if close >= 0 and raw[close] in "})" else None


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


def splice_into_text(original_text: str, edits: Iterable[tuple[str, str]]) -> str | None:
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
    entry.field_expressions[name] = "{" + value + "}"
    _apply(entry, lambda raw: set_raw_field(raw, name, value))
    return True


def set_entry_field_expression(
    entry: BibEntry,
    name: str,
    expression: str,
    semantic_value: str,
) -> bool:
    """Set an existing source field to an exact expression and semantic value.

    Parsed fields retain only semantic values, while some valid repairs need a
    bare macro rather than a brace-delimited literal. Entries without raw
    source fall back to a normal brace-quoted field update, which is valid
    BibTeX and avoids treating an in-memory value as source syntax.
    """
    if entry.raw_content:
        original = raw_field_value(entry.raw_content, name)
        if original is not None:
            if original == expression and entry.fields.get(name) == semantic_value:
                return False
            entry.fields[name] = semantic_value
            entry.field_expressions[name] = expression
            entry.raw_content = set_raw_field_expression(entry.raw_content, name, expression)
            return True
    return set_entry_field(entry, name, semantic_value)


def remove_entry_field(entry: BibEntry, name: str) -> bool:
    """Remove a field. Returns ``True`` if the field was present."""
    if name not in entry.fields:
        return False
    del entry.fields[name]
    entry.field_expressions.pop(name, None)
    _apply(entry, lambda raw: remove_raw_field(raw, name))
    return True


def rename_entry_field(entry: BibEntry, old: str, new: str) -> bool:
    """Rename a field, preserving its value and position. Returns ``True`` if changed."""
    if old not in entry.fields or old == new:
        return False
    # Rebuild the dict so the renamed field keeps its original position.
    entry.fields = {(new if k == old else k): v for k, v in entry.fields.items()}
    entry.field_expressions = {
        (new if k == old else k): v for k, v in entry.field_expressions.items()
    }
    _apply(entry, lambda raw: rename_raw_field(raw, old, new))
    return True


def normalize_entry_field_names(entry: BibEntry) -> int:
    """Lowercase an entry's field names, returning the number changed.

    Parsed entries retain their original spelling only in ``raw_content``;
    update that text directly while keeping the already-canonical fields map
    intact. Entries constructed without raw text are normalized in the map
    when doing so cannot collapse two distinct field names.
    """
    if entry.raw_content:
        updated, changed = _normalize_raw_field_names(entry.raw_content)
        if changed:
            entry.raw_content = updated
        return changed

    changed = sum(name != name.lower() for name in entry.fields)
    normalized = {name.lower(): value for name, value in entry.fields.items()}
    if len(normalized) != len(entry.fields) or normalized == entry.fields:
        return 0
    entry.fields = normalized
    entry.modified = True
    return changed


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
