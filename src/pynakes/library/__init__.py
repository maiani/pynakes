"""Discovery and routed additions across explicitly declared bibliography members.

``Library.open()`` loads a versioned manifest; ``Library.from_files()`` loads
explicit files. Both read member files once using the normal BibTeX reader.
Lookup and search use that in-memory view until the caller opens it again.
Additions select one member and stage through Bibliography. There is no index,
background refresh, network access or multi-file mutation.
"""

from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pynakes.bibtex_parser import ParseError
from pynakes.io import _load_source
from pynakes.library._add import LibraryAddition, LibraryRoutingError
from pynakes.library._members import LibraryIssue, _read_manifest, _resolve_files, _resolve_members
from pynakes.library._routing import LibraryRouting, RoutingDecision, RoutingRule
from pynakes.model import BibEntry, BibFile
from pynakes.search import SearchResult, _result_rank, _search_indexed

__all__ = [
    "Library",
    "LibraryHit",
    "LibraryIssue",
    "LibraryRead",
    "LibraryRouting",
    "RoutingRule",
    "RoutingDecision",
    "LibraryRoutingError",
    "LibraryAddition",
]


@dataclass(frozen=True)
class LibraryHit:
    """One occurrence, never an assertion of work identity.

    ``file`` is an absolute resolved path, ``entry_index`` is zero-based in
    that file, and ``start_line`` is one-based. ``source_sha256`` identifies
    the exact bytes read. Indices/lines refer to those bytes, not later edits.
    ``entry`` contains detached fields and the ordinary search explanations.
    Lookup results have no match explanations. Duplicate keys remain distinct.
    """

    file: Path
    entry_index: int
    start_line: int | None
    source_sha256: str
    entry: SearchResult

    def to_dict(self) -> dict[str, object]:
        """Serialize an occurrence and its search result for clients."""
        return {
            "file": str(self.file),
            "entry_index": self.entry_index,
            "start_line": self.start_line,
            "source_sha256": self.source_sha256,
            **self.entry.to_dict(),
        }


@dataclass(frozen=True)
class LibraryRead:
    """Results plus the coverage of the view they were read from.

    ``total`` counts matching entry occurrences before ``limit``; it is not a
    count of distinct works. ``complete`` means no member-resolution/read
    issues, independently of result truncation. It does not assert freshness.
    """

    results: tuple[LibraryHit, ...]
    total: int
    members: tuple[Path, ...]
    loaded_members: tuple[Path, ...]
    issues: tuple[LibraryIssue, ...]

    @property
    def complete(self) -> bool:
        """Whether every declared member/pattern was read without issues."""
        return not self.issues

    @property
    def truncated(self) -> bool:
        """Whether a result limit omitted matching occurrences."""
        return len(self.results) < self.total

    def to_dict(self) -> dict[str, object]:
        """Return results, counts and read diagnostics as JSON-friendly data."""
        return {
            "results": [hit.to_dict() for hit in self.results],
            "total": self.total,
            "complete": self.complete,
            "truncated": self.truncated,
            "members": [str(path) for path in self.members],
            "loaded_members": [str(path) for path in self.loaded_members],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _stamp(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@dataclass(frozen=True)
class _Member:
    path: Path
    bib: BibFile
    sha256: str
    stamp: tuple[int, int, int, int, int]


class Library:
    """A direct-read view of declared bibliographies with per-file provenance.

    Use :meth:`open` or :meth:`from_files` to read members. Invalid manifests
    raise ``ValueError`` (including TOML syntax errors); manifest I/O errors
    propagate. Member failures instead appear in :attr:`issues` and in every
    lookup/search report, allowing useful partial reads without hiding gaps.

    Members are read sequentially. File stat checks during and after loading
    detect common concurrent edits; detected changes exclude that member.
    This is not a globally atomic filesystem snapshot or a watcher. Reopen
    the Library to resolve membership and read current bytes again.
    """

    def __init__(
        self,
        members: tuple[Path, ...],
        *,
        issues: tuple[LibraryIssue, ...] = (),
        manifest: Path | None = None,
        name: str | None = None,
        catalogue: Path | None = None,
        routing: LibraryRouting | None = None,
        manifest_sha256: str | None = None,
    ) -> None:
        self.members = members
        self.manifest = manifest
        self.name = name
        self.routing = routing or LibraryRouting()
        self.routing.validate_members(members)
        self._manifest_sha256 = manifest_sha256
        # Reserved declaration only: no index is opened, created or refreshed.
        self.catalogue = catalogue
        diagnostics = list(issues)
        loaded: list[_Member] = []
        for path in members:
            try:
                if not stat.S_ISREG(path.stat().st_mode):
                    diagnostics.append(
                        LibraryIssue(str(path), "invalid_member", "Member is not a regular file")
                    )
                    continue
                before = _stamp(path)
                bib, _, data = _load_source(path)
                if before != _stamp(path):
                    diagnostics.append(
                        LibraryIssue(str(path), "changed", "Member changed while reading")
                    )
                    continue
                loaded.append(_Member(path, bib, hashlib.sha256(data).hexdigest(), before))
            except ParseError as exc:
                diagnostics.append(LibraryIssue(str(path), "parse_error", str(exc)))
            except (OSError, UnicodeError) as exc:
                diagnostics.append(LibraryIssue(str(path), "unreadable", str(exc)))
        stable: list[_Member] = []
        for member in loaded:
            try:
                if member.stamp == _stamp(member.path):
                    stable.append(member)
                    continue
                message = "Member changed while loading the Library"
            except OSError as exc:
                message = str(exc)
            diagnostics.append(LibraryIssue(str(member.path), "changed", message))
        self._loaded = tuple(stable)
        self.loaded_members = tuple(member.path for member in stable)
        self.issues = tuple(diagnostics)

    @classmethod
    def open(cls, manifest: str | Path) -> Library:
        """Read a ``<name>.library.toml`` and its selected members.

        Version 1 requires ``pynakes-library = 1`` and a ``members`` array.
        Optional keys are ``name``, ``exclude``, ``catalogue`` and ``routing``.
        Routing declares a fallback and named selector rules with integer
        priorities; higher priorities win, equal-priority destinations conflict.
        Paths/patterns are relative to the manifest folder. Patterns use
        case-sensitive ``*``, ``?``, ``[]`` and recursive ``**`` components;
        hidden names are included, recursive directory symlinks are not.
        Exclusions match the entire relative path with the same rules.
        Declaration order is retained, each pattern is sorted, and resolved
        path aliases are read once. Unmatched patterns are reported as issues.
        Nested manifests and other non-``.bib`` members are reported as invalid.
        ``catalogue`` reserves a path; indexing is not implemented.
        """
        spec = _read_manifest(manifest)
        members, issues = _resolve_members(spec.members, spec.path.parent, spec.exclude)
        return cls(
            members,
            issues=issues,
            manifest=spec.path,
            name=spec.name,
            catalogue=spec.catalogue,
            routing=spec.routing,
            manifest_sha256=spec.sha256,
        )

    @property
    def source_sha256(self) -> str:
        """Fingerprint the held manifest and ordered member read results."""
        data = {
            "manifest": self._manifest_sha256,
            "members": [str(path) for path in self.members],
            "loaded": [(str(member.path), member.sha256) for member in self._loaded],
            "issues": [issue.to_dict() for issue in self.issues],
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _assert_current(self) -> None:
        """Refuse stale routing or duplicate-check evidence before a write."""
        from pynakes.engine import ExternalModificationError

        path = self.manifest or next(iter(self.members), Path.cwd())
        try:
            current = (
                Library.open(self.manifest) if self.manifest else Library.from_files(self.members)
            )
            same = self.source_sha256 == current.source_sha256
        except (ValueError, OSError):
            same = False
        if not same:
            raise ExternalModificationError(path)

    def route(
        self,
        entry: BibEntry,
        *,
        destination: str | Path | None = None,
    ) -> RoutingDecision:
        """Preview one home, checking work/key candidates across every member.

        Explicit destinations override rules, but never duplicate or incomplete
        read checks. Relative destinations resolve from the manifest directory
        (cwd for unnamed Libraries). No network or filesystem writes occur.
        """
        from pynakes.library._add import route

        return route(self, entry, destination)

    def stage_entry(
        self,
        entry: BibEntry,
        *,
        destination: str | Path | None = None,
    ) -> LibraryAddition:
        """Stage a uniquely routed new entry in one existing member.

        Returns its decision and Bibliography for preview, diff, reset and
        commit. Raises LibraryRoutingError for existing/uncertain work, routing
        ties, absent fallback or incomplete reads. The commit rechecks every
        member and the manifest; these checks are not a cross-file lock.
        Entry fields are supplied metadata, with file paths interpreted from
        the destination bibliography. This does not ingest or move materials.
        """
        from pynakes.library._add import stage_entry

        return stage_entry(self, entry, destination)

    @classmethod
    def from_files(cls, files: Iterable[str | Path]) -> Library:
        """Read an unnamed Library from explicit paths, relative to the cwd.

        A single string/path is rejected to prevent iterating its characters.
        Patterns belong in a manifest; use a list of literal files here.
        """
        if isinstance(files, (str, Path)):
            raise ValueError("Pass an iterable of file paths, not a single path")
        members, issues = _resolve_files(tuple(Path(path).absolute() for path in files))
        return cls(members, issues=issues)

    def _report(self, hits: list[LibraryHit], limit: int | None) -> LibraryRead:
        if limit is not None and limit < 0:
            raise ValueError("Library read limit must be non-negative")
        return LibraryRead(
            tuple(hits[:limit]), len(hits), self.members, self.loaded_members, self.issues
        )

    @staticmethod
    def _hit(member: _Member, index: int, result: SearchResult) -> LibraryHit:
        return LibraryHit(
            member.path,
            index,
            member.bib.entries.values()[index].start_line,
            member.sha256,
            result,
        )

    def lookup(self, key: str, *, limit: int | None = None) -> LibraryRead:
        """Return every exact, case-sensitive citation-key occurrence.

        Order is member order then entry order. Repeated keys are returned
        without inferring that the entries identify the same work.
        """
        hits = [
            self._hit(member, index, SearchResult(entry.key, entry.type, [], dict(entry.fields)))
            for member in self._loaded
            for index, entry in enumerate(member.bib.entries.values())
            if entry.key == key
        ]
        return self._report(hits, limit)

    def search(
        self,
        query: str,
        *,
        search_in: Iterable[str] | None = None,
        case_sensitive: bool = False,
        fuzzy: bool = False,
        limit: int | None = None,
    ) -> LibraryRead:
        """Search members using the existing field/phrase/AND/OR grammar.

        Match explanations and stored fields follow ``search_entries``.
        Results rank globally by strongest matched field, then score, with
        member/entry order breaking ties. ``limit`` applies across members;
        ``total`` counts every match before limiting (including duplicates).
        This direct scan has no persistent index or bounded-memory promise.
        """
        fields = tuple(search_in) if search_in is not None else None
        # Validate even an empty or wholly unreadable Library.
        _search_indexed(BibFile(), query, search_in=fields, limit=limit)
        hits = [
            self._hit(member, index, result)
            for member in self._loaded
            for index, result in _search_indexed(
                member.bib,
                query,
                search_in=fields,
                case_sensitive=case_sensitive,
                fuzzy=fuzzy,
                rank=False,
            )
        ]
        hits.sort(key=lambda hit: _result_rank(hit.entry))
        return self._report(hits, limit)
