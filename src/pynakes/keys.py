"""Citation-key inspection, generation, and duplicate repair.

Generated keys follow the ``AuthorYearTitle`` pattern (e.g. ``Smith2020Big``):
first author's last name, four-digit year, first significant title word.
If a library stores JabRef citation-key pattern metadata, that pattern is used
instead. Generation is deterministic — the same entry always yields the same key.
"""

import re

from pynakes.editing import rename_entry_key
from pynakes.model import BibEntry, BibLibrary

# Common title words skipped when picking the "first significant" word.
_TITLE_STOPWORDS = {
    "a", "an", "the", "on", "of", "for", "and", "in", "to", "with",
    "from", "by", "at", "as", "is", "are", "into", "over", "via",
}

_PATTERN_MARKER_RE = re.compile(r"\[([^\[\]]+)\]")


class UnsupportedCitationKeyPatternError(ValueError):
    """Raised when a JabRef citation-key pattern uses unsupported syntax."""


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


def _words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", value.replace("{", "").replace("}", ""))


def _capitalize_word(word: str) -> str:
    return word[:1].upper() + word[1:] if word else ""


def _significant_title_words(entry: BibEntry) -> list[str]:
    return [
        word
        for word in _words(entry.fields.get("title", ""))
        if word.lower() not in _TITLE_STOPWORDS
    ]


def _field_value(entry: BibEntry, field: str) -> str:
    return entry.fields.get(field.lower(), "")


def _all_author_last_names(entry: BibEntry) -> list[str]:
    raw = entry.fields.get("author") or entry.fields.get("editor") or ""
    names: list[str] = []
    for person in re.split(r"\s+and\s+", raw):
        person = person.strip()
        if not person:
            continue
        if person.startswith("{") and person.endswith("}"):
            cleaned = re.sub(r"[^A-Za-z]", "", person[1:-1])
        elif "," in person:
            cleaned = re.sub(r"[^A-Za-z]", "", person.split(",", 1)[0])
        else:
            parts = person.replace("{", "").replace("}", "").split()
            cleaned = re.sub(r"[^A-Za-z]", "", parts[-1] if parts else "")
        if cleaned:
            names.append(cleaned)
    return names


def _resolve_marker(entry: BibEntry, marker: str) -> str:
    base, *_modifiers = marker.split(":")
    base = base.strip()
    lower_base = base.lower()

    if base != lower_base and lower_base in entry.fields:
        value = _field_value(entry, base)
    elif lower_base == "auth":
        value = _first_author_last_name(entry)
    elif lower_base.startswith("auth") and lower_base[4:].isdigit():
        value = _first_author_last_name(entry)[: int(lower_base[4:])]
    elif lower_base == "authors":
        value = "".join(_all_author_last_names(entry))
    elif lower_base == "year":
        value = _year(entry)
    elif lower_base == "shortyear":
        value = _year(entry)[-2:]
    elif lower_base == "veryshorttitle":
        words = _significant_title_words(entry)
        value = _capitalize_word(words[0]) if words else ""
    elif lower_base == "shorttitle":
        value = "".join(_capitalize_word(word) for word in _significant_title_words(entry)[:3])
    elif lower_base == "title":
        value = "".join(_capitalize_word(word) for word in _significant_title_words(entry))
    elif lower_base == "camel":
        value = "".join(_capitalize_word(word) for word in _words(entry.fields.get("title", "")))
    elif lower_base.startswith("camel") and lower_base[5:].isdigit():
        value = "".join(
            _capitalize_word(word)
            for word in _words(entry.fields.get("title", ""))[: int(lower_base[5:])]
        )
    elif lower_base == "entrytype":
        value = _capitalize_word(entry.type)
    else:
        value = _field_value(entry, base)
        if not value and base not in entry.fields and lower_base not in entry.fields:
            raise UnsupportedCitationKeyPatternError(
                f"Unsupported JabRef citation-key marker [{base}]"
            )

    return _apply_modifiers(value, _modifiers)


def _apply_modifiers(value: str, modifiers: list[str]) -> str:
    for modifier in modifiers:
        modifier = modifier.strip()
        if modifier == "lower":
            value = value.lower()
        elif modifier == "upper":
            value = value.upper()
        elif modifier == "capitalize":
            value = "".join(_capitalize_word(word.lower()) for word in _words(value))
        elif modifier == "titlecase":
            value = "".join(_capitalize_word(word.lower()) for word in _words(value))
        elif modifier == "abbr":
            value = "".join(word[:1] for word in _words(value))
        elif modifier.startswith("truncate") and modifier[len("truncate") :].isdigit():
            value = value[: int(modifier[len("truncate") :])]
        elif modifier:
            raise UnsupportedCitationKeyPatternError(
                f"Unsupported JabRef citation-key modifier :{modifier}"
            )
    return value


def _sanitize_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_:+.-]", "", value)


def generate_key_from_pattern(entry: BibEntry, pattern: str) -> str:
    """Generate a citation key from a supported JabRef citation-key pattern."""
    output = []
    last = 0
    for match in _PATTERN_MARKER_RE.finditer(pattern):
        output.append(pattern[last : match.start()])
        output.append(_resolve_marker(entry, match.group(1)))
        last = match.end()
    output.append(pattern[last:])
    return _sanitize_key("".join(output)) or generate_fallback_key(entry)


def _strip_jabref_value(value: str) -> str:
    return value.strip().rstrip(";").strip()


def get_jabref_key_pattern(lib: BibLibrary, entry_type: str) -> str | None:
    """Return the JabRef citation-key pattern for ``entry_type`` if stored."""
    type_key = f"keypattern_{entry_type.lower()}"
    for key, value in lib.jabref_metadata.items():
        normalized = key.lower()
        if normalized == type_key:
            return _strip_jabref_value(value)
    for key, value in lib.jabref_metadata.items():
        if key.lower() == "keypatterndefault":
            return _strip_jabref_value(value)
    return None


def generate_fallback_key(entry: BibEntry) -> str:
    """Generate a citation key using pynakes' default ``AuthorYearTitle`` pattern."""
    return f"{_first_author_last_name(entry)}{_year(entry)}{_first_title_word(entry)}"


def generate_key(entry: BibEntry, lib: BibLibrary | None = None) -> str:
    """Generate a citation key for an entry.

    If ``lib`` stores JabRef citation-key metadata, the matching library pattern
    is used. Otherwise this falls back to ``AuthorYearTitle``.
    """
    if lib is not None:
        pattern = get_jabref_key_pattern(lib, entry.type)
        if pattern:
            return generate_key_from_pattern(entry, pattern)
    return generate_fallback_key(entry)


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
        new_key = _unique(generate_key(entry, lib), taken)
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
