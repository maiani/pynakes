"""Bulk field-level operations over matching bibliography entries.

Each operation walks the library and edits matching entries surgically (only
the touched field changes in a diff). A ``where`` filter — a predicate over a
:class:`~pynakes.model.BibEntry`, or one built from a query string via
:func:`parse_query` — restricts which entries are affected.
"""

import re
from collections.abc import Iterable, Iterator

from pynakes import query
from pynakes.editing import (
    append_delimited_field,
    remove_entry_field,
    rename_entry_field,
    set_entry_field,
)
from pynakes.model import BibEntry, BibFile, QueryFilter

TITLE_FIELDS = ("title", "booktitle", "maintitle", "subtitle")


def _selected(lib: BibFile, where: QueryFilter) -> Iterator[BibEntry]:
    for entry in lib.entries.values():
        if where is None or where(entry):
            yield entry


def _resolve_field_name(entry: BibEntry, name: str) -> str:
    """Return ``name`` as it actually appears in ``entry.fields``, if present.

    BibTeX field names are case-insensitive, so a caller-supplied name (e.g.
    copied verbatim from a lint warning) may not match a stored key by-exact
    (a parsed entry's ``fields`` keys are always lowercase; hand-built ones may
    keep other casing). Falls back to ``name`` unchanged when no field of that
    name — in any case — exists on ``entry``.
    """
    if name in entry.fields:
        return name
    lowered = name.lower()
    for key in entry.fields:
        if key.lower() == lowered:
            return key
    return name


def rename_field(lib: BibFile, old: str, new: str, where: QueryFilter = None) -> int:
    """Rename field ``old`` to ``new`` on matching entries.

    ``old`` is matched case-insensitively against each entry's stored field
    names. Returns the number of entries changed. Entries already using
    ``new`` (and lacking ``old``) are left untouched. Modifies ``lib`` in place.
    """
    count = 0
    for entry in _selected(lib, where):
        if rename_entry_field(entry, _resolve_field_name(entry, old), new):
            count += 1
    return count


def set_field(lib: BibFile, field: str, value: str, where: QueryFilter = None) -> int:
    """Set or replace ``field`` on matching entries.

    ``field`` is matched case-insensitively against stored field names, avoiding
    a duplicate field with different casing. Returns the number of entries
    changed and modifies ``lib`` in place.
    """
    count = 0
    for entry in _selected(lib, where):
        actual_field = _resolve_field_name(entry, field)
        if set_entry_field(entry, actual_field, value):
            count += 1
    return count


def move_field(lib: BibFile, old: str, new: str, where: QueryFilter = None) -> int:
    """Move field ``old`` to ``new``, but only where ``new`` is not already set.

    Both ``old`` and ``new`` are matched case-insensitively against each
    entry's stored field names. Unlike :func:`rename_field`, this never
    clobbers an existing target field; entries that already have ``new`` are
    skipped. Returns the number changed.
    """
    count = 0
    for entry in _selected(lib, where):
        actual_old = _resolve_field_name(entry, old)
        actual_new = _resolve_field_name(entry, new)
        if actual_old in entry.fields and actual_new not in entry.fields:
            if rename_entry_field(entry, actual_old, new):
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

    ``field`` is matched case-insensitively against each entry's stored field
    names, so an existing mixed-case field is updated in place rather than
    duplicated. The field is created (using ``field`` as given) if absent;
    duplicate values are not re-added. Returns the number of entries changed.
    Modifies ``lib`` in place.
    """
    count = 0
    for entry in _selected(lib, where):
        actual_field = _resolve_field_name(entry, field)
        if append_delimited_field(entry, actual_field, value, delim, join):
            count += 1
    return count


def clear_field(lib: BibFile, field: str, where: QueryFilter = None) -> int:
    """Remove ``field`` from matching entries, matched case-insensitively.

    Returns the number changed.
    """
    count = 0
    for entry in _selected(lib, where):
        if remove_entry_field(entry, _resolve_field_name(entry, field)):
            count += 1
    return count


# --- title capitalization protection ---------------------------------------

_TITLE_TOKEN_RE = re.compile(r"(?:[A-Z]\.){2,}|[A-Za-z][A-Za-z0-9]*(?:[-+][A-Za-z0-9]+)*")


def _protect_token(token: str, terms: set[str]) -> bool:
    """Return whether ``token`` should be brace-protected in a BibTeX title."""
    if not token:
        return False
    if token in terms:
        return True
    if re.fullmatch(r"(?:[A-Z]\.){2,}", token):
        return True

    letters = [ch for ch in token if ch.isalpha()]
    if len(letters) >= 2 and all(ch.isupper() for ch in letters):
        return True
    if any(ch.isdigit() for ch in token) and any(ch.isupper() for ch in token):
        return True

    for part in [t for t in re.split(r"[-+]", token) if t]:
        for i, ch in enumerate(part):
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


def parse_query(expr: str, *, cited_keys: Iterable[str] | None = None) -> query.Node:
    """Compile a ``--where`` expression into a predicate.

    Examples::

        title contains "digital currency"
        type = article
        key == "Smith2020"
        doi exists
        year >= 2025 and type in [article, inproceedings]

    The grammar lives in :mod:`pynakes.query`, shared by every command that
    selects entries; see :func:`pynakes.query.parse_query` for its full
    description and the meaning of ``cited_keys``.

    Raises:
        ValueError: if the expression cannot be parsed.
    """
    return query.parse_query(expr, cited_keys=cited_keys)
