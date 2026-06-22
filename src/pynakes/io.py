"""I/O operations for BibTeX files with atomic writes and backups."""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.model import BibFile


@dataclass
class SaveResult:
    """Structured outcome of a file write, including backup/error context.

    I/O functions return this value for expected write failures so CLI and
    engine layers can present a controlled error rather than a traceback.
    """

    success: bool
    file_path: str
    backup_path: Optional[str] = None
    error: Optional[str] = None


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
    return save_text(write_bib(lib), file_path, encoding=lib.encoding, backup=backup, atomic=atomic)


def save_text(
    content: str,
    file_path: str,
    encoding: str = "utf-8",
    backup: bool = True,
    atomic: bool = True,
) -> SaveResult:
    """Save already-serialized BibTeX text to a file.

    Used when content is produced outside the writer (e.g. surgical in-place
    edits that splice changed entries into the original text for a minimal
    diff). Shares the same atomic-write, backup, and re-parse-validation
    guarantees as :func:`save_bib`.
    """
    path = Path(file_path)
    backup_path = None

    try:
        # Create backup if file exists and backup=True
        if backup and path.exists():
            backup_path = str(path) + ".bak"
            path.rename(backup_path)

        # Atomic write: write to temp file, then rename
        if atomic:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=path.parent,
                delete=False,
                encoding=encoding,
                newline="",
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            # Validate temp file before committing
            try:
                with open(tmp_path, "r", encoding=encoding) as f:
                    parse_bib(f.read())
            except Exception as e:
                # Restore backup if validation fails
                if backup_path:
                    Path(backup_path).rename(path)
                Path(tmp_path).unlink()
                return SaveResult(
                    success=False,
                    file_path=file_path,
                    backup_path=backup_path,
                    error=f"Validation failed: {str(e)}",
                )

            # Atomic rename
            Path(tmp_path).replace(path)
        else:
            # Non-atomic write
            with open(path, "w", encoding=encoding, newline="") as f:
                f.write(content)

        return SaveResult(success=True, file_path=file_path, backup_path=backup_path, error=None)

    except Exception as e:
        # Restore backup on error
        if backup_path and not path.exists():
            Path(backup_path).rename(path)

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
    """Save arbitrary text with the same backup/atomic mechanics as BibTeX I/O."""
    path = Path(file_path)
    backup_path = None

    try:
        if backup and path.exists():
            backup_path = str(path) + ".bak"
            path.rename(backup_path)

        if atomic:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=path.parent,
                delete=False,
                encoding=encoding,
                newline="",
            ) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            Path(tmp_path).replace(path)
        else:
            with open(path, "w", encoding=encoding, newline="") as f:
                f.write(content)

        return SaveResult(success=True, file_path=file_path, backup_path=backup_path, error=None)

    except Exception as e:
        if backup_path and not path.exists():
            Path(backup_path).rename(path)
        return SaveResult(
            success=False,
            file_path=file_path,
            backup_path=backup_path,
            error=str(e),
        )
