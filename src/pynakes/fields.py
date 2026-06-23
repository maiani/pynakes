"""Field-level operations: rename, move, append, and clear.

Each operation walks the library and edits matching entries surgically (only
the touched field changes in a diff). A ``where`` filter — a predicate over a
:class:`~pynakes.model.BibEntry`, or one built from a query string via
:func:`parse_query` — restricts which entries are affected.
"""

import re
from collections.abc import Callable, Iterator
from typing import Optional

from pynakes.editing import (
    append_delimited_field,
    remove_entry_field,
    rename_entry_field,
    set_entry_field,
)
from pynakes.model import BibEntry, BibFile

QueryFilter = Optional[Callable[[BibEntry], bool]]


def _selected(lib: BibFile, where: QueryFilter) -> Iterator[BibEntry]:
    for entry in lib.entries.values():
        if where is None or where(entry):
            yield entry


def rename_field(lib: BibFile, old: str, new: str, where: QueryFilter = None) -> int:
    """Rename field ``old`` to ``new`` on matching entries.

    Returns the number of entries changed. Entries already using ``new`` (and
    lacking ``old``) are left untouched. Modifies ``lib`` in place.
    """
    return sum(rename_entry_field(e, old, new) for e in _selected(lib, where))


def move_field(lib: BibFile, old: str, new: str, where: QueryFilter = None) -> int:
    """Move field ``old`` to ``new``, but only where ``new`` is not already set.

    Unlike :func:`rename_field`, this never clobbers an existing target field;
    entries that already have ``new`` are skipped. Returns the number changed.
    """
    count = 0
    for entry in _selected(lib, where):
        if old in entry.fields and new not in entry.fields:
            if rename_entry_field(entry, old, new):
                count += 1
    return count


def append_field(
    lib: BibFile,
    field: str,
    value: str,
    where: QueryFilter = None,
    delim: str = ",",
    join: str = ", ",
) -> int:
    """Append ``value`` to a delimited ``field`` on matching entries.

    The field is created if absent; duplicate values are not re-added. Returns
    the number of entries changed. Modifies ``lib`` in place.
    """
    return sum(append_delimited_field(e, field, value, delim, join) for e in _selected(lib, where))


def clear_field(lib: BibFile, field: str, where: QueryFilter = None) -> int:
    """Remove ``field`` from matching entries. Returns the number changed."""
    return sum(remove_entry_field(e, field) for e in _selected(lib, where))


# --- title capitalization protection ---------------------------------------

_TITLE_TOKEN_RE = re.compile(r"(?:[A-Z]\.){2,}|[A-Za-z][A-Za-z0-9]*(?:[-+][A-Za-z0-9]+)*")


def _protect_token(token: str, terms: set[str]) -> bool:
    """Return whether ``token`` should be brace-protected in a BibTeX title."""
    if token in terms:
        return True
    if re.fullmatch(r"(?:[A-Z]\.){2,}", token):
        return True

    letters = [ch for ch in token if ch.isalpha()]
    if len(letters) >= 2 and all(ch.isupper() for ch in letters):
        return True
    if any(ch.isdigit() for ch in token) and any(ch.isupper() for ch in token):
        return True

    for i, ch in enumerate(token):
        if i > 0 and ch.isupper():
            return True
    return False


def _protect_title_value(value: str, terms: set[str]) -> str:
    """Brace-protect capitalization-sensitive tokens outside existing braces."""
    out: list[str] = []
    depth = 0
    i = 0

    while i < len(value):
        ch = value[i]
        if ch == "{":
            depth += 1
            out.append(ch)
            i += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            out.append(ch)
            i += 1
            continue

        if depth == 0:
            match = _TITLE_TOKEN_RE.match(value, i)
            if match:
                token = match.group(0)
                out.append(f"{{{token}}}" if _protect_token(token, terms) else token)
                i = match.end()
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def title_capitalization_is_protected(value: str, terms: list[str] | None = None) -> bool:
    """Return whether ``value`` already meets pynakes' title-protection policy.

    This is the non-mutating counterpart to :func:`protect_title_capitalization`.
    Keeping the predicate next to the transformation ensures lint and normalize
    cannot drift apart over which tokens need brace protection.
    """
    return _protect_title_value(value, set(terms or [])) == value


def protect_title_capitalization(
    lib: BibFile,
    field: str = "title",
    where: QueryFilter = None,
    terms: list[str] | None = None,
) -> int:
    """Brace-protect capitalization-sensitive tokens in title-like fields.

    Existing brace groups are preserved and never nested again. By default, this
    protects all-uppercase acronyms, dotted acronyms, mixed-case technical names,
    and uppercase/digit tokens such as ``GPT-4``. ``terms`` can be used for
    explicit case-sensitive matches.
    """
    count = 0
    protected_terms = set(terms or [])
    for entry in _selected(lib, where):
        if field not in entry.fields:
            continue
        old_value = entry.fields[field]
        new_value = _protect_title_value(old_value, protected_terms)
        if set_entry_field(entry, field, new_value):
            count += 1
    return count


# --- query filters ---------------------------------------------------------

# Supports: `FIELD contains "x"`, `FIELD = "x"` / `FIELD == "x"`, `FIELD exists`.
# The special field names `type` and `key` match the entry type and citation
# key respectively, rather than a stored field.
_QUERY_RE = re.compile(
    r"""^\s*(?P<field>\w+)\s+
        (?P<op>contains|==|=|exists)
        (?:\s+(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>\S+)))?
        \s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def parse_query(expr: str) -> Callable[[BibEntry], bool]:
    """Compile a simple ``--where`` expression into a predicate.

    Examples::

        title contains "digital currency"
        type = article
        key == "Smith2020"
        doi exists

    Raises:
        ValueError: if the expression cannot be parsed.
    """
    match = _QUERY_RE.match(expr)
    if not match:
        raise ValueError(f"Invalid query expression: {expr!r}")

    field = match.group("field").lower()
    op = match.group("op").lower()
    value = match.group("dq")
    if value is None:
        value = match.group("sq")
    if value is None:
        value = match.group("bare")

    def get(entry: BibEntry) -> str:
        if field == "type":
            return entry.type
        if field == "key":
            return entry.key
        return entry.fields.get(field, "")

    if op == "exists":
        return lambda e: field in ("type", "key") or field in e.fields

    if value is None:
        raise ValueError(f"Query operator {op!r} requires a value: {expr!r}")

    needle = value.lower()
    if op == "contains":
        return lambda e: needle in get(e).lower()
    return lambda e: get(e).lower() == needle
