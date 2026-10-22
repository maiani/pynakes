"""Scaffold a new ``.bib`` library, optionally seeded with a metadata profile.

A new library is just a ``.bib`` file whose only content is its top-level
metadata profile. A fresh library is pynakes-native — the default profile seeds
the native ``dialect`` and ``key-pattern`` keys in ``pynakes-meta`` and no
``jabref-meta`` (the CLI's ``--jabref`` flag projects the JabRef equivalents on
top). This module renders that seed file in the canonical layout (any
one consolidated ``pynakes-meta`` block first, then sorted ``jabref-meta``
comments) and extracts the copyable profile from an existing
library for ``init --profile-from``.  The native ``group-tree`` metadata key is
copied as a reusable convention (unlike the legacy JabRef group metadata
keys, which are library-specific content).

It is deterministic (sorted output, no timestamps) and produces no entries; the
CLI command writes the rendered text through the same atomic, re-parse-validated
path as every other write.

The module also renders the optional ``AGENTS.md`` guide (``init --agent-guide``)
that tells LLM agents how to work with a Pinax bibliography.
"""

from dataclasses import dataclass

from pynakes.metadata import (
    format_metadata_comment,
    format_pynakes_meta_block,
    native_key_for_jabref,
)
from pynakes.model import BibFile

# Metadata that is library-specific *content*, not a reusable maintenance
# convention, so ``--profile-from`` never copies it: the source library's own linked
# TeX sources, per-file management bookkeeping, and legacy JabRef group
# metadata.  The native ``group-tree`` key *is* copied (it represents a
# convention, not content), so a new library inherits the template's group
# hierarchy.
_PROFILE_SKIP_KEYS = {
    "tex-sources",
    "blgfilepath",
    "protectedflag",
    "versiondbstructure",
    "grouping",
    "groupstree",
    "groups",
    "groupsversion",
    "groups-search-syntax-version",
}
_PROFILE_SKIP_CATEGORIES = {"selectors"}

# A sensible starting profile for a brand-new library, so `init` produces a
# working library rather than an empty file: the modern BibLaTeX dialect and a
# citation-key pattern equivalent to pynakes' own ``AuthorYearTitle`` fallback,
# so `keys generate` behaves consistently and the convention is visible in the
# file. Both are overridable via `--dialect` / `--key-pattern`, or replaced wholesale
# by `--profile-from`.
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

    Returns the library's metadata minus its legacy JabRef group metadata,
    TeX-source list, and per-file management bookkeeping — i.e. the conventions
    worth carrying to a fresh library, not that library's own content.  The
    native ``group-tree`` key *is* copied as a convention.
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


def _native_key_form(key: str) -> str:
    """Return the canonical native form of ``key``, aliasing JabRef equivalents."""
    native = native_key_for_jabref(key)
    return native if native is not None else key.lower()


def missing_profile_entries(lib: BibFile, entries: list[ProfileEntry]) -> list[ProfileEntry]:
    """Return the subset of ``entries`` whose concept ``lib`` doesn't already set.

    Used by ``init --profile-from`` on an already-initialized library (``--pinax`` onto
    an existing file) to merge in only the maintenance-profile settings the
    library is missing, rather than clobbering its existing conventions.
    Aliasing-aware: a native ``dialect`` key counts as already set even when
    the template only supplies the JabRef ``databaseType`` equivalent, and
    vice versa.
    """
    existing = {_native_key_form(key) for key in lib.metadata}
    missing: list[ProfileEntry] = []
    for entry in entries:
        native = _native_key_form(entry.key)
        if native in existing:
            continue
        missing.append(entry)
        existing.add(native)
    return missing


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

`{bibname}.bib` is managed with pynakes. Its **Pinax**, `{bibname}.files/`,
holds downloaded materials named by citation key:

```
{bibname}.files/
  .pinax/manifest.json    # SHA-256 hashes, fetch dates, sources
  {{Key}}.preprint.pdf
  {{Key}}.published.pdf
  {{Key}}.supplement.pdf
  {{Key}}.source/           # preprint LaTeX source and figures
```

## Rules

1. **Change the library only through pynakes.** Add a reference with
   `pynakes ref import {bibname}.bib <identifier>` (DOI, arXiv id, `PMID:...`,
   or a supported URL). Without an identifier, use
   `pynakes ref add {bibname}.bib <citekey> --field name=value`. Remove one with
   `pynakes ref remove {bibname}.bib <citekey>`, which also removes its
   materials. Preview any change with `--dry-run --diff`.

2. **Fetch materials with `pynakes asset fetch {bibname}.bib`**, never by
   hand, so the manifest stays accurate. The `pinax-fetch-policy` setting
   decides what is fetched; the default, `bestpdf`, fetches PDFs only. Add
   `--material source --key <citekey>` to get an entry's LaTeX source.

3. **Read the source when there is one.** `{{Key}}.source/` keeps equations,
   citations and structure that PDF extraction loses.

4. **Check before and after changes.**
   `pynakes lint --strict --severity warning {bibname}.bib` fails only on
   errors and warnings. Info findings are suggestions: do not edit entries
   just to silence them. `pynakes asset check --strict {bibname}.bib --root .`
   verifies the materials; report checksum drift to the user rather than
   fixing it.

5. **Inspect instead of scanning.** `pynakes inspect --json {bibname}.bib`
   lists every entry and which of its materials exist.
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
