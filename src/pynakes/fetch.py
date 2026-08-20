"""Download arXiv materials and open-access published PDFs into a Pinax ``FileStore``.

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
from typing import Literal

import httpx

from pynakes._identifiers import normalize_arxiv, normalize_doi
from pynakes.fetch_progress import FetchArtifact, FetchProgress, FetchProgressEvent
from pynakes.filestore import FileStore
from pynakes.providers import publisher
from pynakes.providers._http import USER_AGENT, ProviderFetchError, fetch_bytes
from pynakes.providers.metadata import crossref, openalex
from pynakes.providers.repositories import arxiv

FetchArxivBytes = Callable[[str], bytes]
FetchPublishedPdfUrl = Callable[[str], str | None]
UrlPdfValidator = Callable[[str], bool]
FetchAccess = Literal["open", "institutional"]


class ArxivFetchError(Exception):
    """Raised when arXiv material download or extraction fails."""


class ArxivSourceUnavailableError(ArxivFetchError):
    """Raised when arXiv has no TeX/source archive for a preprint.

    Distinct from a corrupt-archive failure: it means the e-print endpoint
    returned a PDF-only submission rather than an extractable source bundle, so
    there is simply nothing to extract. A subclass of :class:`ArxivFetchError`
    so existing ``except ArxivFetchError`` handlers still catch it, while callers
    that care can treat it as a benign "no source" outcome.
    """


class PublishedPdfFetchError(Exception):
    """Raised when open-access published PDF resolution or download fails."""


class SupplementPdfFetchError(Exception):
    """Raised when supplementary-PDF discovery or download fails."""


@dataclass(frozen=True)
class ArxivDownloadResult:
    """Filesystem result of downloading arXiv materials for one citation key."""

    key: str
    arxiv_id: str
    pdf_path: Path | None = None
    source_path: Path | None = None
    source_unavailable: bool = False

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
    access: FetchAccess | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Serialize the result to a JSON-friendly dict.

        Includes ``arxiv_id`` and ``source_path`` (always ``None``) so the
        CLI loop can iterate both :class:`ArxivDownloadResult` and
        :class:`PublishedDownloadResult` items uniformly.
        """
        result = {
            "key": self.key,
            "doi": self.doi,
            "arxiv_id": None,
            "pdf_path": str(self.pdf_path) if self.pdf_path is not None else None,
            "source_path": None,
        }
        if self.access is not None:
            result["access"] = self.access
        if self.reason is not None:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class SupplementDownloadResult:
    """Filesystem result of downloading one unambiguous supplement PDF."""

    key: str
    doi: str
    pdf_path: Path | None = None
    access: FetchAccess | None = None
    reason: str | None = None
    candidates: int = 0

    def to_dict(self) -> dict[str, object]:
        """Serialize the result to a JSON-friendly dict."""
        result: dict[str, object] = {
            "key": self.key,
            "doi": self.doi,
            "arxiv_id": None,
            "artifact": "supplement_pdf",
            "pdf_path": str(self.pdf_path) if self.pdf_path is not None else None,
            "source_path": None,
        }
        if self.access is not None:
            result["access"] = self.access
        if self.reason is not None:
            result["reason"] = self.reason
        if self.candidates:
            result["candidates"] = self.candidates
        return result


def fetch_arxiv_pdf(
    identifier: str,
    timeout: float = 30.0,
    progress: FetchProgress | None = None,
    key: str = "",
) -> bytes:
    """Fetch arXiv PDF bytes for ``identifier``.

    Thin wrapper over :func:`pynakes.providers.repositories.arxiv.fetch_pdf` translating
    provider errors into :class:`ArxivFetchError`.
    """
    try:
        return arxiv.fetch_pdf(
            identifier,
            timeout=timeout,
            progress=_byte_progress(progress, key, "preprint_pdf"),
        )
    except (ProviderFetchError, ValueError) as exc:
        raise ArxivFetchError(str(exc)) from exc


def fetch_arxiv_source(
    identifier: str,
    timeout: float = 30.0,
    progress: FetchProgress | None = None,
    key: str = "",
) -> bytes:
    """Fetch arXiv source archive bytes for ``identifier``.

    Thin wrapper over :func:`pynakes.providers.repositories.arxiv.fetch_source` translating
    provider errors into :class:`ArxivFetchError`.
    """
    try:
        return arxiv.fetch_source(
            identifier,
            timeout=timeout,
            progress=_byte_progress(progress, key, "preprint_source"),
        )
    except (ProviderFetchError, ValueError) as exc:
        raise ArxivFetchError(str(exc)) from exc


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
    progress: FetchProgress | None = None,
) -> ArxivDownloadResult:
    """Download selected arXiv materials and install them in ``store``.

    ``pdf_fetcher`` and ``source_fetcher`` receive the normalized arXiv id and
    return bytes, allowing unit tests and callers to provide deterministic
    fixtures instead of making network requests.
    """
    arxiv_id = _normalize_or_raise(identifier)
    pdf_path: Path | None = None
    source_path: Path | None = None
    source_unavailable = False

    if pdf:
        _emit_progress(progress, "artifact_start", key, "preprint_pdf")
        if pdf_fetcher is None:
            pdf_bytes = fetch_arxiv_pdf(arxiv_id, progress=progress, key=key)
        else:
            pdf_bytes = pdf_fetcher(arxiv_id)
        pdf_path = store.write_preprint_pdf(key, pdf_bytes)
        store.record_artifact(
            key,
            "preprint_pdf",
            source=arxiv.pdf_url(arxiv_id),
            fetched_date=fetched_date,
            refetchable=True,
        )
        _emit_progress(progress, "artifact_done", key, "preprint_pdf", total_bytes=len(pdf_bytes))

    if source:
        _emit_progress(progress, "artifact_start", key, "preprint_source")
        if source_fetcher is None:
            source_bytes = fetch_arxiv_source(arxiv_id, progress=progress, key=key)
        else:
            source_bytes = source_fetcher(arxiv_id)
        store.ensure_root()
        try:
            with (
                store.scratch() as scratch,
                tempfile.TemporaryDirectory(prefix=f"{key}.source.", dir=scratch) as tmp,
            ):
                extracted = Path(tmp) / "source"
                extracted.mkdir()
                extract_arxiv_source(source_bytes, extracted)
                source_path = store.write_preprint_source(key, extracted)
        except ArxivSourceUnavailableError:
            # PDF-only deposit: nothing to extract. Not a corrupt-archive failure,
            # so don't discard a PDF fetched above — report it as unavailable.
            source_unavailable = True
            _emit_progress(
                progress,
                "artifact_done",
                key,
                "preprint_source",
                total_bytes=len(source_bytes),
                message="no arXiv source archive (PDF-only submission)",
            )
        else:
            store.record_artifact(
                key,
                "preprint_source",
                source=arxiv.source_url(arxiv_id),
                fetched_date=fetched_date,
                refetchable=True,
            )
            _emit_progress(
                progress, "artifact_done", key, "preprint_source", total_bytes=len(source_bytes)
            )

    return ArxivDownloadResult(
        key=key,
        arxiv_id=arxiv_id,
        pdf_path=pdf_path,
        source_path=source_path,
        source_unavailable=source_unavailable,
    )


def openalex_oa_pdf_url(
    doi: str,
    *,
    urlopen: Callable[..., object] | None = None,
    cache_file: str | Path | None = None,
) -> str | None:
    """Resolve a DOI to an open-access PDF URL via OpenAlex.

    Returns the ``best_oa_location.pdf_url`` when an open-access copy is
    available; returns ``None`` when there is no resolvable OA copy.

    ``urlopen`` is injectable for testing (same signature as
    ``urllib.request.urlopen``). Results are cached under ``cache_file`` when
    provided, following the same deterministic SHA256 digest pattern as
    :mod:`pynakes.integrity`.
    """
    try:
        return openalex.oa_pdf_url_for_doi(doi, cache_file=cache_file, urlopen=urlopen)
    except (ProviderFetchError, ValueError) as exc:
        raise PublishedPdfFetchError(str(exc)) from exc


def crossref_oa_pdf_url(
    doi: str,
    *,
    urlopen: Callable[..., object] | None = None,
    cache_file: str | Path | None = None,
) -> str | None:
    """Resolve a DOI to an open-access PDF URL via CrossRef.

    Used as a fallback when ``openalex_oa_pdf_url`` returns ``None``.
    """
    try:
        return crossref.oa_pdf_url_for_doi(doi, cache_file=cache_file, urlopen=urlopen)
    except (ProviderFetchError, ValueError) as exc:
        raise PublishedPdfFetchError(str(exc)) from exc


def institutional_pdf_url(doi: str) -> str | None:
    """Discover a publisher PDF URL using the DOI landing page.

    Discovery does not imply entitlement. The subsequent download succeeds
    only when the caller's current network context is authorized by the
    publisher.
    """
    try:
        return publisher.discover_artifacts_for_doi(doi).published_pdf_url
    except (ProviderFetchError, ValueError) as exc:
        raise PublishedPdfFetchError(str(exc)) from exc


def publisher_supplement_pdf_urls(doi: str) -> tuple[str, ...]:
    """Discover supplement links advertised by the DOI landing page."""
    try:
        return publisher.discover_artifacts_for_doi(doi).supplement_pdf_urls
    except (ProviderFetchError, ValueError) as exc:
        raise SupplementPdfFetchError(str(exc)) from exc


def fetch_published_pdf(
    url: str,
    *,
    urlopen: Callable[..., object] | None = None,
    progress: FetchProgress | None = None,
    key: str = "",
) -> bytes:
    """Fetch the bytes of an open-access published PDF from ``url``.

    ``urlopen`` is injectable for testing (same signature as
    ``urllib.request.urlopen``).
    """
    try:
        return fetch_bytes(
            url,
            timeout=30.0,
            error_class=PublishedPdfFetchError,
            label=url,
            opener=urlopen,
            progress=_byte_progress(progress, key, "published_pdf"),
        )
    except PublishedPdfFetchError as exc:
        raise PublishedPdfFetchError(f"Failed to download published PDF from {url}: {exc}") from exc


def _describe_content(data: bytes) -> str:
    """Return a short description of ``data`` for error messages."""
    if not data:
        return "empty response"
    if data.startswith(b"<") or data.startswith(b"<!") or data.startswith(b"<?"):
        return f"HTML ({len(data)} bytes)"
    return f"{len(data)} bytes"


def _url_serves_pdf(url: str, *, timeout: float = 8.0) -> bool:
    """Return ``True`` when *url* serves content that starts with ``%PDF``.

    Uses a streaming GET and reads only the first few bytes to check the magic
    bytes, so the full body is never downloaded for validation. Follows
    redirects. Returns ``False`` on any error or when the content does not
    start with ``%PDF``.
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                header = b""
                for chunk in response.iter_bytes():
                    header += chunk
                    if len(header) >= 256:
                        break
                return header.startswith(b"%PDF")
    except httpx.HTTPError:
        return False


def download_published_material(
    store: FileStore,
    key: str,
    doi: str,
    *,
    url_resolver: FetchPublishedPdfUrl | None = None,
    institutional_url_resolver: FetchPublishedPdfUrl | None = None,
    pdf_fetcher: Callable[[str], bytes] | None = None,
    url_validator: UrlPdfValidator | None = None,
    cache_file: str | Path | None = None,
    fetched_date: str | None = None,
    progress: FetchProgress | None = None,
    access: FetchAccess = "open",
) -> PublishedDownloadResult:
    """Resolve and download a published PDF for *doi* into *store*.

    ``url_resolver`` receives the normalized DOI and returns an OA PDF URL
    (or ``None`` when no OA copy exists). ``pdf_fetcher`` receives the resolved
    URL and returns bytes. Both are injectable for testing.

    ``url_validator`` receives the resolved PDF URL and returns ``True``
    when the URL appears to serve PDF content. By default a streaming GET
    checks the first 256 bytes for ``%PDF`` magic bytes. Pass ``lambda _: True``
    to skip validation.

    Returns a ``PublishedDownloadResult`` with ``pdf_path`` set when the
    download succeeded, or ``None`` when no OA copy was found.
    """
    try:
        normalized = normalize_doi(doi)
    except ValueError as exc:
        raise PublishedPdfFetchError(str(exc)) from exc
    if access not in {"open", "institutional"}:
        raise ValueError(f"Unknown fetch access mode: {access!r}")
    resolver = url_resolver or (
        lambda d: (
            openalex_oa_pdf_url(d, cache_file=cache_file)
            or crossref_oa_pdf_url(d, cache_file=cache_file)
        )
    )
    candidates: list[tuple[str, FetchAccess]] = []
    resolution_error: PublishedPdfFetchError | None = None
    try:
        pdf_url = resolver(normalized)
    except PublishedPdfFetchError as exc:
        if access == "open":
            raise
        resolution_error = exc
        pdf_url = None
    if pdf_url is not None:
        candidates.append((pdf_url, "open"))
    if access == "institutional":
        entitled_resolver = institutional_url_resolver
        if entitled_resolver is None and url_resolver is None:
            entitled_resolver = institutional_pdf_url
        if entitled_resolver is not None:
            entitled_url = entitled_resolver(normalized)
            if entitled_url is not None:
                candidates.append((entitled_url, "institutional"))
    if not candidates:
        if resolution_error is not None:
            raise resolution_error
        reason = (
            "no publisher PDF link found"
            if access == "institutional"
            else "no open-access copy found"
        )
        return PublishedDownloadResult(key=key, doi=normalized, reason=reason)

    _emit_progress(progress, "artifact_start", key, "published_pdf")
    last_reason = "publisher URL did not serve PDF content"
    for candidate_url, candidate_access in candidates:
        try:
            if pdf_fetcher is not None:
                data = pdf_fetcher(candidate_url)
            else:
                if candidate_access == "open":
                    validate_url = url_validator or _url_serves_pdf
                    if not validate_url(candidate_url):
                        continue
                data = fetch_published_pdf(candidate_url, progress=progress, key=key)
        except PublishedPdfFetchError as exc:
            access_reason = _access_error_reason(exc)
            if candidate_access == "institutional" and access_reason is not None:
                last_reason = access_reason
                continue
            raise
        if not data.startswith(b"%PDF"):
            last_reason = _non_pdf_reason(data)
            continue
        pdf_path = store.write_published_pdf(key, data)
        store.record_artifact(
            key,
            "published_pdf",
            source=candidate_url,
            fetched_date=fetched_date,
            refetchable=True,
            access=candidate_access,
        )
        _emit_progress(progress, "artifact_done", key, "published_pdf", total_bytes=len(data))
        return PublishedDownloadResult(
            key=key,
            doi=normalized,
            pdf_path=pdf_path,
            access=candidate_access if candidate_access == "institutional" else None,
        )
    _emit_progress(
        progress,
        "artifact_skip",
        key,
        "published_pdf",
        message=last_reason,
    )
    return PublishedDownloadResult(key=key, doi=normalized, reason=last_reason)


def download_supplement_material(
    store: FileStore,
    key: str,
    doi: str,
    *,
    url_resolver: Callable[[str], tuple[str, ...]] | None = None,
    pdf_fetcher: Callable[[str], bytes] | None = None,
    fetched_date: str | None = None,
    progress: FetchProgress | None = None,
    access: FetchAccess = "open",
) -> SupplementDownloadResult:
    """Download one unambiguous supplementary PDF advertised for *doi*.

    Multiple candidates are reported without choosing one, because the v1
    Pinax layout has one deterministic ``.supplement.pdf`` path.
    """
    try:
        normalized = normalize_doi(doi)
    except ValueError as exc:
        raise SupplementPdfFetchError(str(exc)) from exc
    if access not in {"open", "institutional"}:
        raise ValueError(f"Unknown fetch access mode: {access!r}")
    resolver = url_resolver or publisher_supplement_pdf_urls
    urls = tuple(dict.fromkeys(resolver(normalized)))
    if not urls:
        return SupplementDownloadResult(
            key=key, doi=normalized, reason="no supplementary PDF link found"
        )
    if len(urls) > 1:
        return SupplementDownloadResult(
            key=key,
            doi=normalized,
            reason="multiple supplementary files found; no unambiguous PDF selected",
            candidates=len(urls),
        )

    url = urls[0]
    _emit_progress(progress, "artifact_start", key, "supplement_pdf")
    try:
        if pdf_fetcher is not None:
            data = pdf_fetcher(url)
        else:
            data = fetch_bytes(
                url,
                timeout=30.0,
                error_class=SupplementPdfFetchError,
                label=url,
                progress=_byte_progress(progress, key, "supplement_pdf"),
            )
    except SupplementPdfFetchError as exc:
        access_reason = _access_error_reason(exc)
        if access == "institutional" and access_reason is not None:
            _emit_progress(progress, "artifact_skip", key, "supplement_pdf", message=access_reason)
            return SupplementDownloadResult(key=key, doi=normalized, reason=access_reason)
        raise SupplementPdfFetchError(f"Failed to download supplement from {url}: {exc}") from exc
    if not data.startswith(b"%PDF"):
        reason = _non_pdf_reason(data)
        _emit_progress(progress, "artifact_skip", key, "supplement_pdf", message=reason)
        return SupplementDownloadResult(key=key, doi=normalized, reason=reason)

    pdf_path = store.write_supplement_pdf(key, data)
    store.record_artifact(
        key,
        "supplement_pdf",
        source=url,
        fetched_date=fetched_date,
        refetchable=True,
        access=access,
    )
    _emit_progress(progress, "artifact_done", key, "supplement_pdf", total_bytes=len(data))
    return SupplementDownloadResult(key=key, doi=normalized, pdf_path=pdf_path, access=access)


def _non_pdf_reason(data: bytes) -> str:
    description = _describe_content(data)
    if data.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        return f"authentication required or publisher returned HTML ({len(data)} bytes)"
    return f"publisher URL returned {description}, not a PDF"


def _access_error_reason(exc: Exception) -> str | None:
    message = str(exc)
    if "HTTP 401" in message:
        return "authentication required for publisher PDF"
    if "HTTP 403" in message:
        return "institutional access was not accepted by the publisher"
    return None


def extract_arxiv_source(data: bytes, target_dir: str | Path) -> Path:
    """Safely extract an arXiv source tar archive into ``target_dir``.

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
        with tarfile.open(fileobj=BytesIO(data), mode="r:*") as archive:
            members = archive.getmembers()
            for member in members:
                _validate_tar_member(member, root)
            for member in members:
                _extract_validated_member(archive, member, root)
    except tarfile.TarError as exc:
        raise ArxivFetchError("arXiv source archive is not a readable tar archive") from exc
    return target


def _normalize_or_raise(identifier: str) -> str:
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise ArxivFetchError(f"Malformed arXiv identifier: {identifier!r}")
    return normalized


def _byte_progress(
    progress: FetchProgress | None,
    key: str,
    artifact: FetchArtifact,
) -> Callable[[int, int | None], None] | None:
    if progress is None:
        return None

    def callback(advance: int, total: int | None) -> None:
        progress(
            FetchProgressEvent(
                kind="artifact_progress",
                key=key,
                artifact=artifact,
                advance=advance,
                total_bytes=total,
            )
        )

    return callback


def _emit_progress(
    progress: FetchProgress | None,
    kind: str,
    key: str,
    artifact: FetchArtifact,
    *,
    total_bytes: int | None = None,
    message: str = "",
) -> None:
    if progress is None:
        return
    progress(
        FetchProgressEvent(
            kind=kind,  # type: ignore[arg-type]
            key=key,
            artifact=artifact,
            total_bytes=total_bytes,
            message=message,
        )
    )


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
