"""JabRef group management.

JabRef stores per-entry group membership in a ``groups`` field whose value is a
comma-delimited list by default; existing semicolon libraries are supported.
These helpers read and edit that field while preserving all other formatting
via the surgical raw-text editing in :mod:`pynakes.editing`.
"""

from contextvars import ContextVar

from pynakes._text_utils import check_balanced_braces
from pynakes.editing import append_delimited_field, remove_entry_field, set_entry_field
from pynakes.model import BibEntry, BibFile

# Scoped by the CLI invocation, reset even when a command fails.
_groups_override: ContextVar[str | None] = ContextVar("groups_separator", default=None)


def _detect_separator(values: list[str]) -> str:
    comma = any("," in value for value in values)
    semicolon = any(";" in value for value in values)
    if comma and semicolon:
        raise ValueError(
            "Ambiguous groups separators: both comma and semicolon occur; set "
            "groups-separator to comma or semicolon with metadata set, or use "
            "the global --groups-separator option"
        )
    return ";" if semicolon else ","


def library_groups_separator(lib: BibFile, override: str | None = None) -> str:
    """Resolve an explicit override, native setting, JabRef declaration, or detection.

    Overrides and ``groups-separator`` accept ``auto``, ``comma``, or
    ``semicolon``. Auto preserves semicolon libraries, defaults new libraries
    to comma, and refuses mixed punctuation rather than guessing group names.
    Resolution does not modify metadata or existing entries.
    """
    choice = _separator_choice(lib, override)
    if choice == "auto":
        return _detect_separator([entry.fields.get("groups", "") for entry in lib.entries.values()])
    if choice not in {"comma", "semicolon"}:
        raise ValueError("groups-separator must be auto, comma, or semicolon")
    return "," if choice == "comma" else ";"


def _separator_choice(lib: BibFile, override: str | None = None) -> str:
    from pynakes.metadata.core import metadata_value

    choice = override or _groups_override.get() or metadata_value(lib, "groups-separator")
    if choice is not None:
        return choice.strip().lower()
    from pynakes.metadata.jabref import jabref_keyword_separator

    declared = jabref_keyword_separator(lib)
    if declared is not None:
        return "comma" if declared == "," else "semicolon"
    return "auto"


def _parse_groups(value: str, separator: str) -> list[str]:
    return [g.strip() for g in value.split(separator) if g.strip()]


def entry_groups(entry: BibEntry, *, separator: str | None = None) -> list[str]:
    """Return memberships; pass the library's resolved separator when available.

    With no library context, infer from this entry alone. Explicit separators
    are the literal comma or semicolon returned by ``library_groups_separator``.
    """
    value = entry.fields.get("groups") or ""
    return _parse_groups(value, separator or _detect_separator([value]))


def _validate_group(group: str, separator: str, lib: BibFile, override: str | None = None) -> None:
    check_balanced_braces(f"Group name {group!r}", group)
    if _separator_choice(lib, override) == "auto" and any(char in group for char in ",;"):
        raise ValueError("Punctuation in group names requires an explicit groups-separator setting")
    if not group.strip() or separator in group:
        raise ValueError(f"Group name must be nonempty and cannot contain separator {separator!r}")


def list_groups(lib: BibFile, *, separator: str | None = None) -> list[str]:
    """Return all distinct group names across the library, in first-seen order."""
    delimiter = library_groups_separator(lib, separator)
    seen: dict[str, None] = {}
    for entry in lib.entries.values():
        for group in _parse_groups(entry.fields.get("groups") or "", delimiter):
            seen.setdefault(group, None)
    return list(seen)


def list_entries_in_group(lib: BibFile, group: str, *, separator: str | None = None) -> list[str]:
    """Return the keys of entries that belong to ``group``."""
    delimiter = library_groups_separator(lib, separator)
    return [
        entry.key
        for entry in lib.entries.values()
        if group in _parse_groups(entry.fields.get("groups") or "", delimiter)
    ]


def add_to_group(lib: BibFile, key: str, group: str, *, separator: str | None = None) -> int:
    """Add ``group`` to every entry with citation key ``key``.

    Returns the number of entries newly added (already-member entries are
    skipped). Modifies ``lib`` in place.
    """
    delimiter = library_groups_separator(lib, separator)
    _validate_group(group, delimiter, lib, separator)
    count = 0
    for entry in lib.entries.get_all(key):
        if append_delimited_field(entry, "groups", group, delimiter, delimiter + " "):
            count += 1
    return count


def remove_from_group(lib: BibFile, key: str, group: str, *, separator: str | None = None) -> int:
    """Remove ``group`` from every entry with citation key ``key``.

    Drops the ``groups`` field entirely if it becomes empty. Returns the number
    of entries changed. Modifies ``lib`` in place.
    """
    delimiter = library_groups_separator(lib, separator)
    count = 0
    for entry in lib.entries.get_all(key):
        groups = _parse_groups(entry.fields.get("groups") or "", delimiter)
        if group not in groups:
            continue
        groups.remove(group)
        if groups:
            set_entry_field(entry, "groups", (delimiter + " ").join(groups))
        else:
            remove_entry_field(entry, "groups")
        count += 1
    return count


def _renamed_value(value: str, old: str, new: str, delimiter: str) -> str | None:
    """Return ``value`` with membership ``old`` renamed to ``new``, or ``None``.

    Matches whole names only, so ``Optics Lab`` is not a membership of
    ``Optics``. The first membership that is (or becomes) ``new`` keeps its
    place and its surrounding spacing; every later one is dropped, so an entry
    that already named ``new``, or named ``old`` twice, ends up naming ``new``
    exactly once. Memberships of other groups keep their text and separators.
    """
    pieces = value.split(delimiter)
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
    return delimiter.join(kept)


def rename_group_memberships(
    lib: BibFile, old: str, new: str, *, separator: str | None = None
) -> list[str]:
    """Rename membership ``old`` to ``new`` in every entry's ``groups`` field.

    Exact-name matching: only a membership spelled exactly ``old`` changes.
    Each changed entry is edited surgically, so only its ``groups`` line
    differs and every other entry stays byte-identical. Returns the keys of the
    changed entries in file order, each once even when the key is duplicated.
    Modifies ``lib`` in place.
    """
    delimiter = library_groups_separator(lib, separator)
    _validate_group(new, delimiter, lib, separator)
    changed: list[str] = []
    for entry in lib.entries.values():
        value = entry.fields.get("groups")
        if not value:
            continue
        renamed = _renamed_value(value, old, new, delimiter)
        if renamed is None or renamed == value:
            continue
        set_entry_field(entry, "groups", renamed)
        if entry.key not in changed:
            changed.append(entry.key)
    return changed
