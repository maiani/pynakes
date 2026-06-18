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
)
from pynakes.model import BibEntry, BibLibrary

QueryFilter = Optional[Callable[[BibEntry], bool]]


def _selected(lib: BibLibrary, where: QueryFilter) -> Iterator[BibEntry]:
    for entry in lib.entries.values():
        if where is None or where(entry):
            yield entry


def rename_field(lib: BibLibrary, old: str, new: str, where: QueryFilter = None) -> int:
    """Rename field ``old`` to ``new`` on matching entries.

    Returns the number of entries changed. Entries already using ``new`` (and
    lacking ``old``) are left untouched. Modifies ``lib`` in place.
    """
    return sum(rename_entry_field(e, old, new) for e in _selected(lib, where))


def move_field(lib: BibLibrary, old: str, new: str, where: QueryFilter = None) -> int:
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
    lib: BibLibrary,
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
    return sum(
        append_delimited_field(e, field, value, delim, join)
        for e in _selected(lib, where)
    )


def clear_field(lib: BibLibrary, field: str, where: QueryFilter = None) -> int:
    """Remove ``field`` from matching entries. Returns the number changed."""
    return sum(remove_entry_field(e, field) for e in _selected(lib, where))


# --- query filters ---------------------------------------------------------

# Supports: `FIELD contains "x"`, `FIELD = "x"` / `FIELD == "x"`, `FIELD exists`.
# The special field name `type` matches the entry type rather than a field.
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
        return entry.fields.get(field, "")

    if op == "exists":
        return lambda e: field == "type" or field in e.fields

    if value is None:
        raise ValueError(f"Query operator {op!r} requires a value: {expr!r}")

    needle = value.lower()
    if op == "contains":
        return lambda e: needle in get(e).lower()
    return lambda e: get(e).lower() == needle
