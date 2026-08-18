"""IACR Cryptology ePrint Archive client.

The ePrint Archive addresses preprints by ``<year>/<number>`` — the
cryptography community's canonical id, not a DOI (many ePrint papers never
receive one). Unlike INSPIRE-HEP, DBLP, or the ACL Anthology, the Archive has
no dedicated citation endpoint: each paper's own landing page embeds a
ready-made BibTeX record inline (inside a ``<pre id="bibtex">`` block), so
that record is extracted from the page before sharing the parse-and-relabel
step in :mod:`pynakes.providers.metadata._bibtex_service`.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable

from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.metadata._bibtex_service import bibtex_metadata
from pynakes.providers.records import ReferenceMetadata

BASE_URL = "https://eprint.iacr.org"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "IACR ePrint Archive"

_ID_RE = re.compile(r"^\d{4}/\d+$")
_BIBTEX_BLOCK_RE = re.compile(r'<pre[^>]*\bid="bibtex"[^>]*>(.*?)</pre>', re.IGNORECASE | re.DOTALL)


def normalize_identifier(identifier: str) -> str:
    """Normalize an IACR ePrint id, dropping a trailing format suffix."""
    value = identifier.strip().strip("/")
    for suffix in (".pdf", ".bib"):
        value = value.removesuffix(suffix)
    if _ID_RE.match(value) is None:
        raise ValueError(f"Malformed IACR ePrint id: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return the canonical ePrint landing page for one paper.

    The landing page is also the only place the BibTeX record is published,
    so it doubles as the request URL.
    """
    return f"{BASE_URL}/{normalize_identifier(identifier)}"


def request_url(identifier: str) -> str:
    """Return the URL fetched for ``identifier``."""
    return record_url(identifier)


def _extract_bibtex(page: str) -> str | None:
    """Return the embedded BibTeX record from an ePrint landing page, if present."""
    match = _BIBTEX_BLOCK_RE.search(page)
    if match is None:
        return None
    text = html.unescape(match.group(1)).strip()
    return text or None


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an IACR ePrint record.

    IACR's own citation key (``cryptoeprint:2023/1234``) is service
    bookkeeping rather than a citation-key convention the community reuses
    (unlike INSPIRE's texkey), so it is discarded and a key is generated
    instead.
    """
    del dialect
    normalized = normalize_identifier(identifier)
    page = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(request_url(normalized), label=f"IACR ePrint {normalized}")
    )
    text = _extract_bibtex(page)
    if not text:
        raise ProviderFetchError(f"IACR ePrint Archive has no record for {normalized!r}")
    return bibtex_metadata(
        text,
        provider=PROVIDER_NAME,
        identifier_kind="iacr",
        identifier=normalized,
        url=record_url(normalized),
        keep_provider_key=False,
    )
