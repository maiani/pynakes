"""Detect which bibliography entries are cited in LaTeX sources.

Reads citation keys from ``.aux`` files (``\\citation{...}``) and ``.tex``
sources (the ``\\cite`` command family, including natbib and biblatex
variants), then reports which library entries are used, unused, or cited but
missing. Can optionally tag used entries (into a JabRef group or a keyword) or
export a subset library containing only the cited entries.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pynakes._text_utils import _line_number
from pynakes.editing import append_delimited_field, splice_into_text
from pynakes.groups import GROUPS_DELIM as _GROUPS_DELIM
from pynakes.groups import GROUPS_JOIN as _GROUPS_JOIN
from pynakes.metadata import metadata_list_values
from pynakes.model import BibFile

__all__ = [
    "UsageReport",
    "KeyUsageMatch",
    "extract_keys_from_aux",
    "extract_keys_from_tex",
    "collect_cited_keys",
    "collect_citation_occurrences",
    "find_key_usages",
    "iter_tex_files",
    "rename_citation_key_in_tex",
    "rename_citation_keys_in_tex",
    "analyze_usage",
    "subset_library",
    "tag_with_group",
    "tag_with_keyword",
    "tex_sources_from_metadata",
    "validate_tex_sources",
    "resolve_existing_tex_sources",
    "splice_into_text",
]

# Linked-source metadata key.
TEX_SOURCES_KEY = "tex-sources"


class MissingTexSourcesError(FileNotFoundError):
    """Linked TeX sources prevent a citation-key rename.

    Citation keys are ordinarily rewritten in every declared TeX source at the
    same time.  Callers may opt in to proceeding without unavailable sources,
    but the default is to stop before committing a bibliography whose citations
    could no longer match its keys.
    """

    def __init__(self, sources: list[str]) -> None:
        self.sources = sources
        listed = ", ".join(repr(source) for source in sources)
        super().__init__(
            "Cannot rename citation keys because declared TeX source(s) are missing: "
            f"{listed}. Restore or remove them, or pass --force to update the bibliography "
            "without rewriting those sources."
        )


def tex_sources_from_metadata(lib: BibFile, base_dir: str | Path) -> list[str]:
    """Resolve the ``tex-sources`` metadata list to paths under ``base_dir``.

    The metadata value is a comma-separated list of ``.tex`` files or
    directories, with semicolon-separated legacy values accepted while reading.
    If both metadata namespaces contain ``tex-sources``, their lists are merged
    rather than allowing the effective metadata view to hide one side. Relative
    entries are resolved against ``base_dir`` (normally the ``.bib``'s folder);
    absolute entries are used as-is. Returns ``[]`` when the key is unset.
    """
    base = Path(base_dir)
    resolved: list[str] = []
    for candidate in metadata_list_values(lib, TEX_SOURCES_KEY):
        path = Path(candidate)
        resolved.append(str(path if path.is_absolute() else base / path))
    return resolved


def validate_tex_sources(sources: list[str]) -> list[dict]:
    """Return warnings for resolved source paths that do not exist on disk.

    Each warning is a dict with ``type``, ``message``, and ``path`` keys,
    suitable for inclusion in the CLI ``warnings`` envelope.
    """
    warnings: list[dict] = []
    for source in sources:
        if not Path(source).exists():
            warnings.append(
                {
                    "type": "missing_tex_source",
                    "message": f"TeX source {source!r} not found",
                    "path": source,
                }
            )
    return warnings


def resolve_existing_tex_sources(sources: list[str]) -> tuple[list[str], list[dict]]:
    """Validate ``sources`` and drop any that don't exist on disk.

    Returns ``(existing_sources, warnings)``; ``existing_sources`` is safe to
    pass on to :func:`iter_tex_files` without it raising on a missing path.
    """
    warnings = validate_tex_sources(sources)
    if warnings:
        sources = [s for s in sources if Path(s).exists()]
    return sources, warnings


# ``\citation{key,key2}`` lines emitted by LaTeX into .aux files.
_AUX_CITATION_RE = re.compile(r"\\citation\s*\{([^}]*)\}")

# The \cite family: \cite, \citep, \citet, \citeauthor, \parencite, \textcite,
# \autocite, \footcite, \nocite, \Cite, ... — any command whose name contains
# "cite", with an optional star and any number of optional [...] arguments.
_TEX_CITE_RE = re.compile(
    r"\\[a-zA-Z]*cite[a-zA-Z]*\*?\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}",
    re.IGNORECASE,
)

# The leading command name of a matched citation macro, for reporting which
# macro cited a key (``cite``, ``citep``, ``textcite``, ...).
_MACRO_NAME_RE = re.compile(r"\\([a-zA-Z]+)")

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
    usages: dict[str, list["KeyUsageMatch"]] = field(default_factory=dict)
    """Every citation occurrence, keyed by the citation key it cites.

    Covers keys in ``missing`` as well as those in ``used``: a key cited by a
    source but absent from the library is exactly the one a caller most needs
    to locate.  Empty when occurrences were not collected.
    """

    def to_dict(self) -> dict:
        """Serialize the usage report to a JSON-friendly dict for CLI output."""
        return {
            "used": list(self.used),
            "unused": list(self.unused),
            "missing": list(self.missing),
            "cited_count": self.cited_count,
            "sources": list(self.sources),
            "include_all": self.include_all,
            "usages": {
                key: [match.to_dict() for match in matches] for key, matches in self.usages.items()
            },
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


def _walk_sources(
    paths: Iterable[str], suffixes: tuple[str, ...], *, any_named_file: bool
) -> Iterator[Path]:
    """Yield files with ``suffixes`` from the given files and/or directories.

    Directories are scanned recursively, one suffix at a time, each in sorted
    order. A file named explicitly is yielded when ``any_named_file`` is set or
    its suffix is one of ``suffixes``.

    Raises:
        FileNotFoundError: if a named path does not exist.
    """
    for path_str in paths:
        path = Path(path_str)
        if path.is_dir():
            for suffix in suffixes:
                yield from sorted(path.rglob(f"*{suffix}"))
        elif path.exists():
            if any_named_file or path.suffix.lower() in suffixes:
                yield path
        else:
            raise FileNotFoundError(f"Source not found: {path_str}")


def _iter_source_files(paths: Iterable[str]) -> Iterator[Path]:
    """Yield .tex/.aux files; an explicitly named file is used whatever its extension."""
    return _walk_sources(paths, (".tex", ".aux"), any_named_file=True)


@dataclass
class KeyUsageMatch:
    """One ``\\cite``-family macro occurrence citing a specific key."""

    path: str
    line: int
    text: str
    column: int = 1
    """One-based column of the macro's leading backslash on its line."""
    macro: str = ""
    """The citing command's name without its backslash (``cite``, ``citep``, ...)."""

    def to_dict(self) -> dict:
        """Serialize the match to a JSON-friendly dict for CLI output."""
        return {
            "path": self.path,
            "line": self.line,
            "text": self.text,
            "column": self.column,
            "macro": self.macro,
        }


def _iter_text_occurrences(text: str, path: Path) -> Iterator[tuple[str, KeyUsageMatch]]:
    """Yield ``(key, occurrence)`` for every citation in one source file's text.

    The single citation scanner in this module: every caller that needs
    locations goes through it, so the cite-macro pattern, the ``.aux``
    ``\\citation`` pattern, comment stripping, and position arithmetic are
    defined once.  ``.aux`` files are read with the generated-citation pattern;
    anything else is treated as TeX source with its line comments stripped
    first — which preserves the line and column of everything left, since only
    text from an unescaped ``%`` to the end of its line is removed.
    """
    is_aux = path.suffix.lower() == ".aux"
    scanned = text if is_aux else _strip_tex_comments(text)
    pattern = _AUX_CITATION_RE if is_aux else _TEX_CITE_RE
    for match in pattern.finditer(scanned):
        raw = match.group(0)
        name = _MACRO_NAME_RE.match(raw)
        line_start = scanned.rfind("\n", 0, match.start()) + 1
        for key in _split_keys(match.group(1)):
            yield (
                key,
                KeyUsageMatch(
                    path=str(path),
                    line=_line_number(scanned, match.start()),
                    text=raw.strip(),
                    column=match.start() - line_start + 1,
                    macro=name.group(1) if name else "",
                ),
            )


def collect_citation_occurrences(
    paths: Iterable[str],
) -> tuple[dict[str, list[KeyUsageMatch]], bool, list[str]]:
    """Locate every citation in a set of sources, keyed by citation key.

    One pass over each file answers both "which keys are cited" and "where is
    each one cited", so a caller wanting locations for a whole library never
    re-reads a source per key.

    Returns:
        ``(occurrences, include_all, scanned)``.  ``occurrences`` maps each
        cited key to its occurrences in scan order; ``include_all`` is True if
        a ``\\nocite{*}`` was seen (meaning every entry counts as used), and
        ``scanned`` is the list of files actually read.  A ``\\nocite{*}``
        records no occurrence of its own, since ``*`` is not a citation key.
    """
    occurrences: dict[str, list[KeyUsageMatch]] = {}
    include_all = False
    scanned: list[str] = []

    for path in _iter_source_files(paths):
        text = path.read_text(encoding="utf-8", errors="replace")
        scanned.append(str(path))
        for key, occurrence in _iter_text_occurrences(text, path):
            if key == "*":
                include_all = True
            else:
                occurrences.setdefault(key, []).append(occurrence)

    return occurrences, include_all, scanned


def collect_cited_keys(paths: Iterable[str]) -> tuple[set[str], bool, list[str]]:
    """Collect cited keys from a set of .tex/.aux files and/or directories.

    Returns:
        ``(keys, include_all, scanned)`` where ``include_all`` is True if a
        ``\\nocite{*}`` was seen (meaning every entry counts as used), and
        ``scanned`` is the list of files actually read.
    """
    occurrences, include_all, scanned = collect_citation_occurrences(paths)
    return set(occurrences), include_all, scanned


def find_key_usages(key: str, paths: Iterable[str]) -> tuple[list[KeyUsageMatch], list[str]]:
    """Scan ``.tex`` files under ``paths`` for citations of ``key``.

    Unlike :func:`collect_cited_keys`, this needs no ``.bib`` file and never
    consults ``tex-sources`` metadata: it scans exactly the given files or
    directories, so a caller can check one key's blast radius over sources
    ``tex add`` deliberately does not track (frozen snapshots, generated
    diffs) without registering them first.  It also scans ``.tex`` sources
    only, where :func:`collect_citation_occurrences` also reads generated
    ``.aux`` files.

    Returns ``(matches, scanned)``, where ``scanned`` lists every ``.tex`` file
    examined, matched or not.
    """
    matches: list[KeyUsageMatch] = []
    scanned: list[str] = []
    for tex_path in iter_tex_files(paths):
        scanned.append(str(tex_path))
        text = tex_path.read_text(encoding="utf-8", errors="replace")
        matches.extend(
            occurrence
            for cited, occurrence in _iter_text_occurrences(text, tex_path)
            if cited == key
        )
    return matches, scanned


def iter_tex_files(paths: Iterable[str]) -> list[Path]:
    """Return `.tex` files from the given files and/or directories."""
    return list(_walk_sources(paths, (".tex",), any_named_file=False))


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


def rename_citation_keys_in_tex(text: str, renames: Iterable[tuple[str, str]]) -> tuple[str, int]:
    """Rename citation keys inside TeX citation commands using one simultaneous map."""
    mapping = {old: new for old, new in renames if old != new}
    if not mapping:
        return text, 0

    parts: list[str] = []
    count = 0
    for line in text.splitlines(keepends=True):
        body, comment = _split_tex_line_comment(line)
        renamed_body, renamed_count = _rename_citation_keys_in_segment(body, mapping)
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
        renamed_keys, renamed_count = _rename_key_list(raw_keys, {old: new})
        count += renamed_count
        return (
            match.group(0)[: match.start(1) - match.start(0)]
            + renamed_keys
            + match.group(0)[match.end(1) - match.start(0) :]
        )

    return _TEX_CITE_RE.sub(replace, segment), count


def _rename_citation_keys_in_segment(segment: str, mapping: dict[str, str]) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        raw_keys = match.group(1)
        renamed_keys, renamed_count = _rename_key_list(raw_keys, mapping)
        count += renamed_count
        return (
            match.group(0)[: match.start(1) - match.start(0)]
            + renamed_keys
            + match.group(0)[match.end(1) - match.start(0) :]
        )

    return _TEX_CITE_RE.sub(replace, segment), count


def _rename_key_list(raw: str, mapping: dict[str, str]) -> tuple[str, int]:
    pieces = re.split(r"(,)", raw)
    count = 0
    for index, piece in enumerate(pieces):
        if piece == ",":
            continue
        leading = piece[: len(piece) - len(piece.lstrip())]
        trailing = piece[len(piece.rstrip()) :]
        key = piece.strip()
        if key in mapping:
            pieces[index] = f"{leading}{mapping[key]}{trailing}"
            count += 1
    return "".join(pieces), count


# --- analysis --------------------------------------------------------------


def analyze_usage(
    lib: BibFile,
    cited_keys: set[str],
    include_all: bool = False,
    sources: list[str] | None = None,
    usages: dict[str, list[KeyUsageMatch]] | None = None,
) -> UsageReport:
    """Compare a library's entries against the set of cited keys.

    ``usages`` optionally carries the citation occurrences behind
    ``cited_keys`` — from :func:`collect_citation_occurrences` — and is passed
    through to the report unchanged.
    """
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
        usages=usages or {},
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
