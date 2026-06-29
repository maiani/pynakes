"""Download arXiv materials and open-access published PDFs into a Pinax ``FileStore``.

The public functions are split for testability: URL construction and network
fetching are small injectable pieces, while archive extraction is local and
deterministic. The CLI layer decides when online fetching is allowed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request
from urllib.request import urlopen as _default_urlopen

from pynakes._constants import ARXIV_BASE, OPENALEX_API, USER_AGENT
from pynakes._identifiers import normalize_arxiv, normalize_doi
from pynakes.filestore import FileStore
from pynakes.importer import _fetch_url

FetchArxivBytes = Callable[[str], bytes]
FetchPublishedPdfUrl = Callable[[str], str | None]


class ArxivFetchError(Exception):
    """Raised when arXiv material download or extraction fails."""


class PublishedPdfFetchError(Exception):
    """Raised when open-access published PDF resolution or download fails."""


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


@dataclass(frozen=True)
class PublishedDownloadResult:
    """Filesystem result of downloading an open-access published PDF for one citation key."""

    key: str
    doi: str
    pdf_path: Path | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Serialize the result to a JSON-friendly dict.

        Includes ``arxiv_id`` and ``source_path`` (always ``None``) so the
        CLI loop can iterate both :class:`ArxivDownloadResult` and
        :class:`PublishedDownloadResult` items uniformly.
        """
        return {
            "key": self.key,
            "doi": self.doi,
            "arxiv_id": None,
            "pdf_path": str(self.pdf_path) if self.pdf_path is not None else None,
            "source_path": None,
        }


def arxiv_pdf_url(identifier: str) -> str:
    """Return the canonical arXiv PDF URL for ``identifier``."""
    normalized = _normalize_or_raise(identifier)
    return f"{ARXIV_BASE}/pdf/{quote(normalized, safe='/')}"


def arxiv_source_url(identifier: str) -> str:
    """Return the canonical arXiv source archive URL for ``identifier``."""
    normalized = _normalize_or_raise(identifier)
    return f"{ARXIV_BASE}/e-print/{quote(normalized, safe='/')}"


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


def openalex_oa_pdf_url(
    doi: str,
    *,
    urlopen: Callable[..., object] | None = None,
    cache_dir: str | Path | None = None,
) -> str | None:
    """Resolve a DOI to an open-access PDF URL via OpenAlex.

    Returns the ``best_oa_location.pdf_url`` when an open-access copy is
    available; returns ``None`` when there is no resolvable OA copy.

    ``urlopen`` is injectable for testing (same signature as
    ``urllib.request.urlopen``). Results are cached under ``cache_dir`` when
    provided, following the same deterministic SHA256 digest pattern as
    :mod:`pynakes.integrity`.
    """
    normalized = _normalize_doi_or_raise(doi)
    url = f"{OPENALEX_API}{quote(normalized, safe='')}"

    opener = urlopen or _default_urlopen
    cache_path = _openalex_cache_path(cache_dir, normalized)
    if cache_path is not None and cache_path.exists():
        text = cache_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = _fetch_published_bytes(
            url,
            opener=opener,
            timeout=15.0,
            error_prefix=f"OpenAlex lookup failed for DOI {normalized!r}",
        ).decode("utf-8", errors="replace")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PublishedPdfFetchError(
            f"OpenAlex returned invalid JSON for DOI {normalized!r}: {exc}"
        ) from exc

    if cache_path is not None and not cache_path.exists():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(text, encoding="utf-8")

    if not isinstance(data, dict):
        return None

    best_oa = data.get("best_oa_location")
    if not isinstance(best_oa, dict):
        return None

    pdf_url = best_oa.get("pdf_url")
    if not isinstance(pdf_url, str) or not pdf_url.strip():
        return None
    return pdf_url.strip()


def fetch_published_pdf(url: str, *, urlopen: Callable[..., object] | None = None) -> bytes:
    """Fetch the bytes of an open-access published PDF from ``url``.

    ``urlopen`` is injectable for testing (same signature as
    ``urllib.request.urlopen``).
    """
    opener = urlopen or _default_urlopen
    return _fetch_published_bytes(
        url,
        opener=opener,
        timeout=30.0,
        error_prefix=f"Failed to download published PDF from {url}",
    )


def download_published_material(
    store: FileStore,
    key: str,
    doi: str,
    *,
    url_resolver: FetchPublishedPdfUrl | None = None,
    pdf_fetcher: Callable[[str], bytes] | None = None,
    cache_dir: str | Path | None = None,
    fetched_date: str | None = None,
) -> PublishedDownloadResult:
    """Resolve an OA PDF URL for *doi* and download it into *store*.

    ``url_resolver`` receives the normalized DOI and returns an OA PDF URL
    (or ``None`` when no OA copy exists). ``pdf_fetcher`` receives the resolved
    URL and returns bytes. Both are injectable for testing.

    Returns a ``PublishedDownloadResult`` with ``pdf_path`` set when the
    download succeeded, or ``None`` when no OA copy was found.
    """
    normalized = _normalize_doi_or_raise(doi)
    resolver = url_resolver or (lambda d: openalex_oa_pdf_url(d, cache_dir=cache_dir))
    pdf_url = resolver(normalized)
    if pdf_url is None:
        return PublishedDownloadResult(key=key, doi=normalized)

    fetcher = pdf_fetcher or fetch_published_pdf
    data = fetcher(pdf_url)
    pdf_path = store.write_published_pdf(key, data)
    store.record_artifact(
        key,
        "published_pdf",
        source=pdf_url,
        fetched_date=fetched_date,
        refetchable=True,
    )
    return PublishedDownloadResult(key=key, doi=normalized, pdf_path=pdf_path)


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
    return _fetch_url(
        url,
        timeout=timeout,
        error_class=ArxivFetchError,
        label=f"{identifier} {kind}",
    )


def _normalize_or_raise(identifier: str) -> str:
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ArxivFetchError(f"Malformed arXiv identifier: {identifier!r}")
    return normalized


def _normalize_doi_or_raise(doi: str) -> str:
    try:
        return normalize_doi(doi)
    except ValueError as exc:
        raise PublishedPdfFetchError(str(exc)) from exc


def _fetch_published_bytes(
    url: str,
    *,
    opener: Callable[..., object],
    timeout: float,
    error_prefix: str,
) -> bytes:
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with opener(request, timeout=timeout) as response:  # type: ignore[arg-type]
            return response.read()
    except (HTTPError, URLError, OSError) as exc:
        raise PublishedPdfFetchError(f"{error_prefix}: {exc}") from exc


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


def _openalex_cache_path(cache_dir: str | Path | None, doi: str) -> Path | None:
    """Return a deterministic cache path for an OpenAlex DOI lookup, or ``None``."""
    if cache_dir is None:
        return None
    digest = hashlib.sha256(doi.lower().encode("utf-8")).hexdigest()
    return Path(cache_dir) / "openalex" / f"{digest}.json"
