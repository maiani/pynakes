"""Scaffold a new ``.bib`` library, optionally seeded with a metadata profile.

A new library is just a ``.bib`` file whose only content is its top-level
metadata profile — ``databaseType``, a citation-key pattern, ``saveActions``,
and pynakes normalization/lint settings. This module renders that seed file in
the canonical layout (JabRef-meta comments first, sorted by key, then one
consolidated ``pynakes-meta`` block) and extracts the copyable profile from an
existing library for ``init --from``.

It is deterministic (sorted output, no timestamps) and produces no entries; the
CLI command writes the rendered text through the same atomic, re-parse-validated
path as every other write.
"""

from dataclasses import dataclass

from pynakes.metadata import format_metadata_comment, format_pynakes_meta_block
from pynakes.model import BibFile

# Metadata that is library-specific *content*, not a reusable maintenance
# convention, so ``--from`` never copies it: the source library's own group
# tree, its linked TeX sources, and per-file management bookkeeping.
_PROFILE_SKIP_KEYS = {
    "tex-sources",
    "blgfilepath",
    "protectedflag",
    "versiondbstructure",
    "groupsversion",
    "groups-search-syntax-version",
}
_PROFILE_SKIP_CATEGORIES = {"groups", "selectors"}

# A sensible starting profile for a brand-new library, so `init` produces a
# working library rather than an empty file: the modern BibLaTeX dialect and a
# citation-key pattern equivalent to pynakes' own ``AuthorYearTitle`` fallback,
# so `keys generate` behaves consistently and the convention is visible in the
# file. Both are overridable via `--type` / `--key-pattern`, or replaced wholesale
# by `--from`.
DEFAULT_TYPE = "biblatex"
DEFAULT_KEY_PATTERN = "[auth][year][veryshorttitle]"


@dataclass
class ProfileEntry:
    """One metadata setting destined for a new library.

    ``raw`` carries the source comment verbatim when copied from a template (so
    multi-line values such as ``saveActions`` survive intact); it is ``None`` for
    entries constructed from CLI options, which render canonically.
    """

    key: str
    value: str
    namespace: str  # "jabref" | "pynakes"
    raw: str | None = None


def default_profile() -> list[ProfileEntry]:
    """Return the sensible default metadata profile for a brand-new library."""
    return [
        ProfileEntry("databaseType", DEFAULT_TYPE, "jabref"),
        ProfileEntry("keypatterndefault", DEFAULT_KEY_PATTERN, "jabref"),
    ]


def collect_profile(lib: BibFile) -> list[ProfileEntry]:
    """Extract the copyable maintenance profile from a template library.

    Returns the library's metadata minus its group tree, TeX-source list, and
    per-file management bookkeeping — i.e. the conventions worth carrying to a
    fresh library, not that library's own content.
    """
    entries: list[ProfileEntry] = []
    for block in lib.jabref_metadata_blocks:
        if block.key.lower() in _PROFILE_SKIP_KEYS or block.category in _PROFILE_SKIP_CATEGORIES:
            continue
        entries.append(ProfileEntry(block.key, block.value, "jabref", raw=block.raw))
    for block in lib.pynakes_metadata_blocks:
        if block.key.lower() in _PROFILE_SKIP_KEYS or block.category in _PROFILE_SKIP_CATEGORIES:
            continue
        entries.append(ProfileEntry(block.key, block.value, "pynakes"))
    return entries


def apply_overrides(
    entries: list[ProfileEntry], overrides: list[tuple[str, str, str]]
) -> list[ProfileEntry]:
    """Return ``entries`` with each ``(key, value, namespace)`` override applied.

    An override replaces the existing entry with a matching (case-insensitive)
    key, or is appended when none exists. Overridden entries render canonically
    (``raw`` is dropped).
    """
    result = list(entries)
    for key, value, namespace in overrides:
        replacement = ProfileEntry(key, value, namespace)
        for index, existing in enumerate(result):
            if existing.key.lower() == key.lower():
                result[index] = replacement
                break
        else:
            result.append(replacement)
    return result


def _normalize_line_endings(text: str, line_ending: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized if line_ending == "\n" else normalized.replace("\n", line_ending)


def render_library(entries: list[ProfileEntry], line_ending: str = "\n") -> str:
    """Render a new ``.bib`` containing only ``entries`` as metadata (no entries).

    Produces the canonical layout: each ``jabref-meta`` setting as its own
    comment sorted by key, then a single consolidated ``pynakes-meta`` block.
    Returns ``""`` when there is no profile (a valid empty library).
    """
    jabref = [entry for entry in entries if entry.namespace == "jabref"]
    pynakes = [entry for entry in entries if entry.namespace == "pynakes"]
    if not jabref and not pynakes:
        return ""

    parts: list[str] = []
    for entry in sorted(jabref, key=lambda e: e.key.lower()):
        rendered = (
            _normalize_line_endings(entry.raw, line_ending)
            if entry.raw
            else format_metadata_comment(entry.key, entry.value, "jabref")
        )
        parts.append(rendered)

    if pynakes:
        merged: dict[str, str] = {}
        for entry in pynakes:
            merged[entry.key] = entry.value
        items = sorted(merged.items(), key=lambda kv: kv[0].lower())
        parts.append(format_pynakes_meta_block(items, line_ending))

    return (line_ending + line_ending).join(parts) + line_ending
