"""INSPIRE-HEP literature client.

INSPIRE is the high-energy-physics literature database. Records are addressed
either by numeric record id or by texkey — the ``Author:2024abc`` form the HEP
community uses as its citation key — and INSPIRE publishes BibTeX directly,
including the eprint, report numbers, and journal reference in one record.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.metadata._bibtex_service import bibtex_metadata
from pynakes.providers.records import ReferenceMetadata

API_URL = "https://inspirehep.net/api/literature"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "INSPIRE-HEP"

_RECORD_ID_RE = re.compile(r"^\d+$")
_TEXKEY_RE = re.compile(r"^[A-Za-z][\w.'\-]*:\d{4}[a-z]{2,3}$")


def normalize_identifier(identifier: str) -> str:
    """Normalize an INSPIRE record id or texkey.

    Record ids stay numeric; texkeys keep their exact case, because INSPIRE
    texkeys are case-sensitive and are reused verbatim as citation keys.
    """
    value = identifier.strip()
    if _RECORD_ID_RE.match(value) or _TEXKEY_RE.match(value):
        return value
    raise ValueError(f"Malformed INSPIRE record id or texkey: {identifier!r}")


def is_record_id(identifier: str) -> bool:
    """Return whether ``identifier`` is a numeric INSPIRE record id."""
    return bool(_RECORD_ID_RE.match(identifier.strip()))


def record_url(identifier: str) -> str:
    """Return the canonical INSPIRE literature URL for a record id.

    Only record ids address a single record; a texkey is resolved through a
    search, which is not a citable landing page.
    """
    normalized = normalize_identifier(identifier)
    if not is_record_id(normalized):
        raise ValueError(f"INSPIRE literature URLs address record ids, not texkeys: {identifier!r}")
    return f"https://inspirehep.net/literature/{normalized}"


def request_url(identifier: str) -> str:
    """Return the INSPIRE API URL that answers with BibTeX for ``identifier``."""
    normalized = normalize_identifier(identifier)
    if is_record_id(normalized):
        return f"{API_URL}/{normalized}?format=bibtex"
    query = quote(f"texkeys:{normalized}", safe="")
    return f"{API_URL}?q={query}&format=bibtex&size=1"


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an INSPIRE-HEP record."""
    del dialect
    normalized = normalize_identifier(identifier)
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(
            request_url(normalized),
            accept="application/x-bibtex",
            label=f"INSPIRE {normalized}",
        )
    )
    if not text.strip():
        raise ProviderFetchError(f"INSPIRE-HEP has no record for {normalized!r}")
    return bibtex_metadata(
        text,
        provider=PROVIDER_NAME,
        identifier_kind="inspire",
        identifier=normalized,
        url=record_url(normalized) if is_record_id(normalized) else None,
    )
