"""Author/editor name-list parsing and normalization.

This module owns the single implementation of splitting an author/editor field
into individual people and extracting a person's last name; other modules
(e.g. key generation) build on these rather than re-deriving the logic.
"""

import re

from pynakes.editing import set_entry_field
from pynakes.model import BibLibrary

NAME_FIELDS = ("author", "editor")
AUTHOR_STYLES = {"jabref", "conservative", "bibtex", "biblatex", "none"}
AUTHOR_STYLE_ALIASES = {
    "bibtex": "jabref",
    "biblatex": "jabref",
}


def _is_top_level_and(value: str, i: int) -> bool:
    if value[i : i + 3].lower() != "and":
        return False
    before = value[i - 1] if i > 0 else " "
    after = value[i + 3] if i + 3 < len(value) else " "
    return before.isspace() and after.isspace()


def _split_names(value: str) -> list[str]:
    names: list[str] = []
    current: list[str] = []
    depth = 0
    i = 0

    while i < len(value):
        ch = value[i]
        if ch == "{":
            depth += 1
            current.append(ch)
            i += 1
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            current.append(ch)
            i += 1
            continue
        if depth == 0 and (ch in "&;" or _is_top_level_and(value, i)):
            part = "".join(current).strip()
            if part:
                names.append(part)
            current = []
            i += 3 if _is_top_level_and(value, i) else 1
            continue
        current.append(ch)
        i += 1

    part = "".join(current).strip()
    if part:
        names.append(part)
    return names


def split_name_list(value: str) -> list[str]:
    """Split an author/editor field into individual people (brace-aware).

    Separators are ``and`` (top level), ``&``, and ``;``. Braced groups are
    preserved verbatim so corporate names like ``{World Bank}`` stay intact.
    """
    return _split_names(value)


def last_name(person: str) -> str:
    """Extract a person's last name, stripped to letters only.

    Handles ``{Corporate Name}`` (taken whole), ``Last, First`` (part before
    the comma), and ``First Last`` (final token). Returns ``""`` if empty.
    """
    person = person.strip()
    if person.startswith("{") and person.endswith("}"):
        return re.sub(r"[^A-Za-z]", "", person[1:-1])
    if "," in person:
        return re.sub(r"[^A-Za-z]", "", person.split(",", 1)[0])
    parts = person.replace("{", "").replace("}", "").split()
    return re.sub(r"[^A-Za-z]", "", parts[-1] if parts else "")


def _split_top_level(value: str, sep: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0

    for ch in value:
        if ch == "{":
            depth += 1
            current.append(ch)
            continue
        if ch == "}":
            depth = max(0, depth - 1)
            current.append(ch)
            continue
        if ch == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)

    parts.append("".join(current).strip())
    return parts


def _is_fully_braced(value: str) -> bool:
    if not (value.startswith("{") and value.endswith("}")):
        return False
    depth = 0
    for i, ch in enumerate(value):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and i != len(value) - 1:
                return False
    return depth == 0


def _normalize_style(style: str) -> str:
    lowered = style.lower()
    return AUTHOR_STYLE_ALIASES.get(lowered, lowered)


def _normalize_name(name: str) -> str:
    collapsed = " ".join(name.split())
    normalized = collapsed.lower().replace(".", "").replace(" ", "")
    if normalized in {"etal", "others"}:
        return "others"
    return collapsed


def _normalize_conservative_name(name: str) -> str:
    return _normalize_name(name)


def _is_von_token(token: str) -> bool:
    stripped = token.strip("{}")
    return bool(stripped) and stripped[0].islower()


def _normalize_jabref_name(name: str) -> str:
    collapsed = _normalize_name(name)
    if collapsed == "others" or _is_fully_braced(collapsed):
        return collapsed

    comma_parts = _split_top_level(collapsed, ",")
    if len(comma_parts) > 1:
        return ", ".join(part for part in comma_parts if part)

    tokens = collapsed.split()
    if len(tokens) < 2:
        return collapsed

    last_start = len(tokens) - 1
    while last_start > 0 and _is_von_token(tokens[last_start - 1]):
        last_start -= 1

    first_names = " ".join(tokens[:last_start])
    last_names = " ".join(tokens[last_start:])
    if not first_names or not last_names:
        return collapsed
    return f"{last_names}, {first_names}"


def normalize_name_list(value: str, style: str = "jabref") -> str:
    """Normalize an author/editor name list.

    ``jabref`` follows JabRef's documented "Normalize names of persons" save
    action: separators become ``and`` and personal names are converted to
    comma form, e.g. ``John Smith`` -> ``Smith, John``. Fully braced corporate
    names and already comma-form names are left intact.

    ``conservative`` only standardizes separators, whitespace, and the
    canonical ``others`` marker.
    """
    normalized_style = _normalize_style(style)
    if normalized_style not in {"jabref", "conservative"}:
        raise ValueError(f"Unsupported author style: {style!r}")
    normalizer = (
        _normalize_jabref_name if normalized_style == "jabref" else _normalize_conservative_name
    )
    return " and ".join(normalizer(name) for name in _split_names(value))


def normalize_authors(lib: BibLibrary, style: str = "jabref") -> int:
    """Normalize author/editor fields across a library."""
    normalized_style = _normalize_style(style)
    if normalized_style == "none":
        return 0
    count = 0
    for entry in lib.entries.values():
        for field in NAME_FIELDS:
            if field not in entry.fields:
                continue
            new_value = normalize_name_list(entry.fields[field], normalized_style)
            if set_entry_field(entry, field, new_value):
                count += 1
    return count
