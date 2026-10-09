"""I/O operations for BibTeX files with atomic writes and backups."""

import codecs
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile, copymode

from pynakes._atomic import match_mode, next_backup_path, replace_file, replacement_target
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
    """Copy ``path`` to a new backup without moving the original away.

    The backup is ``<path>.bak``, or the next free ``<path>.bak.N`` when that
    exists: an earlier backup is never overwritten.
    """
    backup_path = next_backup_path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        staged_backup = Path(tmp.name)
    try:
        copyfile(path, staged_backup)
        copymode(path, staged_backup)
        replace_file(staged_backup, backup_path)
    finally:
        staged_backup.unlink(missing_ok=True)
    return str(backup_path)


# Byte-order marks, longest first: a UTF-32-LE mark begins with the UTF-16-LE one.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)
# The encodings whose codec neither reads nor writes the mark itself. They are
# only ever detected from a mark, so a file read in one is written with it.
_MARKED = {encoding: bom for bom, encoding in _BOMS if encoding != "utf-8-sig"}

# One well-formed UTF-8 multi-byte character (RFC 3629: no overlongs, no
# surrogates, nothing above U+10FFFF).
_UTF8_MULTIBYTE = re.compile(
    rb"[\xc2-\xdf][\x80-\xbf]"
    rb"|\xe0[\xa0-\xbf][\x80-\xbf]|[\xe1-\xec\xee\xef][\x80-\xbf]{2}|\xed[\x80-\x9f][\x80-\xbf]"
    rb"|\xf0[\x90-\xbf][\x80-\xbf]{2}|[\xf1-\xf3][\x80-\xbf]{3}|\xf4[\x80-\x8f][\x80-\xbf]{2}"
)


def _line_of(data: bytes, offset: int) -> int:
    return data.count(b"\n", 0, offset) + 1


def _decode_bytes(data: bytes, source: str | Path | None = None) -> tuple[str, str]:
    """Decode file bytes, returning ``(text, encoding)``.

    A byte-order mark decides: UTF-8, UTF-16, or UTF-32, the mark itself left
    out of the text and restored by :func:`encode_text`. Without one the file is
    UTF-8, or Latin-1 when it is not valid UTF-8 and holds no UTF-8 multi-byte
    character at all, so that every byte is a character of its own. Decoding
    from bytes avoids text-mode newline translation, so ``\\r\\n`` survives for
    the parser to detect.

    Raises:
        ParseError: The bytes are neither: valid UTF-8 apart from stray bytes,
            which as Latin-1 would turn every accented character into mojibake;
            a NUL byte without a mark, as in binary data or UTF-16 without a
            mark; or malformed under the encoding their mark names.
    """
    name = f"{source}: " if source is not None else ""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            body = data if encoding == "utf-8-sig" else data[len(bom) :]
            try:
                return body.decode(encoding), encoding
            except UnicodeDecodeError as exc:
                offset = exc.start + (0 if encoding == "utf-8-sig" else len(bom))
                raise ParseError(
                    f"{name}the byte-order mark says {encoding}, but the bytes after it "
                    f"are not valid {encoding} ({exc.reason})",
                    line=_line_of(data, offset),
                ) from None
    nul = data.find(b"\0")
    if nul != -1:
        raise ParseError(
            f"{name}the file contains a NUL byte, so it is binary, or UTF-16 or "
            "UTF-32 without a byte-order mark; save it as UTF-8",
            line=_line_of(data, nul),
        )
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as exc:
        if _UTF8_MULTIBYTE.search(data) is None:
            return data.decode("latin-1"), "latin-1"
        raise ParseError(
            f"{name}the file is UTF-8 except for byte 0x{data[exc.start]:02X}, which is "
            "not valid UTF-8; reading it as Latin-1 instead would garble every other "
            "non-ASCII character, so fix that byte or save the file as UTF-8",
            line=_line_of(data, exc.start),
        ) from None


def encode_text(text: str, encoding: str) -> bytes:
    """Encode ``text`` in ``encoding``, with the byte-order mark the file was read with."""
    return _MARKED.get(encoding, b"") + text.encode(encoding)


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
    text, encoding = _decode_bytes(data, path)

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
        data = encode_text(content, encoding)
        if atomic:
            # Write content to a temporary file in the same directory so the
            # final rename is guaranteed to be on the same filesystem.
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(data)

            if validate:
                # Read back exactly as a later load would, mark and all.
                try:
                    parse_bib(_decode_bytes(tmp_path.read_bytes())[0])
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
            replace_file(tmp_path, target)
            tmp_path = None
        else:
            # Non-atomic write — preserve a copied backup first if requested.
            if backup and original_exists:
                backup_path = _write_backup(path)
            path.write_bytes(data)

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
