"""Finding the URLs to request for one published PDF, and what each one turned out to be.

Not public API. :func:`pynakes.fetch.download_published_material` asks this
module for the candidate URLs of a DOI before it downloads anything. Every
lookup made on the way — an open-access index, the DOI landing page — is
recorded as a ``resolve`` attempt, so a run that never reached a PDF link still
says which request failed and how.

Two rules keep a stored file's label honest:

* An arXiv DataCite DOI (``10.48550/arXiv.*``) names a preprint. It is never
  resolved as if it named a version of record.
* A PDF served by a preprint repository is a preprint, whichever route led to
  it. Such URLs are tried last, after every publisher candidate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import quote

from pynakes._fetch_attempts import (
    access_error_reason,
    aps_pdf_url,
    attempt_record,
    error_outcome,
    is_preprint_host,
    status_from_message,
)

#: Why a DOI under arXiv's own prefix is not looked up as a published version.
ARXIV_DOI_REASON = "the DOI is arXiv's own (10.48550/arXiv.*), which names the preprint"


@dataclass
class PublishedCandidates:
    """The URLs to request for one DOI, and the lookups made to find them.

    ``urls`` pairs each URL with the access context it was found under, in the
    order to try them. ``attempts`` holds one ``resolve`` record per lookup that
    failed. ``errors`` are the lookup failures that are not access refusals;
    ``refusal`` is the reason an access refusal gave, when one did.
    """

    urls: list[tuple[str, str]] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)
    refusal: str | None = None


def resolve_candidates(
    doi: str,
    access: str,
    *,
    open_resolver: Callable[[str], str | None],
    entitled_resolver: Callable[[str], str | None] | None,
    error_class: type[Exception],
) -> PublishedCandidates:
    """Look up the URLs that may serve the published PDF for the normalized *doi*.

    The open-access resolver is asked first. Under ``institutional`` access the
    DOI landing page is asked next, and a publisher route derived from the DOI
    itself (an APS article's canonical PDF URL) is added after both, so a
    landing page that refuses the request does not leave nothing to try.
    """
    found = PublishedCandidates()
    url = _lookup(found, doi, open_resolver, error_class, label="open-access index", access=access)
    if url is not None:
        found.urls.append((url, "open"))
    if access == "institutional":
        if entitled_resolver is not None:
            entitled = _lookup(
                found, doi, entitled_resolver, error_class, label="landing", access=access
            )
            if entitled is not None:
                found.urls.append((entitled, "institutional"))
        derived = aps_pdf_url(doi)
        if derived is not None:
            found.urls.append((derived, "institutional"))
    # A preprint repository's copy is a last resort: try every publisher first.
    found.urls.sort(key=lambda item: is_preprint_host(item[0]))
    return found


def _lookup(
    found: PublishedCandidates,
    doi: str,
    resolver: Callable[[str], str | None],
    error_class: type[Exception],
    *,
    label: str,
    access: str,
) -> str | None:
    try:
        return resolver(doi)
    except error_class as exc:
        info = {"status": status_from_message(str(exc))}
        url = f"https://doi.org/{quote(doi, safe='/')}" if label == "landing" else None
        record = attempt_record(url or "", info, error_outcome(exc, info), stage="resolve")
        record["lookup"] = "doi_landing_page" if label == "landing" else "open_access_index"
        record["error"] = str(exc)
        if url is None:
            record["url"] = None
        found.attempts.append(record)
        refusal = access_error_reason(exc)
        if access == "institutional" and refusal is not None:
            found.refusal = f"DOI landing page refused the request: {refusal}"
        else:
            found.errors.append(exc)
        return None
