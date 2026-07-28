"""DBLP computer-science bibliography client.

DBLP records are addressed by record key (``journals/cacm/Codd70``) and are
published as BibTeX. DBLP's own citation key is prefixed with ``DBLP:`` and
contains path separators, so it is not reused as a citation key; pynakes
generates one instead.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._http import fetch_text
from pynakes.providers.metadata._bibtex_service import bibtex_metadata
from pynakes.providers.records import ReferenceMetadata

BASE_URL = "https://dblp.org/rec"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "DBLP"

# Service bookkeeping rather than bibliographic data.
DROPPED_FIELDS = ("timestamp", "biburl", "bibsource")

_RECORD_KEY_RE = re.compile(r"^[a-z]+(?:/[\w.+-]+){2,}$", re.IGNORECASE)


def normalize_identifier(identifier: str) -> str:
    """Normalize a DBLP record key, dropping a trailing format suffix."""
    value = identifier.strip().strip("/")
    for suffix in (".bib", ".html", ".xml", ".rdf"):
        value = value.removesuffix(suffix)
    if _RECORD_KEY_RE.match(value) is None:
        raise ValueError(f"Malformed DBLP record key: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return the canonical DBLP record URL."""
    return f"{BASE_URL}/{normalize_identifier(identifier)}.html"


def request_url(identifier: str) -> str:
    """Return the DBLP BibTeX URL for one record."""
    return f"{BASE_URL}/{quote(normalize_identifier(identifier), safe='/')}.bib"


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a DBLP record."""
    del dialect
    normalized = normalize_identifier(identifier)
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(
            request_url(normalized),
            accept="application/x-bibtex",
            label=f"DBLP {normalized}",
        )
    )
    return bibtex_metadata(
        text,
        provider=PROVIDER_NAME,
        identifier_kind="dblp",
        identifier=normalized,
        url=record_url(normalized),
        drop_fields=DROPPED_FIELDS,
        keep_provider_key=False,
    )
