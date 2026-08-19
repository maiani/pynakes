"""Author/editor name-list parsing and normalization.

This module owns the single implementation of splitting an author/editor field
into individual people and extracting a person's last name; other modules
(e.g. key generation) build on these rather than re-deriving the logic.
"""

import re
import unicodedata

from pynakes._text_utils import iter_toplevel_splits
from pynakes.editing import set_entry_field
from pynakes.model import BibFile

NAME_FIELDS = ("author", "editor")

# Latin letters that NFKD does not decompose into an ASCII base plus combining
# marks. JabRef transliterates these (rather than dropping them) when reducing
# a name to ASCII for citation keys and comparisons.
_ASCII_FOLD_SPECIALS = {
    "ø": "o",
    "Ø": "O",
    "đ": "d",
    "Đ": "D",
    "ð": "d",
    "Ð": "D",
    "ł": "l",
    "Ł": "L",
    "þ": "th",
    "Þ": "Th",
    "ß": "ss",
    "æ": "ae",
    "Æ": "Ae",
    "œ": "oe",
    "Œ": "Oe",
    "ı": "i",
    "İ": "I",
}


def ascii_fold(value: str) -> str:
    """Transliterate accented Latin characters to ASCII, JabRef-style.

    Citation keys are ASCII, so ``Šmith`` must fold to ``Smith`` rather
    than have its accented letter dropped. NFKD splits most accented characters
    into an ASCII base plus combining marks (which are removed); the few Latin
    letters that do not decompose are mapped explicitly.
    """
    folded: list[str] = []
    for char in value:
        if char in _ASCII_FOLD_SPECIALS:
            folded.append(_ASCII_FOLD_SPECIALS[char])
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        folded.append("".join(c for c in decomposed if not unicodedata.combining(c)))
    return "".join(folded)


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


def _drop_von_particle(segment: str) -> str:
    """Drop a leading BibTeX "von" particle from a ``von Last`` name segment.

    BibTeX/biblatex name parsing treats a run of lowercase-starting words
    before the true (capitalized) surname as the "von" part — e.g. ``van
    den`` in ``van den Berg`` or ``de la`` in ``de la Cruz`` — so the real
    last name is the capitalized remainder alone. If no word is capitalized
    (an all-lowercase mononym), the segment is returned unchanged rather than
    discarded.
    """
    words = segment.split()
    for index, word in enumerate(words):
        if word[:1].isupper():
            return " ".join(words[index:])
    return segment


def last_name(person: str) -> str:
    """Extract a person's last name, stripped to letters only.

    Handles ``{Corporate Name}`` (taken whole), ``von Last, First`` (the part
    before the comma, minus a leading lowercase "von" particle like ``van
    den``), and ``First von Last`` (the final token). Accented Latin
    characters are folded to ASCII (``Šmith`` → ``Smith``) rather than
    dropped. Returns ``""`` if empty.
    """
    person = ascii_fold(person.strip())
    if person.startswith("{") and person.endswith("}"):
        return re.sub(r"[^A-Za-z]", "", person[1:-1])
    if "," in person:
        von_last = _drop_von_particle(person.split(",", 1)[0])
        return re.sub(r"[^A-Za-z]", "", von_last)
    parts = person.replace("{", "").replace("}", "").split()
    return re.sub(r"[^A-Za-z]", "", parts[-1] if parts else "")


def _split_top_level(value: str, sep: str) -> list[str]:
    return iter_toplevel_splits(value, separators=sep)


def is_fully_braced(value: str) -> bool:
    """Return whether *value* is enclosed by one balanced outer brace pair."""
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


def _normalize_jabref_name(name: str) -> str:
    collapsed = _normalize_name(name)
    if collapsed == "others" or is_fully_braced(collapsed):
        return collapsed

    comma_parts = _split_top_level(collapsed, ",")
    if len(comma_parts) > 1:
        return ", ".join(_normalize_initials(part) for part in comma_parts if part)

    tokens = collapsed.split()
    if len(tokens) < 2:
        return collapsed

    # JabRef expands compact initials in both ``First Last`` and ``Last FI``
    # forms. The latter is identifiable because its final token is all caps.
    if _is_initials(tokens[-1]) and not _is_initials(tokens[0]):
        return f"{tokens[0]}, {_normalize_initials(tokens[-1])}"

    last_start = len(tokens) - 1
    while last_start > 0:
        stripped = tokens[last_start - 1].strip("{}")
        if not (stripped and stripped[0].islower()):
            break
        last_start -= 1

    first_names = " ".join(_normalize_initials(token) for token in tokens[:last_start])
    last_names = " ".join(tokens[last_start:])
    if not first_names or not last_names:
        return collapsed
    return f"{last_names}, {first_names}"


def _is_initials(token: str) -> bool:
    bare = token.replace(".", "")
    return bool(bare) and bare.isalpha() and bare.upper() == bare and len(bare) <= 3


def _normalize_initials(token: str) -> str:
    if not _is_initials(token):
        return token
    return " ".join(f"{letter}." for letter in token.replace(".", ""))


def _split_comma_name_list(value: str) -> list[str] | None:
    """Recognize JabRef's legacy comma-separated multi-person syntax.

    Plain ``Last, First`` remains a single person. A sequence of full
    whitespace-separated names is a person list, while the conventional
    ``Last, jr, First, Last, First`` form has an explicit suffix marker.
    """
    parts = _split_top_level(value, ",")
    if len(parts) < 3:
        return None
    if all(len(part.split()) >= 2 for part in parts):
        return parts
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}
    if len(parts) >= 5 and parts[1].lower() in suffixes:
        return [
            ", ".join(parts[:3]),
            *[", ".join(parts[i : i + 2]) for i in range(3, len(parts), 2)],
        ]
    return None


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
    names = _split_names(value)
    if len(names) == 1 and normalized_style == "jabref":
        names = _split_comma_name_list(names[0]) or names
    return " and ".join(normalizer(name) for name in names)


def normalize_authors(lib: BibFile, style: str = "jabref") -> int:
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
