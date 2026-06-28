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

from pynakes.editing import append_delimited_field, splice_into_text
from pynakes.model import BibFile

__all__ = [
    "UsageReport",
    "extract_keys_from_aux",
    "extract_keys_from_tex",
    "collect_cited_keys",
    "iter_tex_files",
    "rename_citation_key_in_tex",
    "analyze_usage",
    "subset_library",
    "tag_with_group",
    "tag_with_keyword",
    "tex_sources_from_metadata",
    "splice_into_text",
]

# Linked-source metadata key.
TEX_SOURCES_KEY = "tex-sources"


def tex_sources_from_metadata(lib: BibFile, base_dir: str | Path) -> list[str]:
    """Resolve the ``tex-sources`` metadata list to paths under ``base_dir``.

    The metadata value is a comma/semicolon-separated list of ``.tex`` files or
    directories, stored relative to the library so it stays portable. Relative
    entries are resolved against ``base_dir`` (normally the ``.bib``'s folder);
    absolute entries are used as-is. Returns ``[]`` when the key is unset.
    """
    raw = next(
        (value for key, value in lib.metadata.items() if key.lower() == TEX_SOURCES_KEY),
        None,
    )
    if not raw:
        return []
    base = Path(base_dir)
    resolved: list[str] = []
    for part in re.split(r"[;,]", raw.rstrip(";")):
        candidate = part.strip()
        if not candidate:
            continue
        path = Path(candidate)
        resolved.append(str(path if path.is_absolute() else base / path))
    return resolved


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
        """Serialize the usage report to a JSON-friendly dict for CLI output."""
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


def iter_tex_files(paths: Iterable[str]) -> list[Path]:
    """Return `.tex` files from the given files and/or directories."""
    files: list[Path] = []
    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.tex")))
        elif path.exists():
            if path.suffix.lower() == ".tex":
                files.append(path)
        else:
            raise FileNotFoundError(f"Source not found: {path_str}")
    return files


def rename_citation_key_in_tex(text: str, old: str, new: str) -> tuple[str, int]:
    """Rename a citation key inside TeX citation commands.

    Commented text is left untouched. The rewrite is intentionally narrow:
    it updates comma-delimited keys inside commands matched by the existing
    citation-command recognizer, preserving surrounding whitespace.
    """
    if old == new:
        return text, 0

    parts: list[str] = []
    count = 0
    for line in text.splitlines(keepends=True):
        body, comment = _split_tex_line_comment(line)
        renamed_body, renamed_count = _rename_citation_key_in_segment(body, old, new)
        parts.append(renamed_body + comment)
        count += renamed_count
    return "".join(parts), count


def _split_tex_line_comment(line: str) -> tuple[str, str]:
    i = 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            i += 2
            continue
        if line[i] == "%":
            return line[:i], line[i:]
        i += 1
    return line, ""


def _rename_citation_key_in_segment(segment: str, old: str, new: str) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        raw_keys = match.group(1)
        renamed_keys, renamed_count = _rename_key_list(raw_keys, old, new)
        count += renamed_count
        return (
            match.group(0)[: match.start(1) - match.start(0)]
            + renamed_keys
            + match.group(0)[match.end(1) - match.start(0) :]
        )

    return _TEX_CITE_RE.sub(replace, segment), count


def _rename_key_list(raw: str, old: str, new: str) -> tuple[str, int]:
    pieces = re.split(r"(,)", raw)
    count = 0
    for index, piece in enumerate(pieces):
        if piece == ",":
            continue
        leading = piece[: len(piece) - len(piece.lstrip())]
        trailing = piece[len(piece.rstrip()) :]
        key = piece.strip()
        if key == old:
            pieces[index] = f"{leading}{new}{trailing}"
            count += 1
    return "".join(pieces), count


# --- analysis --------------------------------------------------------------


def analyze_usage(
    lib: BibFile,
    cited_keys: set[str],
    include_all: bool = False,
    sources: list[str] | None = None,
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


def subset_library(lib: BibFile, keys: Iterable[str]) -> BibFile:
    """Return a new library containing only entries whose key is in ``keys``.

    Library-level data (strings, preamble, comments, encoding, line ending) is
    preserved so the subset stays a valid, JabRef-compatible file.
    """
    keyset = set(keys)
    return lib.derive(entry for entry in lib.entries.values() if entry.key in keyset)


# --- tagging ---------------------------------------------------------------


def tag_with_group(lib: BibFile, keys: Iterable[str], group: str) -> int:
    """Add ``group`` to the JabRef ``groups`` field of the given entries.

    Returns the number of entries newly tagged (already-tagged entries are
    skipped). Modifies ``lib`` in place.
    """
    return _tag(lib, keys, "groups", group, _GROUPS_DELIM, _GROUPS_JOIN)


def tag_with_keyword(lib: BibFile, keys: Iterable[str], keyword: str) -> int:
    """Add ``keyword`` to the ``keywords`` field of the given entries.

    Returns the number of entries newly tagged. Modifies ``lib`` in place.
    """
    return _tag(lib, keys, "keywords", keyword, _KEYWORDS_DELIM, _KEYWORDS_JOIN)


def _tag(
    lib: BibFile,
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
