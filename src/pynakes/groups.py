"""JabRef group management.

JabRef stores per-entry group membership in a ``groups`` field whose value is a
semicolon-delimited list (e.g. ``groups = {Machine Learning; AI Papers}``).
These helpers read and edit that field while preserving all other formatting
via the surgical raw-text editing in :mod:`pynakes.editing`.
"""

from pynakes._text_utils import check_balanced_braces
from pynakes.editing import append_delimited_field, remove_entry_field, set_entry_field
from pynakes.model import BibEntry, BibFile

GROUPS_DELIM = ";"
GROUPS_JOIN = "; "


def _parse_groups(value: str) -> list[str]:
    return [g.strip() for g in value.split(GROUPS_DELIM) if g.strip()]


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
    check_balanced_braces(f"Group name {group!r}", group)
    count = 0
    for entry in lib.entries.get_all(key):
        if append_delimited_field(entry, "groups", group, GROUPS_DELIM, GROUPS_JOIN):
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
            set_entry_field(entry, "groups", GROUPS_JOIN.join(groups))
        else:
            remove_entry_field(entry, "groups")
        count += 1
    return count


def _renamed_value(value: str, old: str, new: str) -> str | None:
    """Return ``value`` with membership ``old`` renamed to ``new``, or ``None``.

    Matches whole names only, so ``Optics Lab`` is not a membership of
    ``Optics``. The first membership that is (or becomes) ``new`` keeps its
    place and its surrounding spacing; every later one is dropped, so an entry
    that already named ``new``, or named ``old`` twice, ends up naming ``new``
    exactly once. Memberships of other groups keep their text and separators.
    """
    pieces = value.split(GROUPS_DELIM)
    if old not in (piece.strip() for piece in pieces):
        return None
    kept: list[str] = []
    seen_new = False
    for piece in pieces:
        name = piece.strip()
        if name in (old, new):
            if seen_new:
                continue
            seen_new = True
            if name == old:
                lead = piece[: len(piece) - len(piece.lstrip())]
                trail = piece[len(piece.rstrip()) :]
                piece = f"{lead}{new}{trail}"
        kept.append(piece)
    return GROUPS_DELIM.join(kept)


def rename_group_memberships(lib: BibFile, old: str, new: str) -> list[str]:
    """Rename membership ``old`` to ``new`` in every entry's ``groups`` field.

    Exact-name matching: only a membership spelled exactly ``old`` changes.
    Each changed entry is edited surgically, so only its ``groups`` line
    differs and every other entry stays byte-identical. Returns the keys of the
    changed entries in file order, each once even when the key is duplicated.
    Modifies ``lib`` in place.
    """
    check_balanced_braces(f"Group name {new!r}", new)
    changed: list[str] = []
    for entry in lib.entries.values():
        value = entry.fields.get("groups")
        if not value:
            continue
        renamed = _renamed_value(value, old, new)
        if renamed is None or renamed == value:
            continue
        set_entry_field(entry, "groups", renamed)
        if entry.key not in changed:
            changed.append(entry.key)
    return changed
