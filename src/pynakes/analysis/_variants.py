"""Name-variant candidates: distinct names that may be spellings of one person.

The co-author network compares people by their normalized ``Last, First``
name, so ``Smith, J.`` and ``Smith, John`` are two nodes. Whether they are one
person is a curation decision this module does not take. It reports the pairs
that *look* alike, with the reasons and the evidence against, and leaves the
names apart.

Names are compared letter by letter after TeX accents and diacritics are
removed (``Schr{\\"o}dinger`` and ``Schrödinger`` read alike). A pair is a
candidate for one of these reasons:

``spelling``
    The same letters: they differ only in accents, TeX encoding, case or
    punctuation.
``initials``
    One abbreviates given names the other spells out (``J.`` and ``John``).
``extra_given_names``
    One lists given names the other omits (``John`` and ``John R.``).
``given_missing``
    One carries no given name at all.
``family_split``
    The same names, divided differently between family and given name
    (``Cajal, Santiago Ramón`` and ``Ramón Cajal, Santiago``).
``same_orcid``
    Both are annotated with the same ORCID iD.

Evidence against is listed alongside: ``co_listed`` when both names appear in
one entry's author list (two people, usually), and ``different_orcid`` when
both carry ORCID iDs and they differ.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from pynakes._text_utils import iter_toplevel_splits
from pynakes.authors import ascii_fold, is_fully_braced

_TEX_LETTERS = {
    "ss": "ss",
    "o": "o",
    "O": "O",
    "l": "l",
    "L": "L",
    "ae": "ae",
    "AE": "AE",
    "oe": "oe",
    "OE": "OE",
    "aa": "a",
    "AA": "A",
    "i": "i",
    "j": "j",
}
_TEX_LETTER_RE = re.compile(r"\\(ss|ae|AE|oe|OE|aa|AA|[oOlLij])(?![A-Za-z])\s*")
_TEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+\s*|\\.")
_TOKEN_SPLIT_RE = re.compile(r"[\s\-~]+")


@dataclass(frozen=True)
class _Token:
    letters: str
    abbreviated: bool


@dataclass(frozen=True)
class NameParts:
    """A normalized name split into comparable family and given-name tokens."""

    family: tuple[_Token, ...]
    given: tuple[_Token, ...]

    @property
    def family_letters(self) -> str:
        return "".join(token.letters for token in self.family)

    @property
    def given_letters(self) -> str:
        return "".join(token.letters for token in self.given)

    @property
    def block(self) -> str:
        """The last family token: names that can be variants share it."""
        return self.family[-1].letters if self.family else ""


def plain_letters(text: str) -> str:
    """Return ``text`` with TeX accents and diacritics removed, case-folded."""
    text = _TEX_LETTER_RE.sub(lambda match: _TEX_LETTERS[match.group(1)], text)
    text = _TEX_COMMAND_RE.sub("", text).replace("{", "").replace("}", "")
    return ascii_fold(text).casefold()


def _tokens(text: str) -> tuple[_Token, ...]:
    tokens = []
    for raw in _TOKEN_SPLIT_RE.split(plain_letters(text)):
        letters = re.sub(r"[^a-z0-9]", "", raw)
        if letters:
            tokens.append(_Token(letters, raw.endswith(".") or len(letters) == 1))
    return tuple(tokens)


def name_parts(name: str) -> NameParts | None:
    """Split a normalized ``Last, First`` name; ``None`` for a braced corporate name."""
    if is_fully_braced(name.strip()):
        return None
    parts = iter_toplevel_splits(name, separators=",")
    family = _tokens(parts[0])
    given = _tokens(parts[-1]) if len(parts) > 1 else ()
    if not family:
        return None
    return NameParts(family, given)


def _compatible(left: tuple[_Token, ...], right: tuple[_Token, ...]) -> tuple[bool, bool]:
    """Return whether two token runs agree where both have tokens, and if by abbreviation."""
    abbreviated = False
    for a, b in zip(left, right, strict=False):
        if a.letters == b.letters:
            continue
        if (a.abbreviated and b.letters.startswith(a.letters)) or (
            b.abbreviated and a.letters.startswith(b.letters)
        ):
            abbreviated = True
            continue
        return False, False
    return True, abbreviated


def classify(left: NameParts, right: NameParts) -> list[str]:
    """Return why two names may be one person (empty when they look distinct)."""
    if left.family_letters == right.family_letters:
        if left.given_letters == right.given_letters:
            return ["spelling"]
        if not left.given or not right.given:
            return ["given_missing"]
        ok, abbreviated = _compatible(left.given, right.given)
        if not ok:
            return []
        reasons = ["initials"] if abbreviated else []
        if len(left.given) != len(right.given):
            reasons.append("extra_given_names")
        return reasons or ["spelling"]
    whole_left = left.given + left.family
    whole_right = right.given + right.family
    if left.given and right.given and len(whole_left) == len(whole_right):
        ok, abbreviated = _compatible(whole_left, whole_right)
        if ok:
            return ["family_split", *(["initials"] if abbreviated else [])]
    return []


def variant_candidates(
    names: dict[str, str],
    entry_keys: dict[str, list[str]],
    entry_ids: dict[str, set[int]],
    orcids: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Return the name-variant candidate pairs among ``names`` (key → display name).

    ``entry_keys`` maps each name key to the citation keys of its entries, one
    per entry; ``entry_ids`` to the positions of those entries in the library
    (so duplicate citation keys stay apart); ``orcids`` to the ORCID iDs
    annotated on it. Pairs are
    compared within blocks of the same last family token, plus any two names
    sharing an ORCID iD, so the cost stays near-linear in distinct names.
    """
    parts = {key: name_parts(display) for key, display in names.items()}
    blocks: dict[str, list[str]] = defaultdict(list)
    for key, value in parts.items():
        if value is not None:
            blocks[value.block].append(key)
    found: dict[tuple[str, str], list[str]] = {}
    for members in blocks.values():
        for a, b in combinations(sorted(members), 2):
            left, right = parts[a], parts[b]
            assert left is not None and right is not None
            reasons = classify(left, right)
            if reasons:
                found[(a, b)] = reasons
    by_orcid: dict[str, set[str]] = defaultdict(set)
    for key, ids in orcids.items():
        for orcid in ids:
            by_orcid[orcid].add(key)
    for members in by_orcid.values():
        for pair in combinations(sorted(members), 2):
            found.setdefault(pair, [])
            found[pair].append("same_orcid")

    candidates: list[dict[str, Any]] = []
    for (a, b), reasons in found.items():
        against = []
        if entry_ids[a] & entry_ids[b]:
            against.append("co_listed")
        if orcids.get(a) and orcids.get(b) and not orcids[a] & orcids[b]:
            against.append("different_orcid")
        first, second = sorted((a, b), key=lambda key: (names[key].casefold(), names[key]))
        candidates.append(
            {
                "names": [names[first], names[second]],
                "reasons": reasons,
                "evidence_against": against,
                "entries": [
                    {"name": names[key], "entries": len(entry_keys[key]), "keys": entry_keys[key]}
                    for key in (first, second)
                ],
            }
        )
    candidates.sort(key=lambda item: [name.casefold() for name in item["names"]])
    return candidates
