"""BibLaTeX linked-file field parsing and validation."""

from dataclasses import dataclass, field
from pathlib import Path

from pynakes._text_utils import _split_escaped
from pynakes.model import BibEntry, BibFile

FILE_FIELD = "file"
DIRECTORY_KINDS = {"directory", "folder", "dir"}


@dataclass
class LinkedFile:
    """One attachment parsed from a BibLaTeX ``file`` field."""

    entry_key: str
    index: int
    raw: str
    description: str | None
    path: str
    kind: str | None
    resolved_path: Path | None = None
    candidates: list[Path] = field(default_factory=list)
    status: str = "unresolved"

    def to_dict(self) -> dict[str, object]:
        """Serialize the linked file to a JSON-friendly dict."""
        return {
            "entry_key": self.entry_key,
            "field": FILE_FIELD,
            "index": self.index,
            "raw": self.raw,
            "description": self.description,
            "path": self.path,
            "kind": self.kind,
            "resolved_path": str(self.resolved_path) if self.resolved_path else None,
            "candidates": [str(path) for path in self.candidates],
            "status": self.status,
        }


@dataclass
class FileCheckReport:
    """Summary of linked-file validation."""

    checked: int
    ok: int
    missing: int
    wrong_type: int
    unresolved: int
    files: list[LinkedFile]

    @property
    def issues(self) -> list[LinkedFile]:
        """Return linked files that did not validate cleanly."""
        return [item for item in self.files if item.status != "ok"]

    def to_dict(self) -> dict[str, object]:
        """Serialize the report to a JSON-friendly dict."""
        return {
            "checked": self.checked,
            "ok": self.ok,
            "missing": self.missing,
            "wrong_type": self.wrong_type,
            "unresolved": self.unresolved,
            "files": [item.to_dict() for item in self.files],
            "issues": [item.to_dict() for item in self.issues],
        }


def _unescape_descriptor(value: str) -> str:
    """Unescape file descriptor delimiters while leaving other escapes intact."""
    return value.replace("\\;", ";").replace("\\:", ":")


def _looks_like_windows_drive(parts: list[str]) -> bool:
    return len(parts) == 2 and len(parts[0]) == 1 and parts[0].isalpha()


def parse_file_field(entry: BibEntry) -> list[LinkedFile]:
    """Parse the BibLaTeX ``file`` field for one entry."""
    value = entry.fields.get(FILE_FIELD)
    if not value:
        return []

    linked: list[LinkedFile] = []
    for index, item in enumerate(part for part in _split_escaped(value, ";") if part):
        parts = [_unescape_descriptor(part) for part in _split_escaped(item, ":")]
        if len(parts) >= 3:
            description = parts[0] or None
            path = ":".join(parts[1:-1]).strip()
            kind = parts[-1].strip() or None
        elif _looks_like_windows_drive(parts):
            description = None
            path = ":".join(parts).strip()
            kind = None
        elif len(parts) == 2:
            description = parts[0] or None
            path = parts[1].strip()
            kind = None
        else:
            description = None
            path = parts[0].strip()
            kind = None
        linked.append(
            LinkedFile(
                entry_key=entry.key,
                index=index,
                raw=item,
                description=description,
                path=path,
                kind=kind,
            )
        )
    return linked


def parse_linked_files(lib: BibFile) -> list[LinkedFile]:
    """Parse all linked files in a library."""
    linked: list[LinkedFile] = []
    for entry in lib.entries.values():
        linked.extend(parse_file_field(entry))
    return linked


def metadata_file_directories(lib: BibFile, bib_dir: Path) -> list[Path]:
    """Return JabRef ``fileDirectory*`` roots from library metadata."""
    roots: list[Path] = []
    for block in lib.metadata_blocks:
        if not block.key.lower().startswith("filedirectory"):
            continue
        value = block.normalized_value
        if not value:
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = bib_dir / path
        roots.append(path)
    return roots


def _candidate_roots(bib_path: Path, roots: list[Path], metadata_roots: list[Path]) -> list[Path]:
    """Return path roots in resolution priority order."""
    seen: set[str] = set()
    result: list[Path] = []
    for root in [bib_path.parent, *roots, *metadata_roots]:
        path = root.expanduser()
        if not path.is_absolute():
            path = (bib_path.parent / path).resolve()
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _is_directory_link(link: LinkedFile) -> bool:
    return (link.kind or "").strip().lower() in DIRECTORY_KINDS


def _status_for_existing(path: Path, link: LinkedFile) -> str:
    if _is_directory_link(link):
        return "ok" if path.is_dir() else "wrong_type"
    return "wrong_type" if path.is_dir() else "ok"


def resolve_linked_file(link: LinkedFile, bib_path: Path, roots: list[Path], lib: BibFile) -> None:
    """Resolve one linked file in place."""
    if not link.path:
        link.status = "unresolved"
        return

    raw_path = Path(link.path).expanduser()
    if raw_path.is_absolute():
        candidates = [raw_path]
    else:
        metadata_roots = metadata_file_directories(lib, bib_path.parent)
        candidates = [root / raw_path for root in _candidate_roots(bib_path, roots, metadata_roots)]

    link.candidates = candidates
    for candidate in candidates:
        if candidate.exists():
            link.resolved_path = candidate
            link.status = _status_for_existing(candidate, link)
            return
    link.status = "missing"


def check_linked_files(
    lib: BibFile, bib_file: str | Path, roots: list[str | Path] | None = None
) -> FileCheckReport:
    """Validate linked files in ``lib``.

    Resolution order for relative paths is: the bibliography directory, each
    explicit ``root``, and JabRef ``fileDirectory*`` metadata roots.
    """
    bib_path = Path(bib_file).expanduser()
    if not bib_path.is_absolute():
        bib_path = bib_path.resolve()
    extra_roots = []
    for root in roots or []:
        path = Path(root).expanduser()
        extra_roots.append(path if path.is_absolute() else path.resolve())
    linked = parse_linked_files(lib)
    for link in linked:
        resolve_linked_file(link, bib_path, extra_roots, lib)

    counts = {
        "ok": sum(1 for item in linked if item.status == "ok"),
        "missing": sum(1 for item in linked if item.status == "missing"),
        "wrong_type": sum(1 for item in linked if item.status == "wrong_type"),
        "unresolved": sum(1 for item in linked if item.status == "unresolved"),
    }
    return FileCheckReport(
        checked=len(linked),
        ok=counts["ok"],
        missing=counts["missing"],
        wrong_type=counts["wrong_type"],
        unresolved=counts["unresolved"],
        files=linked,
    )
