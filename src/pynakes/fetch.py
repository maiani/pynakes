"""Download arXiv materials into a Pinax ``FileStore``.

The public functions are split for testability: URL construction and network
fetching are small injectable pieces, while archive extraction is local and
deterministic. The CLI layer decides when online fetching is allowed.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pynakes.filestore import FileStore
from pynakes.importer import normalize_arxiv

_USER_AGENT = "pynakes/0.3.0 arxiv material fetch (mailto:unknown@example.invalid)"

FetchArxivBytes = Callable[[str], bytes]


class ArxivFetchError(Exception):
    """Raised when arXiv material download or extraction fails."""


@dataclass(frozen=True)
class ArxivDownloadResult:
    """Filesystem result of downloading arXiv materials for one citation key."""

    key: str
    arxiv_id: str
    pdf_path: Path | None = None
    source_path: Path | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Serialize the result to a JSON-friendly dict."""
        return {
            "key": self.key,
            "arxiv_id": self.arxiv_id,
            "pdf_path": str(self.pdf_path) if self.pdf_path is not None else None,
            "source_path": str(self.source_path) if self.source_path is not None else None,
        }


def arxiv_pdf_url(identifier: str) -> str:
    """Return the canonical arXiv PDF URL for ``identifier``."""
    normalized = _normalize_or_raise(identifier)
    return f"https://arxiv.org/pdf/{quote(normalized, safe='/')}"


def arxiv_source_url(identifier: str) -> str:
    """Return the canonical arXiv source archive URL for ``identifier``."""
    normalized = _normalize_or_raise(identifier)
    return f"https://arxiv.org/e-print/{quote(normalized, safe='/')}"


def fetch_arxiv_pdf(identifier: str, timeout: float = 30.0) -> bytes:
    """Fetch arXiv PDF bytes for ``identifier``."""
    return _fetch_bytes(arxiv_pdf_url(identifier), _normalize_or_raise(identifier), "PDF", timeout)


def fetch_arxiv_source(identifier: str, timeout: float = 30.0) -> bytes:
    """Fetch arXiv source archive bytes for ``identifier``."""
    return _fetch_bytes(
        arxiv_source_url(identifier), _normalize_or_raise(identifier), "source", timeout
    )


def download_arxiv_materials(
    store: FileStore,
    key: str,
    identifier: str,
    *,
    pdf: bool = True,
    source: bool = True,
    pdf_fetcher: FetchArxivBytes | None = None,
    source_fetcher: FetchArxivBytes | None = None,
    fetched_date: str | None = None,
) -> ArxivDownloadResult:
    """Download selected arXiv materials and install them in ``store``.

    ``pdf_fetcher`` and ``source_fetcher`` receive the normalized arXiv id and
    return bytes, allowing unit tests and callers to provide deterministic
    fixtures instead of making network requests.
    """
    arxiv_id = _normalize_or_raise(identifier)
    pdf_path: Path | None = None
    source_path: Path | None = None

    if pdf:
        pdf_bytes = (pdf_fetcher or fetch_arxiv_pdf)(arxiv_id)
        pdf_path = store.write_preprint_pdf(key, pdf_bytes)
        store.record_artifact(
            key,
            "preprint_pdf",
            source=arxiv_pdf_url(arxiv_id),
            fetched_date=fetched_date,
            refetchable=True,
        )

    if source:
        source_bytes = (source_fetcher or fetch_arxiv_source)(arxiv_id)
        store.ensure_root()
        with tempfile.TemporaryDirectory(prefix=f".{key}_preprint.", dir=store.root) as tmp:
            extracted = Path(tmp) / "source"
            extracted.mkdir()
            extract_arxiv_source(source_bytes, extracted)
            source_path = store.write_preprint_source(key, extracted)
        store.record_artifact(
            key,
            "preprint_source",
            source=arxiv_source_url(arxiv_id),
            fetched_date=fetched_date,
            refetchable=True,
        )

    return ArxivDownloadResult(
        key=key,
        arxiv_id=arxiv_id,
        pdf_path=pdf_path,
        source_path=source_path,
    )


def extract_arxiv_source(data: bytes, target_dir: str | Path) -> Path:
    """Safely extract an arXiv source tar archive into ``target_dir``."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve(strict=False)
    try:
        with tarfile.open(fileobj=BytesIO(data), mode="r:*") as archive:
            members = archive.getmembers()
            for member in members:
                _validate_tar_member(member, root)
            for member in members:
                _extract_validated_member(archive, member, root)
    except tarfile.TarError as exc:
        raise ArxivFetchError("arXiv source archive is not a readable tar archive") from exc
    return target


def _fetch_bytes(url: str, identifier: str, kind: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise ArxivFetchError(f"arXiv returned HTTP {exc.code} for {identifier} {kind}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ArxivFetchError(f"Could not fetch arXiv {kind} for {identifier}: {reason}") from exc


def _normalize_or_raise(identifier: str) -> str:
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ArxivFetchError(f"Malformed arXiv identifier: {identifier!r}")
    return normalized


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
