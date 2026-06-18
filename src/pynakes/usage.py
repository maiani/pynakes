"""Detect which bibliography entries are cited in LaTeX sources.

Reads citation keys from ``.aux`` files (``\\citation{...}``) and ``.tex``
sources (the ``\\cite`` command family, including natbib and biblatex
variants), then reports which library entries are used, unused, or cited but
missing. Can optionally tag used entries (into a JabRef group or a keyword) or
export a subset library containing only the cited entries.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from pynakes.editing import append_delimited_field, splice_into_text
from pynakes.model import BibLibrary, EntryCollection

__all__ = [
    "UsageReport",
    "extract_keys_from_aux",
    "extract_keys_from_tex",
    "collect_cited_keys",
    "analyze_usage",
    "subset_library",
    "tag_with_group",
    "tag_with_keyword",
    "splice_into_text",
]

# ``\citation{key,key2}`` lines emitted by LaTeX into .aux files.
_AUX_CITATION_RE = re.compile(r"\\citation\s*\{([^}]*)\}")

# The \cite family: \cite, \citep, \citet, \citeauthor, \parencite, \textcite,
# \autocite, \footcite, \nocite, \Cite, ... — any command whose name contains
# "cite", with an optional star and any number of optional [...] arguments.
_TEX_CITE_RE = re.compile(
    r"\\[a-zA-Z]*cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}",
    re.IGNORECASE,
)

# Field delimiters by JabRef convention.
_GROUPS_DELIM = ";"
_GROUPS_JOIN = "; "
_KEYWORDS_DELIM = ","
_KEYWORDS_JOIN = ", "


@dataclass
class UsageReport:
    """Result of comparing a library against cited keys."""

    used: list[str]
    unused: list[str]
    missing: list[str]
    cited_count: int
    sources: list[str]
    include_all: bool = False

    def to_dict(self) -> dict:
        return {
            "used": list(self.used),
            "unused": list(self.unused),
            "missing": list(self.missing),
            "cited_count": self.cited_count,
            "sources": list(self.sources),
            "include_all": self.include_all,
        }


# --- citation extraction ---------------------------------------------------


def extract_keys_from_aux(text: str) -> list[str]:
    """Extract citation keys from .aux file content."""
    keys: list[str] = []
    for match in _AUX_CITATION_RE.finditer(text):
        keys.extend(_split_keys(match.group(1)))
    return keys


def extract_keys_from_tex(text: str) -> list[str]:
    """Extract citation keys from .tex source (comments stripped first)."""
    keys: list[str] = []
    for match in _TEX_CITE_RE.finditer(_strip_tex_comments(text)):
        keys.extend(_split_keys(match.group(1)))
    return keys


def _split_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def _strip_tex_comments(text: str) -> str:
    """Remove TeX line comments (unescaped ``%`` to end of line)."""
    cleaned_lines = []
    for line in text.splitlines():
        out = []
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "\\" and i + 1 < len(line):
                out.append(line[i : i + 2])
                i += 2
                continue
            if ch == "%":
                break
            out.append(ch)
            i += 1
        cleaned_lines.append("".join(out))
    return "\n".join(cleaned_lines)


def _iter_source_files(paths: Iterable[str]) -> Iterator[Path]:
    """Yield .tex/.aux files from the given files and/or directories.

    Directories are scanned recursively. Explicitly named files are used as-is
    regardless of extension.

    Raises:
        FileNotFoundError: if a named path does not exist.
    """
    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            yield from sorted(path.rglob("*.tex"))
            yield from sorted(path.rglob("*.aux"))
        elif path.exists():
            yield path
        else:
            raise FileNotFoundError(f"Source not found: {path_str}")


def collect_cited_keys(paths: Iterable[str]) -> tuple[set[str], bool, list[str]]:
    """Collect cited keys from a set of .tex/.aux files and/or directories.

    Returns:
        ``(keys, include_all, scanned)`` where ``include_all`` is True if a
        ``\\nocite{*}`` was seen (meaning every entry counts as used), and
        ``scanned`` is the list of files actually read.
    """
    keys: set[str] = set()
    include_all = False
    scanned: list[str] = []

    for path in _iter_source_files(paths):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".aux":
            found = extract_keys_from_aux(text)
        else:
            found = extract_keys_from_tex(text)
        scanned.append(str(path))
        for key in found:
            if key == "*":
                include_all = True
            else:
                keys.add(key)

    return keys, include_all, scanned


# --- analysis --------------------------------------------------------------


def analyze_usage(
    lib: BibLibrary,
    cited_keys: set[str],
    include_all: bool = False,
    sources: Union[list[str], None] = None,
) -> UsageReport:
    """Compare a library's entries against the set of cited keys."""
    bib_keys = list(dict.fromkeys(lib.entries.keys()))  # unique, order-preserving
    bib_set = set(bib_keys)

    if include_all:
        used = list(bib_keys)
    else:
        used = [k for k in bib_keys if k in cited_keys]

    used_set = set(used)
    unused = [k for k in bib_keys if k not in used_set]
    missing = sorted(k for k in cited_keys if k not in bib_set)

    return UsageReport(
        used=used,
        unused=unused,
        missing=missing,
        cited_count=len(cited_keys),
        sources=sources or [],
        include_all=include_all,
    )


# --- subset export ---------------------------------------------------------


def subset_library(lib: BibLibrary, keys: Iterable[str]) -> BibLibrary:
    """Return a new library containing only entries whose key is in ``keys``.

    Library-level data (strings, preamble, comments, encoding, line ending) is
    preserved so the subset stays a valid, JabRef-compatible file.
    """
    keyset = set(keys)
    subset = EntryCollection()
    for entry in lib.entries.values():
        if entry.key in keyset:
            subset.add(entry)

    return BibLibrary(
        entries=subset,
        strings=dict(lib.strings),
        preamble=list(lib.preamble),
        raw_comments=list(lib.raw_comments),
        jabref_metadata=dict(lib.jabref_metadata),
        jabref_metadata_blocks=list(lib.jabref_metadata_blocks),
        encoding=lib.encoding,
        line_ending=lib.line_ending,
    )


# --- tagging ---------------------------------------------------------------


def tag_with_group(lib: BibLibrary, keys: Iterable[str], group: str) -> int:
    """Add ``group`` to the JabRef ``groups`` field of the given entries.

    Returns the number of entries newly tagged (already-tagged entries are
    skipped). Modifies ``lib`` in place.
    """
    return _tag(lib, keys, "groups", group, _GROUPS_DELIM, _GROUPS_JOIN)


def tag_with_keyword(lib: BibLibrary, keys: Iterable[str], keyword: str) -> int:
    """Add ``keyword`` to the ``keywords`` field of the given entries.

    Returns the number of entries newly tagged. Modifies ``lib`` in place.
    """
    return _tag(lib, keys, "keywords", keyword, _KEYWORDS_DELIM, _KEYWORDS_JOIN)


def _tag(
    lib: BibLibrary,
    keys: Iterable[str],
    field_name: str,
    value: str,
    delim: str,
    join: str,
) -> int:
    keyset = set(keys)
    count = 0
    for entry in lib.entries.values():
        if entry.key in keyset and append_delimited_field(entry, field_name, value, delim, join):
            count += 1
    return count
