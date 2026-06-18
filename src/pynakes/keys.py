"""Citation-key inspection, generation, and duplicate repair.

Generated keys follow the ``AuthorYearTitle`` pattern (e.g. ``Smith2020Big``):
first author's last name, four-digit year, first significant title word.
Generation is deterministic — the same entry always yields the same key.
"""

import re

from pynakes.editing import rename_entry_key
from pynakes.model import BibEntry, BibLibrary

# Common title words skipped when picking the "first significant" word.
_TITLE_STOPWORDS = {
    "a", "an", "the", "on", "of", "for", "and", "in", "to", "with",
    "from", "by", "at", "as", "is", "are", "into", "over", "via",
}


def has_duplicate_keys(lib: BibLibrary) -> bool:
    """Return ``True`` if any citation key appears more than once."""
    return bool(lib.entries.duplicate_keys())


def duplicate_key_counts(lib: BibLibrary) -> dict[str, int]:
    """Return ``{key: count}`` for keys that appear more than once."""
    return lib.entries.duplicate_keys()


def _first_author_last_name(entry: BibEntry) -> str:
    raw = entry.fields.get("author") or entry.fields.get("editor") or ""
    if not raw.strip():
        return "Anon"
    first = re.split(r"\s+and\s+", raw)[0].strip()
    # A wholly brace-protected author (e.g. ``{World Bank}``) is a single
    # corporate name; take it verbatim rather than splitting off a "last word".
    if first.startswith("{") and first.endswith("}"):
        name = re.sub(r"[^A-Za-z]", "", first[1:-1])
        return name or "Anon"
    first = first.replace("{", "").replace("}", "").strip()
    if "," in first:
        last = first.split(",", 1)[0]
    else:
        parts = first.split()
        last = parts[-1] if parts else ""
    last = re.sub(r"[^A-Za-z]", "", last)
    return last or "Anon"


def _year(entry: BibEntry) -> str:
    raw = entry.fields.get("year") or entry.fields.get("date") or ""
    match = re.search(r"\d{4}", raw)
    return match.group(0) if match else ""


def _first_title_word(entry: BibEntry) -> str:
    raw = entry.fields.get("title", "").replace("{", "").replace("}", "")
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]*", raw):
        if word.lower() not in _TITLE_STOPWORDS:
            return word[0].upper() + word[1:]
    return ""


def generate_key(entry: BibEntry) -> str:
    """Generate a citation key for an entry (``AuthorYearTitle``)."""
    return f"{_first_author_last_name(entry)}{_year(entry)}{_first_title_word(entry)}"


def _unique(candidate: str, taken: set[str]) -> str:
    """Return ``candidate`` made unique against ``taken`` with letter suffixes."""
    if candidate not in taken:
        return candidate
    suffix = ord("a")
    while f"{candidate}{chr(suffix)}" in taken:
        suffix += 1
    return f"{candidate}{chr(suffix)}"


def regenerate_keys(lib: BibLibrary) -> list[tuple[str, str]]:
    """Regenerate every entry's key from its metadata.

    Collisions among generated keys are disambiguated with letter suffixes
    (``Smith2020``, ``Smith2020a``, ...). Returns the list of ``(old, new)``
    renames actually applied. Modifies ``lib`` in place.
    """
    renames: list[tuple[str, str]] = []
    taken: set[str] = set()
    for entry in lib.entries.values():
        new_key = _unique(generate_key(entry), taken)
        taken.add(new_key)
        old_key = entry.key
        if rename_entry_key(entry, new_key):
            renames.append((old_key, new_key))
    return renames


def repair_duplicate_keys(lib: BibLibrary) -> list[tuple[str, str]]:
    """Rename duplicate keys so every key is unique.

    The first entry with a given key keeps it; later duplicates gain a numeric
    suffix (``Smith2020``, ``Smith2020_2``, ...), chosen so as not to collide
    with any existing key. Returns the list of ``(old, new)`` renames applied.
    Modifies ``lib`` in place.
    """
    renames: list[tuple[str, str]] = []
    taken = set(lib.entries.keys())
    seen: set[str] = set()
    for entry in lib.entries.values():
        if entry.key not in seen:
            seen.add(entry.key)
            continue
        base = entry.key
        n = 2
        while f"{base}_{n}" in taken:
            n += 1
        new_key = f"{base}_{n}"
        rename_entry_key(entry, new_key)
        taken.add(new_key)
        seen.add(new_key)
        renames.append((base, new_key))
    return renames
