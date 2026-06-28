"""JabRef group management.

JabRef stores per-entry group membership in a ``groups`` field whose value is a
semicolon-delimited list (e.g. ``groups = {Machine Learning; AI Papers}``).
These helpers read and edit that field while preserving all other formatting
via the surgical raw-text editing in :mod:`pynakes.editing`.
"""

from pynakes.editing import append_delimited_field, remove_entry_field, set_entry_field
from pynakes.model import BibEntry, BibFile

_DELIM = ";"
_JOIN = "; "


def _parse_groups(value: str) -> list[str]:
    return [g.strip() for g in value.split(_DELIM) if g.strip()]


def entry_groups(entry: BibEntry) -> list[str]:
    """Return the group names a single entry belongs to (first-seen order)."""
    return _parse_groups(entry.fields.get("groups") or "")


def list_groups(lib: BibFile) -> list[str]:
    """Return all distinct group names across the library, in first-seen order."""
    seen: dict[str, None] = {}
    for entry in lib.entries.values():
        for group in _parse_groups(entry.fields.get("groups") or ""):
            seen.setdefault(group, None)
    return list(seen)


def list_entries_in_group(lib: BibFile, group: str) -> list[str]:
    """Return the keys of entries that belong to ``group``."""
    return [
        entry.key
        for entry in lib.entries.values()
        if group in _parse_groups(entry.fields.get("groups") or "")
    ]


def add_to_group(lib: BibFile, key: str, group: str) -> int:
    """Add ``group`` to every entry with citation key ``key``.

    Returns the number of entries newly added (already-member entries are
    skipped). Modifies ``lib`` in place.
    """
    count = 0
    for entry in lib.entries.get_all(key):
        if append_delimited_field(entry, "groups", group, _DELIM, _JOIN):
            count += 1
    return count


def remove_from_group(lib: BibFile, key: str, group: str) -> int:
    """Remove ``group`` from every entry with citation key ``key``.

    Drops the ``groups`` field entirely if it becomes empty. Returns the number
    of entries changed. Modifies ``lib`` in place.
    """
    count = 0
    for entry in lib.entries.get_all(key):
        groups = _parse_groups(entry.fields.get("groups") or "")
        if group not in groups:
            continue
        groups.remove(group)
        if groups:
            set_entry_field(entry, "groups", _JOIN.join(groups))
        else:
            remove_entry_field(entry, "groups")
        count += 1
    return count
