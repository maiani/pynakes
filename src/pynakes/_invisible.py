"""Invisible characters in field values: finding them, naming them, and removing them.

Not public API. Provider metadata sometimes carries characters that render as
nothing — a byte-order mark inside a title, a zero-width space, a soft hyphen,
MathML's invisible operators — and that survive into BibTeX, where they break
searching, sorting, and TeX itself. ``lint`` reports each one by code point and
offset (``invisible_character``), ``normalize`` removes them, and imported
records are cleaned on the way in.

Only characters with no legitimate role in a bibliographic field are covered.
The zero-width joiner and non-joiner, which some scripts need, and the
directional marks are left alone; so is every visible character.
"""

from __future__ import annotations

import unicodedata

from pynakes.editing import set_entry_field_expression
from pynakes.model import BibFile

#: Format characters that render as nothing and mean nothing in a field value.
INVISIBLE: frozenset[str] = frozenset(
    {
        "\u00ad",  # soft hyphen
        "\u180e",  # Mongolian vowel separator (formerly a space)
        "\u200b",  # zero width space
        "\u2060",  # word joiner
        "\u2061",  # function application (MathML)
        "\u2062",  # invisible times (MathML)
        "\u2063",  # invisible separator (MathML)
        "\u2064",  # invisible plus (MathML)
        "\ufeff",  # zero width no-break space / byte-order mark
    }
)
_KEPT_CONTROLS = frozenset("\t\n\r")


def is_invisible(char: str) -> bool:
    """Return whether *char* is one :mod:`pynakes._invisible` reports and removes."""
    if char in INVISIBLE:
        return True
    return unicodedata.category(char) == "Cc" and char not in _KEPT_CONTROLS


def find_invisible(text: str) -> list[tuple[int, str]]:
    """Return ``(offset, character)`` for each invisible character in *text*."""
    return [(offset, char) for offset, char in enumerate(text) if is_invisible(char)]


def describe(char: str) -> str:
    """Return ``U+XXXX NAME`` for *char*."""
    name = unicodedata.name(char, "control character")
    return f"U+{ord(char):04X} {name}"


def strip_invisible(text: str) -> str:
    """Return *text* without its invisible characters."""
    if not any(is_invisible(char) for char in text):
        return text
    return "".join(char for char in text if not is_invisible(char))


def remove_invisible(lib: BibFile) -> int:
    """Remove invisible characters from every field value; return the entries changed.

    Edits only the fields that hold one, and keeps each field's delimiters and
    macros: the characters are removed from the stored expression as written.
    """
    changed = 0
    for entry in lib.entries.values():
        touched = False
        for name, value in list(entry.fields.items()):
            cleaned = strip_invisible(value)
            if cleaned == value:
                continue
            expression = entry.field_expressions.get(name)
            new_expression = (
                strip_invisible(expression) if expression is not None else "{" + cleaned + "}"
            )
            set_entry_field_expression(entry, name, new_expression, cleaned)
            touched = True
        changed += touched
    return changed
