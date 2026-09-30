"""I/O operations for BibTeX files with atomic writes and backups."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile, copymode

from pynakes._atomic import match_mode, replacement_target
from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.model import BibFile

_WRITE_ERRORS = (OSError, UnicodeError)


@dataclass
class SaveResult:
    """Structured outcome of a file write, including backup/error context.

    I/O functions return this value for expected write failures so CLI and
    engine layers can present a controlled error rather than a traceback.
    """

    success: bool
    file_path: str
    backup_path: str | None = None
    error: str | None = None


def _write_backup(path: Path) -> str:
    """Copy ``path`` to ``<path>.bak`` without moving the original away."""
    backup_path = Path(f"{path}.bak")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        staged_backup = Path(tmp.name)
    try:
        copyfile(path, staged_backup)
        copymode(path, staged_backup)
        staged_backup.replace(backup_path)
    finally:
        staged_backup.unlink(missing_ok=True)
    return str(backup_path)


def _decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode file bytes, returning ``(text, encoding)``.

    Tries UTF-8 first, then falls back to latin-1 (which never fails). Decoding
    from bytes deliberately avoids text-mode universal-newline translation, so
    ``\\r\\n`` line endings survive intact for the parser to detect.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    # latin-1 cannot raise, but keep a defensive default.
    return data.decode("utf-8", errors="replace"), "utf-8"


def load_bib(file_path: str) -> BibFile:
    """Load a BibTeX file.

    Args:
        file_path: Path to .bib file

    Returns:
        Parsed BibFile, with the detected encoding recorded on it.

    Raises:
        FileNotFoundError: If file doesn't exist
        ParseError: If BibTeX is malformed
    """
    return _load_source(file_path)[0]


def _load_source(file_path: str | Path) -> tuple[BibFile, str, bytes]:
    """Load a library with the exact text and bytes it was parsed from.

    One read serves the parse, the pristine text, and the change fingerprint,
    so a save landing in between cannot slip past the concurrency check.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    data = path.read_bytes()
    text, encoding = _decode_bytes(data)

    lib = parse_bib(text)
    lib.encoding = encoding
    return lib, text, data


def save_bib(lib: BibFile, file_path: str, backup: bool = True, atomic: bool = True) -> SaveResult:
    """Save a BibFile to a file.

    Supports atomic writes (write to temp file, then rename) and automatic backups.

    Args:
        lib: BibFile to save
        file_path: Path to write to
        backup: Create .bak file before overwriting
        atomic: Use atomic write (write to temp, then rename)

    Returns:
        SaveResult with status and paths
    """
    return save_text(
        write_bib(lib),
        file_path,
        encoding=lib.encoding,
        backup=backup,
        atomic=atomic,
        validate=True,
    )


def save_text(
    content: str,
    file_path: str,
    encoding: str = "utf-8",
    backup: bool = True,
    atomic: bool = True,
    *,
    validate: bool = False,
) -> SaveResult:
    """Save text to a file with optional backup, atomic write, and BibTeX validation.

    Used both for BibTeX files (``validate=True``, which re-parses the temp file
    before committing) and for arbitrary text such as ``.tex`` sources
    (``validate=False``, the default). Shares the same atomic-write and backup
    mechanics in both cases.

    When backup and atomic writing are both enabled, the backup is staged as a
    copy and published before the destination is atomically replaced. The
    original therefore remains at the destination path until the final replace.
    Temporary files are removed on handled failures. These mechanics reduce
    common interruption hazards; they are not a formal durability guarantee
    against every process, operating-system, or storage failure.
    """
    path = Path(file_path)
    # Replace a symlink's target rather than the link itself.
    target = replacement_target(path)
    backup_path = None
    original_exists = target.exists()
    tmp_path: Path | None = None

    if original_exists and not os.access(target, os.W_OK):
        return SaveResult(
            success=False,
            file_path=file_path,
            backup_path=None,
            error=f"{file_path} is read-only; nothing was written",
        )

    try:
        if atomic:
            # Write content to a temporary file in the same directory so the
            # final rename is guaranteed to be on the same filesystem.
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=target.parent,
                delete=False,
                encoding=encoding,
                newline="",
            ) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(content)

            if validate:
                try:
                    with tmp_path.open("r", encoding=encoding) as f:
                        parse_bib(f.read())
                except ParseError as e:
                    return SaveResult(
                        success=False,
                        file_path=file_path,
                        backup_path=None,
                        error=f"Validation failed: {e}",
                    )

            # Publish a copied backup without moving the destination away.
            if backup and original_exists:
                backup_path = _write_backup(path)

            # Atomic swap: on POSIX this is a single syscall. The replacement
            # keeps the destination's permissions, not the temp file's 0600.
            match_mode(tmp_path, target)
            tmp_path.replace(target)
            tmp_path = None
        else:
            # Non-atomic write — preserve a copied backup first if requested.
            if backup and original_exists:
                backup_path = _write_backup(path)
            with open(path, "w", encoding=encoding, newline="") as f:
                f.write(content)

        return SaveResult(success=True, file_path=file_path, backup_path=backup_path, error=None)

    except _WRITE_ERRORS as e:
        return SaveResult(
            success=False,
            file_path=file_path,
            backup_path=backup_path,
            error=str(e),
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def save_plain_text(
    content: str,
    file_path: str,
    encoding: str = "utf-8",
    backup: bool = True,
    atomic: bool = True,
) -> SaveResult:
    """Save arbitrary text — thin alias for ``save_text(..., validate=False)``."""
    return save_text(content, file_path, encoding, backup, atomic, validate=False)
