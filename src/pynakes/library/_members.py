"""Strict Library manifests and deterministic, diagnostic member expansion."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from pynakes.library._routing import LibraryRouting, parse_routing


@dataclass(frozen=True)
class LibraryIssue:
    """A member or pattern that could not contribute a reliable read.

    ``source`` is an absolute file/directory path or the member pattern.
    Codes are ``unreadable``, ``invalid_member``, ``unmatched_pattern``,
    ``parse_error`` and ``changed``. Issues describe this read, not live state.
    """

    source: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-friendly diagnostic."""
        return {"source": self.source, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class _Manifest:
    path: Path
    name: str | None
    members: tuple[str, ...]
    exclude: tuple[str, ...]
    catalogue: Path | None
    routing: LibraryRouting
    sha256: str


def _strings(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or "\0" in item for item in value
    ):
        raise ValueError(f"Library {key} must be an array of non-empty paths or patterns")
    if any(Path(item).is_absolute() for item in value):
        raise ValueError(f"Library {key} paths must be relative to the manifest")
    return tuple(value)


def _read_manifest(path: str | Path) -> _Manifest:
    path = Path(path).absolute()
    if not path.name.endswith(".library.toml"):
        raise ValueError("Library manifest must be named <name>.library.toml")
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    unknown = data.keys() - {
        "pynakes-library",
        "name",
        "members",
        "exclude",
        "catalogue",
        "routing",
    }
    if unknown:
        raise ValueError(f"Unknown Library manifest keys: {', '.join(sorted(unknown))}")
    if type(data.get("pynakes-library")) is not int or data["pynakes-library"] != 1:
        raise ValueError("Library manifest requires pynakes-library = 1")
    if "members" not in data:
        raise ValueError("Library manifest requires members")
    for key in ("name", "catalogue"):
        if key in data and (
            not isinstance(data[key], str) or not data[key].strip() or "\0" in data[key]
        ):
            raise ValueError(f"Library {key} must be a non-empty string")
    catalogue = data.get("catalogue")
    if catalogue is not None and Path(catalogue).is_absolute():
        raise ValueError("Library catalogue path must be relative to the manifest")
    return _Manifest(
        path=path,
        name=data.get("name"),
        members=_strings(data, "members"),
        exclude=_strings(data, "exclude"),
        catalogue=(path.parent / catalogue).absolute() if catalogue is not None else None,
        routing=parse_routing(data.get("routing", {}), path.parent),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _has_magic(part: str) -> bool:
    return any(char in part for char in "*?[")


def _matches(parts: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    """Match whole paths; ** spans zero or more components."""

    @cache
    def match(i: int, j: int) -> bool:
        if j == len(pattern):
            return i == len(parts)
        if pattern[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], pattern[j]) and match(i + 1, j + 1)

    return match(0, 0)


def _expand(
    base: Path,
    parts: tuple[str, ...],
    issues: list[LibraryIssue],
    excluded: Callable[[Path], bool],
) -> list[Path]:
    """Unlike glob(), preserve errors encountered while traversing directories.

    Recursive ** never follows directory symlinks. Literal path components
    may follow them, as an explicit declaration by the caller.
    """
    if excluded(base):
        return []
    if not parts:
        return [base]
    head, *tail = parts
    if not _has_magic(head):
        return _expand(base / head, tuple(tail), issues, excluded)
    try:
        children = sorted(base.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        issues.append(LibraryIssue(str(base), "unreadable", str(exc)))
        return []
    found = _expand(base, tuple(tail), issues, excluded) if head == "**" else []
    for child in children:
        try:
            if head == "**":
                if stat.S_ISDIR(child.lstat().st_mode):
                    found.extend(_expand(child, parts, issues, excluded))
                elif not tail:
                    found.extend(_expand(child, (), issues, excluded))
            elif fnmatch.fnmatchcase(child.name, head):
                if tail and stat.S_ISLNK(child.lstat().st_mode):
                    continue
                found.extend(_expand(child, tuple(tail), issues, excluded))
        except OSError as exc:
            issues.append(LibraryIssue(str(child), "unreadable", str(exc)))
    return found


def _resolve_files(files: tuple[Path, ...]) -> tuple[tuple[Path, ...], tuple[LibraryIssue, ...]]:
    paths: list[Path] = []
    seen: set[Path] = set()
    issues: list[LibraryIssue] = []
    for candidate in files:
        if "\0" in str(candidate) or candidate.suffix.lower() != ".bib":
            issues.append(
                LibraryIssue(str(candidate), "invalid_member", "Library members must be .bib files")
            )
            continue
        try:
            path = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            issues.append(LibraryIssue(str(candidate), "unreadable", str(exc)))
            continue
        if path not in seen:
            paths.append(path)
            seen.add(path)
    return tuple(paths), tuple(issues)


def _resolve_members(
    members: tuple[str, ...], base: Path, exclude: tuple[str, ...] = ()
) -> tuple[tuple[Path, ...], tuple[LibraryIssue, ...]]:
    paths: list[Path] = []
    issues: list[LibraryIssue] = []
    patterns = [Path(pattern).parts for pattern in exclude]
    excluded_count = 0

    def excluded(path: Path) -> bool:
        nonlocal excluded_count
        relative = Path(os.path.relpath(path, base)).parts
        matches = any(_matches(relative, pattern) for pattern in patterns)
        excluded_count += int(matches)
        return matches

    for member in members:
        member_path = Path(member)
        root = Path(member_path.anchor) if member_path.is_absolute() else base
        parts = member_path.parts[1:] if member_path.is_absolute() else member_path.parts
        before = len(issues)
        excluded_before = excluded_count
        candidates = _expand(root, parts, issues, excluded)
        # An intentionally excluded declaration is not a missing member.
        if not candidates and len(issues) == before and excluded_count == excluded_before:
            issues.append(LibraryIssue(member, "unmatched_pattern", "No members matched"))
        paths.extend(sorted(set(candidates)))
    resolved, resolution_issues = _resolve_files(tuple(paths))
    return resolved, (*issues, *resolution_issues)
