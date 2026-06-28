"""I/O operations for BibTeX files with atomic writes and backups."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

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
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    text, encoding = _decode_bytes(path.read_bytes())

    lib = parse_bib(text)
    lib.encoding = encoding
    return lib


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

    The backup rename happens **after** the new file is safely in place so a
    crash between the temp-write and the final rename never loses data: the
    original is still at its original path until the atomic swap succeeds.
    """
    path = Path(file_path)
    backup_path = None
    original_exists = path.exists()

    try:
        if atomic:
            # Write content to a temporary file in the same directory so the
            # final rename is guaranteed to be on the same filesystem.
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=path.parent,
                delete=False,
                encoding=encoding,
                newline="",
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            if validate:
                try:
                    with open(tmp_path, "r", encoding=encoding) as f:
                        parse_bib(f.read())
                except ParseError as e:
                    Path(tmp_path).unlink(missing_ok=True)
                    return SaveResult(
                        success=False,
                        file_path=file_path,
                        backup_path=None,
                        error=f"Validation failed: {e}",
                    )

            # Rename original to .bak only after the temp file is ready and
            # validated.  A crash between the backup rename and the final
            # replace would leave the original at backup_path; the except
            # block restores it.
            if backup and original_exists:
                backup_path = str(path) + ".bak"
                path.rename(backup_path)

            # Atomic swap: on POSIX this is a single syscall.
            Path(tmp_path).replace(path)
        else:
            # Non-atomic write — backup first if requested.
            if backup and original_exists:
                backup_path = str(path) + ".bak"
                path.rename(backup_path)
            with open(path, "w", encoding=encoding, newline="") as f:
                f.write(content)

        return SaveResult(success=True, file_path=file_path, backup_path=backup_path, error=None)

    except _WRITE_ERRORS as e:
        # Best-effort restore: if the original was moved to .bak but the new
        # file is not yet at path, put the original back.
        if backup_path and not path.exists():
            Path(backup_path).rename(path)
            backup_path = None

        return SaveResult(
            success=False,
            file_path=file_path,
            backup_path=backup_path,
            error=str(e),
        )


def save_plain_text(
    content: str,
    file_path: str,
    encoding: str = "utf-8",
    backup: bool = True,
    atomic: bool = True,
) -> SaveResult:
    """Save arbitrary text — thin alias for ``save_text(..., validate=False)``.

    .. deprecated::
        Call :func:`save_text` directly with ``validate=False`` (the default).
    """
    return save_text(content, file_path, encoding, backup, atomic, validate=False)
