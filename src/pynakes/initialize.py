"""Scaffold a new ``.bib`` library, optionally seeded with a metadata profile.

A new library is just a ``.bib`` file whose only content is its top-level
metadata profile. A fresh library is pynakes-native — the default profile seeds
the native ``dialect`` and ``key-pattern`` keys in ``pynakes-meta`` and no
``jabref-meta`` (the CLI's ``--jabref`` flag projects the JabRef equivalents on
top). This module renders that seed file in the canonical layout (any
one consolidated ``pynakes-meta`` block first, then sorted ``jabref-meta``
comments) and extracts the copyable profile from an existing
library for ``init --from``.

It is deterministic (sorted output, no timestamps) and produces no entries; the
CLI command writes the rendered text through the same atomic, re-parse-validated
path as every other write.

The module also renders the optional ``AGENTS.md`` guide (``init --agent-guide``)
that tells LLM agents how to work with a Pinax bibliography.
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
    """Return the sensible default metadata profile for a brand-new library.

    A fresh library is pynakes-native: the dialect and citation-key pattern are
    written as pynakes' own ``dialect``/``key-pattern`` keys in ``pynakes-meta``,
    so a pynakes-only workflow never gains a ``jabref-meta`` section it did not
    ask for. Pass ``--jabref`` to :func:`pynakes.cli_commands.init.init` (or run
    ``metadata adopt-jabref`` later) to also emit the JabRef projection.
    """
    return [
        ProfileEntry("dialect", DEFAULT_TYPE, "pynakes"),
        ProfileEntry("key-pattern", DEFAULT_KEY_PATTERN, "pynakes"),
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


AGENTS_GUIDE = """\
# Bibliography management (Pinax)

This directory manages a BibTeX library with an associated **Pinax** — a
sidecar directory (`{bibname}.files/`) that stores downloaded materials
(PDFs and LaTeX sources).

## Pinax structure

```
{bibname}.bib               # BibTeX library (pynakes-managed)
{bibname}.files/            # Pinax files-dir (auto-generated)
  .pinax/manifest.json    # Integrity manifest (SHA-256, fetch dates, sources)
  {{Key}}.preprint.pdf      # Preprint PDF for entry {{Key}}
  {{Key}}.source/           # Preprint source bundle (LaTeX + figures)
  {{Key}}.published.pdf     # Published PDF (when available)
```

The `files-dir` path is set in the `pynakes-meta` block inside the `.bib`
file (key: `files-dir`). Fetch behaviour is configured by:
- `fetch-policy`: comma-separated list of ``preprint``, ``published``, ``source``,
  and/or ``bestpdf`` (default: ``bestpdf``, which tries published first then
  falls back to preprint when no open-access copy exists)

## Agent rules

1. **Prefer source over PDF** — when an entry has a Pinax source directory
   (`{{Key}}.source/`), read the `.tex` files there rather than the `.pdf`.
   The source contains semantically meaningful content (equations, citations,
   structured sections) that PDF reading tools cannot reliably extract.

2. **Use `pynakes asset fetch` to download** — never manually download materials.
   `pynakes asset fetch` handles the download and updates the manifest.
   Run it from this directory (it auto-detects the `.bib` file).

3. **Validate before editing** — run `pynakes lint --strict {bibname}.bib`
   and `pynakes asset check {bibname}.bib --root .` before and after changes.

4. **Add new references through pynakes** — use
   `pynakes ref import <identifier> {bibname}.bib` for DOI/arXiv metadata lookup,
   or `pynakes ref add <key> {bibname}.bib --field name=value` for a manual entry,
   rather than writing entries by hand. `ref import` auto-detects DOI
   (`10.1103/PhysRevLett.116.061102`), arXiv ID (`2301.00001`), or a journal
   article URL and ensures consistent formatting and citation-key generation.

5. **Remove entries with `pynakes ref remove`** — use
   `pynakes ref remove {bibname}.bib <citekey>` to delete an entry and its Pinax
   materials.

6. **Inspect before deciding** — `pynakes inspect --json {bibname}.bib` gives a
   machine-readable view of every entry and its local file presence, so you can
   decide what to read or fetch without re-scanning the directory.

7. **Review diffs before committing changes** — all modifying commands support
   `--dry-run --diff`; use them to preview before applying.

8. **Check pinax integrity** — after any fetch or modify operation, verify with
   `pynakes asset check --strict {bibname}.bib --root .`. The manifest tracks
   SHA-256 hashes and fetch dates; report any drift (mismatched checksums) to
   the user rather than silently fixing.
"""


def render_agents_md(bibname: str) -> str:
    """Return the ``AGENTS.md`` guide for a Pinax bibliography.

    ``bibname`` is the stem of the ``.bib`` file (e.g. ``"library"`` for
    ``library.bib``).
    """
    return AGENTS_GUIDE.format(bibname=bibname)


def render_library(entries: list[ProfileEntry], line_ending: str = "\n") -> str:
    """Render a new ``.bib`` containing only ``entries`` as metadata (no entries).

    Produces the canonical layout: a single consolidated ``pynakes-meta`` block,
    then each ``jabref-meta`` setting as its own comment sorted by key.
    Returns ``""`` when there is no profile (a valid empty library).
    """
    jabref = [entry for entry in entries if entry.namespace == "jabref"]
    pynakes = [entry for entry in entries if entry.namespace == "pynakes"]
    if not jabref and not pynakes:
        return ""

    parts: list[str] = []
    if pynakes:
        merged: dict[str, str] = {}
        for entry in pynakes:
            merged[entry.key] = entry.value
        items = sorted(merged.items(), key=lambda kv: kv[0].lower())
        parts.append(format_pynakes_meta_block(items, line_ending))

    for entry in sorted(jabref, key=lambda e: e.key.lower()):
        rendered = (
            _normalize_line_endings(entry.raw, line_ending)
            if entry.raw
            else format_metadata_comment(entry.key, entry.value, "jabref")
        )
        parts.append(rendered)

    return (line_ending + line_ending).join(parts) + line_ending
