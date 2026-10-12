"""Download arXiv materials and open-access published PDFs into a Pinax ``FileStore``.

The public functions are split for testability: URL construction and network
fetching are small injectable pieces, while archive extraction (in
:mod:`pynakes._fetch_source`, re-exported here) is local and deterministic. The
CLI layer decides when online fetching is allowed.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pynakes._fetch_attempts import (
    DiagnosedFetchError,
    attempt_record,
    candidate_urls,
    redact_url,
    status_from_message,
)
from pynakes._fetch_source import (
    MAX_SOURCE_BYTES,
    MAX_SOURCE_MEMBERS,
    ArxivFetchError,
    ArxivSourceUnavailableError,
    extract_arxiv_source,
)
from pynakes._identifiers import normalize_arxiv, normalize_doi
from pynakes.fetch_progress import FetchArtifact, FetchProgress, FetchProgressEvent
from pynakes.filestore import FileStore
from pynakes.providers import publisher
from pynakes.providers._http import ProviderFetchError, fetch_bytes
from pynakes.providers.metadata import crossref, openalex
from pynakes.providers.repositories import arxiv

FetchArxivBytes = Callable[[str], bytes]
FetchPublishedPdfUrl = Callable[[str], str | None]
UrlPdfValidator = Callable[[str], bool]
FetchAccess = Literal["open", "institutional"]

__all__ = [
    "MAX_SOURCE_BYTES",
    "MAX_SOURCE_MEMBERS",
    "ArxivDownloadResult",
    "ArxivFetchError",
    "ArxivSourceUnavailableError",
    "PublishedDownloadResult",
    "PublishedPdfFetchError",
    "SupplementDownloadResult",
    "SupplementPdfFetchError",
    "crossref_oa_pdf_url",
    "download_arxiv_materials",
    "download_published_material",
    "download_supplement_material",
    "extract_arxiv_source",
    "fetch_arxiv_pdf",
    "fetch_arxiv_source",
    "fetch_published_pdf",
    "institutional_pdf_url",
    "openalex_oa_pdf_url",
    "publisher_supplement_pdf_urls",
]


class PublishedPdfFetchError(DiagnosedFetchError):
    """Raised when open-access published PDF resolution or download fails.

    ``attempts`` records each download request made before giving up.
    """


class SupplementPdfFetchError(DiagnosedFetchError):
    """Raised when supplementary-PDF discovery or download fails.

    ``attempts`` records each download request made before giving up.
    """


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
    attempts: tuple[dict, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """Serialize the result to a JSON-friendly dict.

        Includes ``arxiv_id`` and ``source_path`` (always ``None``) so the
        CLI loop can iterate both :class:`ArxivDownloadResult` and
        :class:`PublishedDownloadResult` items uniformly. ``attempts`` is
        listed only for a result that fetched nothing.
        """
        result: dict[str, object] = {
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
        if self.pdf_path is None:
            result["attempts"] = list(self.attempts)
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
    attempts: tuple[dict, ...] = field(default_factory=tuple)

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
        if self.pdf_path is None:
            result["attempts"] = list(self.attempts)
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
    info: dict = {}
    try:
        return arxiv.fetch_pdf(
            identifier,
            timeout=timeout,
            progress=_byte_progress(progress, key, "preprint_pdf"),
            response_info=info,
        )
    except ValueError as exc:
        raise ArxivFetchError(str(exc), artifact="preprint_pdf") from exc
    except ProviderFetchError as exc:
        attempt = attempt_record(arxiv.pdf_url(identifier), info, _error_outcome(exc, info))
        raise ArxivFetchError(str(exc), attempts=[attempt], artifact="preprint_pdf") from exc


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
    info: dict = {}
    try:
        return arxiv.fetch_source(
            identifier,
            timeout=timeout,
            progress=_byte_progress(progress, key, "preprint_source"),
            response_info=info,
        )
    except ValueError as exc:
        raise ArxivFetchError(str(exc), artifact="preprint_source") from exc
    except ProviderFetchError as exc:
        attempt = attempt_record(arxiv.source_url(identifier), info, _error_outcome(exc, info))
        raise ArxivFetchError(str(exc), attempts=[attempt], artifact="preprint_source") from exc


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

    The preprint PDF is installed (and recorded in the manifest) before the
    source is requested. When the source then fails, the raised
    :class:`ArxivFetchError` names ``preprint_source`` as its ``artifact`` and
    carries the installed PDF in ``partial``, so the caller can report both.
    """
    arxiv_id = _normalize_or_raise(identifier)
    pdf_path: Path | None = None
    source_path: Path | None = None
    source_unavailable = False

    if pdf:
        _emit_progress(progress, "artifact_start", key, "preprint_pdf")
        try:
            if pdf_fetcher is None:
                pdf_bytes = fetch_arxiv_pdf(arxiv_id, progress=progress, key=key)
            else:
                pdf_bytes = pdf_fetcher(arxiv_id)
        except ArxivFetchError as exc:
            _diagnose(exc, "preprint_pdf", arxiv.pdf_url(arxiv_id))
            raise
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
        try:
            source_path, source_unavailable = _download_arxiv_source(
                store, key, arxiv_id, source_fetcher, fetched_date, progress
            )
        except ArxivFetchError as exc:
            if exc.artifact is None:
                exc.artifact = "preprint_source"
            if pdf_path is not None:
                # The preprint PDF is installed and recorded; say so with the failure.
                exc.partial = ArxivDownloadResult(key=key, arxiv_id=arxiv_id, pdf_path=pdf_path)
            raise

    return ArxivDownloadResult(
        key=key,
        arxiv_id=arxiv_id,
        pdf_path=pdf_path,
        source_path=source_path,
        source_unavailable=source_unavailable,
    )


def _download_arxiv_source(
    store: FileStore,
    key: str,
    arxiv_id: str,
    source_fetcher: FetchArxivBytes | None,
    fetched_date: str | None,
    progress: FetchProgress | None,
) -> tuple[Path | None, bool]:
    """Fetch and install one arXiv source bundle: its path, and whether arXiv had none."""
    source_path: Path | None = None
    source_unavailable = False
    _emit_progress(progress, "artifact_start", key, "preprint_source")
    try:
        if source_fetcher is None:
            source_bytes = fetch_arxiv_source(arxiv_id, progress=progress, key=key)
        else:
            source_bytes = source_fetcher(arxiv_id)
    except ArxivFetchError as exc:
        _diagnose(exc, "preprint_source", arxiv.source_url(arxiv_id))
        raise
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
    return source_path, source_unavailable


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
    response_info: dict | None = None,
) -> bytes:
    """Fetch the bytes of an open-access published PDF from ``url``.

    ``urlopen`` is injectable for testing (same signature as
    ``urllib.request.urlopen``). ``response_info``, when given, is filled with
    what the server answered (see :func:`~pynakes.providers._http.fetch_bytes`).
    """
    shown = redact_url(url) or url
    try:
        return fetch_bytes(
            url,
            timeout=30.0,
            error_class=PublishedPdfFetchError,
            label=shown,
            opener=urlopen,
            progress=_byte_progress(progress, key, "published_pdf"),
            response_info=response_info,
        )
    except PublishedPdfFetchError as exc:
        raise PublishedPdfFetchError(
            f"Failed to download published PDF from {shown}: {exc}"
        ) from exc


def _describe_content(data: bytes) -> str:
    """Return a short description of ``data`` for error messages."""
    if not data:
        return "empty response"
    if data.startswith(b"<") or data.startswith(b"<!") or data.startswith(b"<?"):
        return f"HTML ({len(data)} bytes)"
    return f"{len(data)} bytes"


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

    Each resolved URL is tried in the order
    :func:`pynakes._fetch_attempts.candidate_urls` gives — an APS article's
    canonical ``journals.aps.org`` PDF URL first, an ``https://`` form before a
    plain ``http://`` one — until one serves a PDF. Each request is a single
    GET whose bytes are kept only when they start with ``%PDF``.

    ``url_validator``, when given, is asked first about each open-access URL and
    a ``False`` skips it without a download.

    Returns a ``PublishedDownloadResult`` with ``pdf_path`` set when the
    download succeeded; otherwise its ``reason`` says why and its
    ``attempts`` records every request made. Raises
    :class:`PublishedPdfFetchError`, with the same ``attempts``, when a request
    failed with an error that is not an access refusal.
    """
    try:
        normalized = normalize_doi(doi)
    except ValueError as exc:
        raise PublishedPdfFetchError(str(exc), artifact="published_pdf") from exc
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
    attempts: list[dict] = []
    errors: list[PublishedPdfFetchError] = []
    tried: set[str] = set()
    last_reason = "publisher URL did not serve PDF content"
    for candidate_url, candidate_access in candidates:
        for url in candidate_urls(candidate_url, normalized):
            if url in tried:
                continue
            tried.add(url)
            info: dict = {}
            try:
                data = _published_bytes(
                    url, candidate_access, pdf_fetcher, url_validator, info, progress, key
                )
            except PublishedPdfFetchError as exc:
                if info.get("status") is None:
                    info["status"] = status_from_message(str(exc))
                attempts.append(attempt_record(url, info, _error_outcome(exc, info)))
                access_reason = _access_error_reason(exc)
                if candidate_access == "institutional" and access_reason is not None:
                    last_reason = access_reason
                else:
                    errors.append(exc)
                continue
            if data is None or not data.startswith(b"%PDF"):
                attempts.append(attempt_record(url, info, "not_pdf"))
                if data is not None:
                    last_reason = _non_pdf_reason(data, candidate_access)
                continue
            pdf_path = store.write_published_pdf(key, data)
            store.record_artifact(
                key,
                "published_pdf",
                source=url,
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
    if errors:
        message = str(errors[0])
        if len(attempts) > 1:
            message = f"{message} ({len(attempts)} URLs tried)"
        raise PublishedPdfFetchError(message, attempts=attempts, artifact="published_pdf")
    _emit_progress(progress, "artifact_skip", key, "published_pdf", message=last_reason)
    return PublishedDownloadResult(
        key=key, doi=normalized, reason=last_reason, attempts=tuple(attempts)
    )


def _published_bytes(
    url: str,
    access: FetchAccess,
    pdf_fetcher: Callable[[str], bytes] | None,
    url_validator: UrlPdfValidator | None,
    info: dict,
    progress: FetchProgress | None,
    key: str,
) -> bytes | None:
    """Request one published-PDF URL; ``None`` when ``url_validator`` refused it."""
    if pdf_fetcher is not None:
        return pdf_fetcher(url)
    if access == "open" and url_validator is not None and not url_validator(url):
        return None
    return fetch_published_pdf(url, progress=progress, key=key, response_info=info)


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
    Pinax layout has one deterministic ``.supplement.pdf`` path. A result that
    fetched nothing, and a raised :class:`SupplementPdfFetchError`, carry the
    request made in ``attempts``.
    """
    try:
        normalized = normalize_doi(doi)
    except ValueError as exc:
        raise SupplementPdfFetchError(str(exc), artifact="supplement_pdf") from exc
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
    shown = redact_url(url) or url
    info: dict = {}
    _emit_progress(progress, "artifact_start", key, "supplement_pdf")
    try:
        if pdf_fetcher is not None:
            data = pdf_fetcher(url)
        else:
            data = fetch_bytes(
                url,
                timeout=30.0,
                error_class=SupplementPdfFetchError,
                label=shown,
                progress=_byte_progress(progress, key, "supplement_pdf"),
                response_info=info,
            )
    except SupplementPdfFetchError as exc:
        if info.get("status") is None:
            info["status"] = status_from_message(str(exc))
        attempts = (attempt_record(url, info, _error_outcome(exc, info)),)
        access_reason = _access_error_reason(exc)
        if access == "institutional" and access_reason is not None:
            _emit_progress(progress, "artifact_skip", key, "supplement_pdf", message=access_reason)
            return SupplementDownloadResult(
                key=key, doi=normalized, reason=access_reason, attempts=attempts
            )
        raise SupplementPdfFetchError(
            f"Failed to download supplement from {shown}: {exc}",
            attempts=attempts,
            artifact="supplement_pdf",
        ) from exc
    if not data.startswith(b"%PDF"):
        reason = _non_pdf_reason(data, access)
        _emit_progress(progress, "artifact_skip", key, "supplement_pdf", message=reason)
        return SupplementDownloadResult(
            key=key,
            doi=normalized,
            reason=reason,
            attempts=(attempt_record(url, info, "not_pdf"),),
        )

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


def _non_pdf_reason(data: bytes, access: FetchAccess = "institutional") -> str:
    description = _describe_content(data)
    if data.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        if access == "open":
            return f"publisher URL served an HTML page ({len(data)} bytes), not a PDF"
        return f"authentication required or publisher returned HTML ({len(data)} bytes)"
    return f"publisher URL returned {description}, not a PDF"


def _access_error_reason(exc: Exception) -> str | None:
    message = str(exc)
    if "HTTP 401" in message:
        return "authentication required for publisher PDF"
    if "HTTP 403" in message:
        return "institutional access was not accepted by the publisher"
    return None


def _error_outcome(exc: Exception, info: dict) -> str:
    """Classify a failed request: an HTTP error status, or no usable response at all."""
    status = info.get("status") or status_from_message(str(exc))
    return "http_error" if isinstance(status, int) and status >= 400 else "network_error"


def _diagnose(exc: DiagnosedFetchError, artifact: str, url: str) -> None:
    """Name the artifact a fetch failed for, and its request, when the raiser did not."""
    if exc.artifact is None:
        exc.artifact = artifact
    if not exc.attempts:
        exc.attempts = (
            attempt_record(url, {"status": status_from_message(str(exc))}, _error_outcome(exc, {})),
        )


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
