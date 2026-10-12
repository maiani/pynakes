"""Safe extraction of arXiv source bundles, and the arXiv fetch errors.

Split out of :mod:`pynakes.fetch`, which re-exports the public names defined
here. Extraction is local and deterministic: it never touches the network.
"""

from __future__ import annotations

import re
import shutil
import tarfile
import zlib
from io import BytesIO
from pathlib import Path, PurePosixPath

from pynakes._fetch_attempts import DiagnosedFetchError

_GZIP_MAGIC = b"\x1f\x8b"
_GZIP_FEXTRA = 0x04
_GZIP_FNAME = 0x08
_PLAIN_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
_SINGLE_FILE_FALLBACK = "main.tex"

# Limits on what one arXiv source bundle may unpack to. The bundle is content
# its author controls, and a few hundred kilobytes of gzip can expand to
# gigabytes or to hundreds of thousands of files.
MAX_SOURCE_BYTES = 1024 * 1024 * 1024
MAX_SOURCE_MEMBERS = 20_000


class ArxivFetchError(DiagnosedFetchError):
    """Raised when arXiv material download or extraction fails."""


class ArxivSourceUnavailableError(ArxivFetchError):
    """Raised when arXiv has no TeX/source archive for a preprint.

    Distinct from a corrupt-archive failure: it means the e-print endpoint
    returned a PDF-only submission rather than an extractable source bundle, so
    there is simply nothing to extract. A subclass of :class:`ArxivFetchError`
    so existing ``except ArxivFetchError`` handlers still catch it, while callers
    that care can treat it as a benign "no source" outcome.
    """


def extract_arxiv_source(data: bytes, target_dir: str | Path) -> Path:
    """Safely extract an arXiv source bundle into ``target_dir``.

    The e-print endpoint serves a multi-file submission as a gzipped tar, and an
    old single-file submission as that one file gzipped, with no tar around it.
    A tar is extracted member by member; a single file is written under the name
    its gzip header records, or ``main.tex`` when the header records no plain
    file name.

    Raises :class:`ArxivSourceUnavailableError` when the e-print endpoint
    returned a PDF instead of a source bundle (a PDF-only submission has no
    extractable TeX/source), and :class:`ArxivFetchError` when the bytes are an
    actual but unreadable/corrupt archive.
    """
    if data.startswith(b"%PDF"):
        raise ArxivSourceUnavailableError(
            "arXiv has no TeX/source archive for this preprint; the e-print "
            "endpoint returned a PDF (PDF-only submission)"
        )
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve(strict=False)
    try:
        try:
            archive = tarfile.open(fileobj=BytesIO(data), mode="r:*")
        except tarfile.ReadError:
            if not data.startswith(_GZIP_MAGIC):
                raise
            _write_single_file_source(data, root)
            return target
        with archive:
            members = archive.getmembers()
            _check_source_size(members)
            for member in members:
                _validate_tar_member(member, root)
            for member in members:
                _extract_validated_member(archive, member, root)
    except tarfile.TarError as exc:
        raise ArxivFetchError("arXiv source archive is not a readable tar archive") from exc
    except (EOFError, zlib.error) as exc:
        # tarfile lets these escape from a truncated or damaged gzip stream.
        raise ArxivFetchError("arXiv source archive is truncated or corrupt") from exc
    return target


def _check_source_size(members: list[tarfile.TarInfo]) -> None:
    """Refuse a tar whose headers declare more than the source limits."""
    if len(members) > MAX_SOURCE_MEMBERS:
        raise ArxivFetchError(
            f"arXiv source archive has {len(members)} members, "
            f"more than the {MAX_SOURCE_MEMBERS} allowed"
        )
    if sum(member.size for member in members if member.isfile()) > MAX_SOURCE_BYTES:
        raise ArxivFetchError(
            f"arXiv source archive unpacks to more than {MAX_SOURCE_BYTES >> 20} MiB"
        )


def _write_single_file_source(data: bytes, root: Path) -> None:
    """Decompress a single gzipped source file in bounded chunks."""
    target = root / _gzip_member_name(data)
    decompressor = zlib.decompressobj(wbits=31)
    written = 0
    try:
        with target.open("wb") as output:
            pending = data
            while not decompressor.eof:
                chunk = decompressor.decompress(pending, 1 << 20)
                pending = decompressor.unconsumed_tail
                if not chunk and not pending:
                    raise ArxivFetchError("arXiv source file is truncated or corrupt")
                written += len(chunk)
                if written > MAX_SOURCE_BYTES:
                    raise ArxivFetchError(
                        f"arXiv source file unpacks to more than {MAX_SOURCE_BYTES >> 20} MiB"
                    )
                output.write(chunk)
    except zlib.error as exc:
        target.unlink(missing_ok=True)
        raise ArxivFetchError("arXiv source file is not a readable gzip file") from exc
    except ArxivFetchError:
        target.unlink(missing_ok=True)
        raise


def _gzip_member_name(data: bytes) -> str:
    """Return the file name an already-validated gzip header records (RFC 1952).

    Only the final path component is kept, and only when it is a plain name,
    so a recorded name can never place the file outside the source directory;
    otherwise the file is ``main.tex``.
    """
    flags = data[3]
    if not flags & _GZIP_FNAME:
        return _SINGLE_FILE_FALLBACK
    start = 10
    if flags & _GZIP_FEXTRA:
        start += 2 + int.from_bytes(data[10:12], "little")
    recorded = data[start : data.index(b"\0", start)].decode("latin-1")
    name = re.split(r"[\\/]", recorded)[-1]
    return name if _PLAIN_FILE_NAME.fullmatch(name) else _SINGLE_FILE_FALLBACK


def _validate_tar_member(member: tarfile.TarInfo, root: Path) -> None:
    name = member.name
    if not name or "\\" in name:
        raise ArxivFetchError(f"Unsafe arXiv source archive path: {name!r}")

    parts = PurePosixPath(name).parts
    if PurePosixPath(name).is_absolute() or ".." in parts:
        raise ArxivFetchError(f"Unsafe arXiv source archive path: {name!r}")

    target = (root / Path(*parts)).resolve(strict=False)
    if not target.is_relative_to(root):
        raise ArxivFetchError(f"Unsafe arXiv source archive path: {name!r}")

    if member.issym() or member.islnk():
        raise ArxivFetchError(f"Unsafe arXiv source archive link: {name!r}")
    if not (member.isfile() or member.isdir()):
        raise ArxivFetchError(f"Unsupported arXiv source archive member: {name!r}")


def _extract_validated_member(
    archive: tarfile.TarFile, member: tarfile.TarInfo, root: Path
) -> None:
    target = root / Path(*PurePosixPath(member.name).parts)
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    source = archive.extractfile(member)
    if source is None:
        raise ArxivFetchError(f"Could not read arXiv source archive member: {member.name!r}")
    with source, target.open("wb") as output:
        shutil.copyfileobj(source, output)
