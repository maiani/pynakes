"""Citation-key inspection, generation, and duplicate repair.

Generated keys follow the ``AuthorYearTitle`` pattern (e.g. ``Smith2020Big``):
first author's last name, four-digit year, first significant title word.
If a library stores a citation-key pattern (pynakes' native ``key-pattern`` keys,
or JabRef's ``keypattern_*`` as a fallback), that pattern is used instead. The
pattern language (markers in ``[brackets]``, modifiers chained after ``:``) and
its supported vocabulary mirror JabRef's citation-key patterns; markers or
modifiers outside that vocabulary raise
:class:`UnsupportedCitationKeyPatternError` rather than generating a wrong key.
Generation is deterministic — the same entry always yields the same key.
"""

import re
from collections.abc import Callable

from pynakes._text_utils import entry_year
from pynakes.authors import ascii_fold as _ascii_fold
from pynakes.authors import last_name as _last_name
from pynakes.authors import split_name_list as _split_name_list
from pynakes.editing import rename_entry_key
from pynakes.formatters import (
    FIELD_FORMATTERS,
    first_page,
    last_page,
    latex_to_plain_text,
    page_prefix,
)
from pynakes.metadata import library_key_pattern
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


def _last_names_for(entry: BibEntry, field: str, fallback: str | None = None) -> list[str]:
    raw = entry.fields.get(field) or (entry.fields.get(fallback, "") if fallback else "") or ""
    return [name for name in (_last_name(p) for p in _split_name_list(raw)) if name]


def _author_last_names(entry: BibEntry) -> list[str]:
    """Return the last names of every author, falling back to editor when absent."""
    return _last_names_for(entry, "author", fallback="editor")


def _editor_last_names(entry: BibEntry) -> list[str]:
    """Return the last names of every editor. Does not fall back to ``author``."""
    return _last_names_for(entry, "editor")


def _first_author_last_name(entry: BibEntry) -> str:
    names = _author_last_names(entry)
    return names[0] if names else "Anon"


def _last_author_last_name(entry: BibEntry) -> str:
    """Return the last name of the last author/editor."""
    names = _author_last_names(entry)
    return names[-1] if names else "Anon"


def _first_editor_last_name(entry: BibEntry) -> str:
    names = _editor_last_names(entry)
    return names[0] if names else "Anon"


def _last_editor_last_name(entry: BibEntry) -> str:
    names = _editor_last_names(entry)
    return names[-1] if names else "Anon"


def _ini(names: list[str]) -> str:
    """Five leading-name chars plus later initials (JabRef ``authorIni``/``editorIni``)."""
    if not names:
        return "Anon"
    return names[0][:5] + "".join(name[:1] for name in names[1:])


def _ini_n(names: list[str], count: int) -> str:
    """Distribute at most N leading surname chars (JabRef ``authIniN``/``edtrIniN``)."""
    if not names or count <= 0:
        return ""
    width, remainder = divmod(count, len(names))
    return "".join(name[: width + (index < remainder)] for index, name in enumerate(names))


def _names_n(names: list[str], count: int) -> str:
    """Up to N surnames, with ``EtAl`` when truncated (JabRef ``authorsN``/``editorsN``)."""
    return "".join(names[:count]) + ("EtAl" if len(names) > count else "")


def _year(entry: BibEntry) -> str:
    return entry_year(entry)


def _first_title_word(entry: BibEntry) -> str:
    return _veryshorttitle_of(entry.fields.get("title", ""))


def _words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", latex_to_plain_text(value))


def _capitalize_word(word: str) -> str:
    return word[:1].upper() + word[1:] if word else ""


def _significant_words(value: str) -> list[str]:
    return [word for word in _words(value) if word.lower() not in _TITLE_STOPWORDS]


def _veryshorttitle_of(value: str) -> str:
    words = _significant_words(value)
    return _capitalize_word(words[0]) if words else ""


def _shorttitle_of(value: str) -> str:
    return "".join(_capitalize_word(word) for word in _significant_words(value)[:3])


_MARKER_HANDLERS: dict[str, Callable[[BibEntry], str]] = {
    "auth": _first_author_last_name,
    "authors": lambda e: "".join(_author_last_names(e)),
    "authorini": lambda e: _ini(_author_last_names(e)),
    "authorlast": _last_author_last_name,
    "edtr": _first_editor_last_name,
    "editors": lambda e: "".join(_editor_last_names(e)),
    "editorini": lambda e: _ini(_editor_last_names(e)),
    "editorlast": _last_editor_last_name,
    "year": _year,
    "shortyear": lambda e: _year(e)[-2:],
    "veryshorttitle": lambda e: _veryshorttitle_of(e.fields.get("title", "")),
    "shorttitle": lambda e: _shorttitle_of(e.fields.get("title", "")),
    "title": lambda e: "".join(
        _capitalize_word(w) for w in _significant_words(e.fields.get("title", ""))
    ),
    "fulltitle": lambda e: latex_to_plain_text(e.fields.get("title", "")).strip(),
    "camel": lambda e: "".join(_capitalize_word(w) for w in _words(e.fields.get("title", ""))),
    "entrytype": lambda e: _capitalize_word(e.type),
    "firstpage": lambda e: first_page(e.fields.get("pages", "")),
    "lastpage": lambda e: last_page(e.fields.get("pages", "")),
    "pageprefix": lambda e: page_prefix(e.fields.get("pages", "")),
}


def _apply_marker_casing(value: str, base: str) -> str:
    """Case ``value`` to match how the marker itself was written.

    ``[auth]`` forces lowercase and ``[AUTH]`` forces uppercase (both fully
    tested, intentional JabRef-compatible behavior). A mixed-case marker like
    ``[Auth]`` only capitalizes the first character — it must not lowercase
    the rest, or a legitimately mixed-case value (a compound surname like
    ``PioroLadriere``, or a title word that's an acronym like ``AI``) gets
    corrupted into ``Pioroladriere``/``Ai``.
    """
    if not value:
        return value
    if base.isupper():
        return value.upper()
    if base.islower():
        return value.lower()
    if base[0].isupper() and (len(base) < 2 or base[1:].islower()):
        return value[:1].upper() + value[1:]
    return value


def _split_top_level(text: str, sep: str = ":") -> list[str]:
    """Split *text* on *sep* outside parenthesized groups and backslash escapes.

    A ``regex("a:b","c")`` or ``(text:with:colons)`` modifier argument can
    contain a literal separator; this only splits where the pattern language
    itself would, leaving such arguments intact.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _has_default_value_modifier(modifiers: list[str]) -> bool:
    return any(re.fullmatch(r"\(.+\)", modifier.strip()) for modifier in modifiers)


def _resolve_marker(entry: BibEntry, marker: str) -> str:
    base, *_modifiers = _split_top_level(marker)
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
        elif lower_base.startswith("authini") and lower_base[7:].isdigit():
            value = _ini_n(_author_last_names(entry), int(lower_base[7:]))
        elif lower_base.startswith("authors") and lower_base[7:].isdigit():
            value = _names_n(_author_last_names(entry), int(lower_base[7:]))
        elif lower_base.startswith("edtr") and lower_base[4:].isdigit():
            value = _first_editor_last_name(entry)[: int(lower_base[4:])]
        elif lower_base.startswith("edtrini") and lower_base[7:].isdigit():
            value = _ini_n(_editor_last_names(entry), int(lower_base[7:]))
        elif lower_base.startswith("editors") and lower_base[7:].isdigit():
            value = _names_n(_editor_last_names(entry), int(lower_base[7:]))
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
                if not _has_default_value_modifier(_modifiers):
                    raise UnsupportedCitationKeyPatternError(
                        f"Unsupported JabRef citation-key marker [{base}]"
                    )

    value = _apply_marker_casing(value, base)
    return _apply_modifiers(value, _modifiers)


# Key-pattern-only modifier spellings that delegate to a registered formatter
# under a different name (JabRef spells these two ways: a short modifier
# keyword here, and an underscored ``saveActions`` formatter key in
# ``FIELD_FORMATTERS``, both driving the same underlying transform).
_MODIFIER_FORMATTER_ALIASES: dict[str, str] = {
    "lower": "lower_case",
    "upper": "upper_case",
    "capitalize": "capitalize",
    "titlecase": "title_case",
    "sentencecase": "sentence_case",
}

_TRUNCATE_RE = re.compile(r"\Atruncate(\d+)\Z")
_REGEX_MODIFIER_RE = re.compile(r'\A\("(?P<pattern>.*?)"\s*,\s*"(?P<replacement>.*)"\)\Z')


def _abbr_modifier(value: str) -> str:
    """First character of each token, split on parens/space/CR/LF/quote (JabRef ``abbr``)."""
    stripped = re.sub(r"[{}']", "", value)
    return "".join(word[0] for word in re.split(r'[() \r\n"]', stripped) if word)


def _regex_modifier(value: str, modifier: str) -> str | None:
    """Apply a ``regex("pattern","replacement")`` modifier, translating Java's
    ``$1``-style backreferences to Python's ``\\1``.

    A pattern containing a literal ``[``/``]`` (e.g. a character class like
    ``[a-z]``) is not supported here: ``_PATTERN_MARKER_RE`` scans the whole
    pattern for ``[marker]`` spans before modifiers are parsed, so a literal
    bracket inside this argument is misread as a marker boundary.
    """
    match = _REGEX_MODIFIER_RE.match(modifier[len("regex") :])
    if not match:
        return None
    replacement = re.sub(r"\$(\d+)", r"\\\1", match.group("replacement"))
    return re.sub(match.group("pattern"), replacement, value)


def _resolve_modifier(value: str, modifier: str) -> str | None:
    """Resolve one modifier to its output, or ``None`` if not recognized."""
    alias = _MODIFIER_FORMATTER_ALIASES.get(modifier)
    if alias is not None:
        return FIELD_FORMATTERS[alias](value)
    if modifier == "veryshorttitle":
        return _veryshorttitle_of(value)
    if modifier == "shorttitle":
        return _shorttitle_of(value)
    if modifier.startswith("camel"):
        suffix = modifier[len("camel") :]
        if suffix == "":
            return "".join(_capitalize_word(word) for word in _words(value))
        if suffix.isdigit():
            return "".join(_capitalize_word(word) for word in _words(value)[: int(suffix)])
        return None
    if modifier.startswith("regex"):
        return _regex_modifier(value, modifier)
    truncate_match = _TRUNCATE_RE.match(modifier)
    if truncate_match:
        return value[: int(truncate_match.group(1))].rstrip()
    formatter = FIELD_FORMATTERS.get(modifier)
    return formatter(value) if formatter is not None else None


def _apply_modifiers(value: str, modifiers: list[str]) -> str:
    # The ``(x)`` default-value modifier fires on the pre-chain value, not the
    # running one — an earlier modifier turning a value empty (or non-empty)
    # does not affect whether the default applies.
    original = value
    for modifier in modifiers:
        modifier = modifier.strip()
        if not modifier:
            continue
        if modifier == "abbr":
            value = _abbr_modifier(value)
            continue
        resolved = _resolve_modifier(value, modifier)
        if resolved is not None:
            value = resolved
            continue
        if modifier[0] == "(" and modifier[-1] == ")" and len(modifier) > 1:
            # Recognized default-value syntax; JabRef only substitutes when the
            # marker resolved empty and a non-empty default was given, and
            # otherwise leaves the value unchanged rather than erroring.
            if not original and len(modifier) > 2:
                value = modifier[1:-1]
            continue
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


def generate_fallback_key(entry: BibEntry) -> str:
    """Generate a citation key using pynakes' default ``AuthorYearTitle`` pattern."""
    return f"{_first_author_last_name(entry)}{_year(entry)}{_first_title_word(entry)}"


def generate_key(entry: BibEntry, lib: BibFile | None = None) -> str:
    """Generate a citation key for an entry.

    If ``lib`` stores a citation-key pattern (pynakes' native ``key-pattern``
    keys, or JabRef's ``keypattern_*``/``keypatterndefault`` as a fallback), the
    matching library pattern is used. Otherwise this falls back to
    ``AuthorYearTitle``.
    """
    if lib is not None:
        pattern = library_key_pattern(lib, entry.type)
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
