"""Infer the citation-key pattern a library's existing keys follow.

A library that never stored a ``key-pattern`` setting still has a style: its
keys were written by hand, by another tool, or by an earlier convention. This
module recognizes that style among a short, fixed list of common patterns, so
a caller can propose it as the library's ``key-pattern`` rather than generate
keys in a different style. It only reports: nothing here stores a setting or
changes a key, and the result depends only on the library's entries.

A key matches a candidate when it equals the key the pattern generates for its
entry, optionally followed by one lowercase letter, the suffix that
disambiguates two works with the same generated key. The best candidate is
inferred only when it matches more than half of the entries checked, and at
least :data:`MIN_ENTRIES` of them, so a small or mixed library yields no
pattern rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pynakes.model import BibFile

#: pynakes' built-in key style (``Newton1687Philosophiae``) as a pattern. A
#: capitalized marker keeps the name's own casing; an all-lowercase marker
#: lowercases it, which is how the Google Scholar style below is written.
DEFAULT_PATTERN = "[Auth][year][Veryshorttitle]"

#: The patterns recognized, in order of preference for ties.
CANDIDATE_PATTERNS: tuple[str, ...] = (
    DEFAULT_PATTERN,
    "[Auth][year][Shorttitle]",
    "[Auth][year][Camel2]",
    "[Auth][year][Camel3]",
    "[Auth][year]",
    "[Auth][shortyear]",
    "[Auth]:[year]",
    "[Auth]_[year]",
    "[auth][year][veryshorttitle]",
    "[auth][year]",
    "[auth]_[year]",
    "[auth]:[year]",
)

#: Fewest entries with key material before a pattern is inferred.
MIN_ENTRIES = 3


@dataclass
class KeyPatternInference:
    """What :func:`infer_key_pattern` found.

    ``pattern`` is the inferred pattern, or ``None`` when no candidate matched
    a clear majority. ``checked`` counts the entries with an author, editor
    or title to build a key from; ``candidates`` lists every candidate with
    the number of those entries whose key it matches, best first.
    """

    pattern: str | None
    matched: int
    checked: int
    candidates: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON shape commands report."""
        return {
            "pattern": self.pattern,
            "matched": self.matched,
            "checked": self.checked,
            "candidates": [
                {"pattern": pattern, "matched": matched} for pattern, matched in self.candidates
            ],
        }


def _matches(key: str, generated: str) -> bool:
    if not generated:
        return False
    if key == generated:
        return True
    return len(key) == len(generated) + 1 and key.startswith(generated) and key[-1].islower()


def infer_key_pattern(lib: BibFile) -> KeyPatternInference:
    """Return the candidate pattern most of ``lib``'s keys follow, if any."""
    # Imported here: keys imports this module to re-export the function.
    from pynakes.keys import _lacks_key_material, generate_key_from_pattern

    entries = [entry for entry in lib.entries.values() if not _lacks_key_material(entry)]
    scores: list[tuple[str, int]] = []
    for pattern in CANDIDATE_PATTERNS:
        matched = sum(
            1 for entry in entries if _matches(entry.key, generate_key_from_pattern(entry, pattern))
        )
        scores.append((pattern, matched))
    # Stable sort: a tie keeps the earlier, more conventional candidate first.
    ranked = sorted(scores, key=lambda score: -score[1])
    best, best_matched = ranked[0] if ranked else (None, 0)
    inferred = best if len(entries) >= MIN_ENTRIES and best_matched * 2 > len(entries) else None
    return KeyPatternInference(
        pattern=inferred,
        matched=best_matched if inferred else 0,
        checked=len(entries),
        candidates=ranked,
    )
