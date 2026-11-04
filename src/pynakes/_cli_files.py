"""Shared bibliography argument and file-discovery helpers."""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import typer

BIB_FILE_HELP = "Path to the .bib file (default: auto-detect single .bib in cwd)"


# REVTeX 4.1/4.2 writes its footnotes and style options to ``<jobname>Notes.bib``,
# opening it with ``@CONTROL{REVTEX41Control}`` / ``@CONTROL{REVTEX42Control}``.
_REVTEX_CONTROL_RE = re.compile(rb"@\s*control\s*[{(]\s*revtex4", re.IGNORECASE)
_REVTEX_SNIFF_BYTES = 4096


def is_auxiliary_bib_file(path: Path) -> bool:
    """Return whether *path* is a REVTeX-generated ``<jobname>Notes.bib``.

    Both the name and REVTeX's ``@CONTROL`` entry near the top must match, so a
    library the user named ``notes.bib`` or ``LectureNotes.bib`` is not one.
    """
    if not path.name.endswith("Notes.bib"):
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(_REVTEX_SNIFF_BYTES)
    except OSError:
        return False
    return _REVTEX_CONTROL_RE.search(head) is not None


def bib_file_argument(help: str = BIB_FILE_HELP) -> Any:
    """Return the standard optional ``.bib`` positional argument."""
    return typer.Argument(None, help=help)


def bib_candidates(directory: Path) -> list[Path]:
    """Return regular user-library ``.bib`` files in *directory*, name-sorted."""
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".bib" and not is_auxiliary_bib_file(path)
        ),
        key=lambda path: path.name.casefold(),
    )


def auxiliary_bib_files(directory: Path) -> list[Path]:
    """Return the REVTeX-generated ``.bib`` files auto-detection skips, name-sorted."""
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() == ".bib" and is_auxiliary_bib_file(path)
        ),
        key=lambda path: path.name.casefold(),
    )


def single_bib_file(directory: Path) -> Path | None:
    """Return the only regular ``.bib`` file in *directory*, if there is one."""
    candidates = bib_candidates(directory)
    return candidates[0] if len(candidates) == 1 else None


def missing_bib_message(candidates: list[Path], skipped: Iterable[Path] = ()) -> str:
    """Return the standard omitted-library error message for *candidates*.

    *skipped* names the REVTeX-generated files auto-detection passed over, so
    a directory holding only one is not reported as holding no ``.bib`` at all.
    """
    skipped_names = ", ".join(path.name for path in skipped)
    if not candidates:
        if skipped_names:
            return (
                "No *.bib bibliography found in current directory (skipped REVTeX-generated "
                f"{skipped_names}); specify one as an argument"
            )
        return "No *.bib file found in current directory; specify one as an argument"
    names = "  ".join(path.name for path in candidates)
    return f"Multiple *.bib files found; specify one as an argument:\n{names}"
