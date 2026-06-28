"""Citation-key inspection, generation, and duplicate repair.

Generated keys follow the ``AuthorYearTitle`` pattern (e.g. ``Smith2020Big``):
first author's last name, four-digit year, first significant title word.
If a library stores JabRef citation-key pattern metadata, that pattern is used
instead. Generation is deterministic — the same entry always yields the same key.
"""

import re
from collections.abc import Callable

from pynakes._text_utils import strip_jabref_terminator
from pynakes.authors import ascii_fold as _ascii_fold
from pynakes.authors import last_name as _last_name
from pynakes.authors import split_name_list as _split_name_list
from pynakes.editing import rename_entry_key
from pynakes.model import BibEntry, BibFile

# Common title words skipped when picking the "first significant" word.
_TITLE_STOPWORDS = {
    "a",
    "an",
    "the",
    "on",
    "of",
    "for",
    "and",
    "in",
    "to",
    "with",
    "from",
    "by",
    "at",
    "as",
    "is",
    "are",
    "into",
    "over",
    "via",
}

_PATTERN_MARKER_RE = re.compile(r"\[([^\[\]]+)\]")

# Entry types that are structural metadata containers referenced by key from
# other entries (e.g. via ``xdata = {key}``). Renaming them would silently
# break those references, so they are skipped by batch key regeneration.
_STRUCTURAL_ENTRY_TYPES: frozenset[str] = frozenset({"xdata"})


class UnsupportedCitationKeyPatternError(ValueError):
    """Raised when a JabRef citation-key pattern uses unsupported syntax."""


def has_duplicate_keys(lib: BibFile) -> bool:
    """Return ``True`` if any citation key appears more than once."""
    return bool(lib.entries.duplicate_keys())


def duplicate_key_counts(lib: BibFile) -> dict[str, int]:
    """Return ``{key: count}`` for keys that appear more than once."""
    return lib.entries.duplicate_keys()


def _author_last_names(entry: BibEntry) -> list[str]:
    """Return the last names of every author/editor (author preferred)."""
    raw = entry.fields.get("author") or entry.fields.get("editor") or ""
    return [name for name in (_last_name(p) for p in _split_name_list(raw)) if name]


def _first_author_last_name(entry: BibEntry) -> str:
    names = _author_last_names(entry)
    return names[0] if names else "Anon"


def _year(entry: BibEntry) -> str:
    raw = entry.fields.get("year") or entry.fields.get("date") or ""
    match = re.search(r"\d{4}", raw)
    return match.group(0) if match else ""


def _first_title_word(entry: BibEntry) -> str:
    for word in _significant_title_words(entry):
        return _capitalize_word(word)
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


_MARKER_HANDLERS: dict[str, Callable[[BibEntry], str]] = {
    "auth": _first_author_last_name,
    "authors": lambda e: "".join(_author_last_names(e)),
    "year": _year,
    "shortyear": lambda e: _year(e)[-2:],
    "veryshorttitle": lambda e: (
        _capitalize_word(_significant_title_words(e)[0]) if _significant_title_words(e) else ""
    ),
    "shorttitle": lambda e: "".join(_capitalize_word(w) for w in _significant_title_words(e)[:3]),
    "title": lambda e: "".join(_capitalize_word(w) for w in _significant_title_words(e)),
    "camel": lambda e: "".join(_capitalize_word(w) for w in _words(e.fields.get("title", ""))),
    "entrytype": lambda e: _capitalize_word(e.type),
}


def _resolve_marker(entry: BibEntry, marker: str) -> str:
    base, *_modifiers = marker.split(":")
    base = base.strip()
    lower_base = base.lower()

    if base != lower_base and lower_base in entry.fields:
        value = entry.fields[lower_base]
    else:
        handler = _MARKER_HANDLERS.get(lower_base)
        if handler is not None:
            value = handler(entry)
        elif lower_base.startswith("auth") and lower_base[4:].isdigit():
            value = _first_author_last_name(entry)[: int(lower_base[4:])]
        elif lower_base.startswith("camel") and lower_base[5:].isdigit():
            count = int(lower_base[5:])
            value = "".join(
                _capitalize_word(word) for word in _words(entry.fields.get("title", ""))[:count]
            )
        elif lower_base in entry.fields:
            value = entry.fields[lower_base]
        else:
            value = entry.fields.get(base.lower(), "")
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
        elif modifier in ("capitalize", "titlecase"):
            # JabRef treats these citation-key modifiers identically.
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
    return re.sub(r"[^A-Za-z0-9_:+.-]", "", _ascii_fold(value))


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


def get_jabref_key_pattern(lib: BibFile, entry_type: str) -> str | None:
    """Return the JabRef citation-key pattern for ``entry_type`` if stored."""
    type_key = f"keypattern_{entry_type.lower()}"
    for key, value in lib.metadata.items():
        normalized = key.lower()
        if normalized == type_key:
            return strip_jabref_terminator(value)
    for key, value in lib.metadata.items():
        if key.lower() == "keypatterndefault":
            return strip_jabref_terminator(value)
    return None


def generate_fallback_key(entry: BibEntry) -> str:
    """Generate a citation key using pynakes' default ``AuthorYearTitle`` pattern."""
    return f"{_first_author_last_name(entry)}{_year(entry)}{_first_title_word(entry)}"


def generate_key(entry: BibEntry, lib: BibFile | None = None) -> str:
    """Generate a citation key for an entry.

    If ``lib`` stores JabRef citation-key metadata, the matching library pattern
    is used. Otherwise this falls back to ``AuthorYearTitle``.
    """
    if lib is not None:
        pattern = get_jabref_key_pattern(lib, entry.type)
        if pattern:
            return generate_key_from_pattern(entry, pattern)
    return generate_fallback_key(entry)


def unique_key(candidate: str, taken: set[str]) -> str:
    """Return ``candidate`` made unique against ``taken`` with letter suffixes."""
    if candidate not in taken:
        return candidate
    suffix = ord("a")
    while f"{candidate}{chr(suffix)}" in taken:
        suffix += 1
    return f"{candidate}{chr(suffix)}"


def regenerate_keys(lib: BibFile) -> list[tuple[str, str]]:
    """Regenerate every entry's key from its metadata.

    Collisions among generated keys are disambiguated with letter suffixes
    (``Smith2020``, ``Smith2020a``, ...). Returns the list of ``(old, new)``
    renames actually applied. Modifies ``lib`` in place.

    Structural entries whose type is in :data:`_STRUCTURAL_ENTRY_TYPES` (e.g.
    ``@xdata``) are skipped: they are referenced by key from other entries and
    renaming them would silently break those references.
    """
    renames: list[tuple[str, str]] = []
    taken: set[str] = set()
    for entry in lib.entries.values():
        if entry.type.lower() in _STRUCTURAL_ENTRY_TYPES:
            taken.add(entry.key)
            continue
        new_key = unique_key(generate_key(entry, lib), taken)
        taken.add(new_key)
        old_key = entry.key
        if rename_entry_key(entry, new_key):
            renames.append((old_key, new_key))
    return renames


def regenerate_key(lib: BibFile, key: str) -> tuple[str, str] | None:
    """Regenerate one unique citation key from its entry metadata.

    The selected entry's current key is excluded from collision detection, so a
    key that already matches the preferred pattern is a no-op. Other entries
    retain their keys; a collision with one of them receives the usual letter
    suffix. Returns the applied ``(old, new)`` rename, or ``None`` for a no-op.
    """
    validate_key(key)
    matches = lib.entries.get_all(key)
    if not matches:
        raise ValueError(f"No entry with key {key!r} in the library")
    if len(matches) > 1:
        raise ValueError(f"Cannot regenerate duplicated key {key!r}; repair duplicates first")

    entry = matches[0]
    new_key = unique_key(generate_key(entry, lib), set(lib.entries.keys()) - {key})
    if not rename_entry_key(entry, new_key):
        return None
    return key, new_key


def repair_duplicate_keys(lib: BibFile) -> list[tuple[str, str]]:
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


def validate_key(key: str) -> None:
    """Validate a citation key for safe BibTeX/LaTeX rewriting."""
    if not key:
        raise ValueError("citation key must not be empty")
    if re.search(r"[\s,{}\\]", key):
        raise ValueError(f"citation key {key!r} contains whitespace or reserved characters")


def rename_key(lib: BibFile, old: str, new: str) -> int:
    """Rename one unique citation key.

    Returns 1 when the key changed, 0 for a no-op. Raises ``ValueError`` when
    the old key is absent, duplicated, or the new key already exists.
    """
    validate_key(old)
    validate_key(new)
    matches = lib.entries.get_all(old)
    if not matches:
        raise ValueError(f"No entry with key {old!r} in the library")
    if len(matches) > 1:
        raise ValueError(f"Cannot rename duplicated key {old!r}; repair duplicates first")
    if old == new:
        return 0
    if new in lib.entries:
        raise ValueError(f"Cannot rename {old!r} to {new!r}: target key already exists")
    return 1 if rename_entry_key(matches[0], new) else 0
