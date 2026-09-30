"""Citation-key rewrites in linked TeX sources, staged until the ``.bib`` commits.

A key rename touches the bibliography and the manuscript together. Writing the
``.tex`` files first and the ``.bib`` second leaves them disagreeing whenever the
second write fails, so a :class:`Bibliography` stages each rewrite here and
applies it only after its own commit succeeded. Before anything is written,
every staged file is checked: unchanged since it was read, writable, and able to
hold the new text in its own encoding.

Sources are read as bytes and written back in the encoding they were decoded
with, without newline translation, so only the rewritten citation keys change.
Sources a library declares in its ``tex-sources`` metadata must lie inside the
project — the enclosing git work tree, or else the ``.bib``'s own directory — so
a library received from someone else cannot direct a rename at arbitrary files.
Sources named on the command line are the caller's own choice and are trusted.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pynakes._atomic import replacement_target
from pynakes.io import _decode_bytes, save_plain_text
from pynakes.usage import rename_citation_keys_in_tex


@dataclass(frozen=True)
class TexRewrite:
    """One source file's planned citation-key rewrite."""

    path: Path
    original: bytes
    encoding: str
    before: str
    after: str
    occurrences: int

    @property
    def modified(self) -> bool:
        return self.before != self.after


class TexSourceChangedError(Exception):
    """A staged source changed on disk after its rewrite was planned."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} changed on disk since it was read")
        self.path = path


def plan_tex_rewrite(path: Path, renames: list[tuple[str, str]]) -> TexRewrite:
    """Read ``path`` and compute its rewrite, without writing anything."""
    data = path.read_bytes()
    text, encoding = _decode_bytes(data)
    after, occurrences = rename_citation_keys_in_tex(text, renames)
    return TexRewrite(path, data, encoding, text, after, occurrences)


def project_root(bib_path: Path) -> Path:
    """Return the enclosing git work tree of ``bib_path``, or else its directory."""
    start = Path(os.path.realpath(bib_path)).parent
    for directory in (start, *start.parents):
        if (directory / ".git").exists():
            return directory
    return start


def require_inside_project(tex_files: Iterable[Path], bib_path: Path) -> None:
    """Refuse metadata-declared sources that resolve outside the project."""
    root = project_root(bib_path)
    outside = [
        str(path) for path in tex_files if not Path(os.path.realpath(path)).is_relative_to(root)
    ]
    if outside:
        raise ValueError(
            "The library's tex-sources metadata points outside the project "
            f"({root}): {', '.join(outside)}. Name these files on the command line "
            "to rewrite them anyway."
        )


def preflight(rewrites: Iterable[TexRewrite]) -> None:
    """Check every modified source can be rewritten before anything is written."""
    problems: list[str] = []
    for rewrite in rewrites:
        if not rewrite.modified:
            continue
        try:
            current = rewrite.path.read_bytes()
        except OSError as exc:
            problems.append(f"{rewrite.path}: {exc}")
            continue
        if current != rewrite.original:
            raise TexSourceChangedError(rewrite.path)
        target = replacement_target(rewrite.path)
        if not os.access(target, os.W_OK) or not os.access(target.parent, os.W_OK):
            problems.append(f"{rewrite.path}: not writable")
            continue
        try:
            rewrite.after.encode(rewrite.encoding)
        except UnicodeEncodeError:
            problems.append(f"{rewrite.path}: the new key cannot be written in {rewrite.encoding}")
    if problems:
        raise OSError("Cannot rewrite TeX sources; nothing was written: " + "; ".join(problems))


def apply(rewrites: Iterable[TexRewrite], *, backup: bool = False) -> list[Path]:
    """Write the modified sources, naming what was done if one write fails."""
    written: list[Path] = []
    for rewrite in rewrites:
        if not rewrite.modified:
            continue
        result = save_plain_text(
            rewrite.after, str(rewrite.path), encoding=rewrite.encoding, backup=backup
        )
        if not result.success:
            done = ", ".join(str(path) for path in written) or "none"
            raise OSError(
                f"The .bib was updated, but {rewrite.path} could not be rewritten "
                f"({result.error}); TeX sources already rewritten: {done}"
            )
        written.append(rewrite.path)
    return written
