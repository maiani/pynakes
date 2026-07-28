"""ACL Anthology client for computational-linguistics proceedings.

The Anthology publishes a BibTeX record per paper, which carries the venue
title, editors, and location that the DOI record omits. Papers are addressed by
Anthology id, in either the legacy ``N19-1423`` form or the current
``2023.acl-long.1`` form.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote

from pynakes.providers._http import fetch_text
from pynakes.providers.metadata._bibtex_service import bibtex_metadata
from pynakes.providers.records import ReferenceMetadata

BASE_URL = "https://aclanthology.org"
DOI_PREFIX = "10.18653/v1"
RawFetcher = Callable[[str], str]

PROVIDER_NAME = "ACL Anthology"

_LEGACY_ID_RE = re.compile(r"^[A-Z]\d{2}-\d{4,5}$")
_MODERN_ID_RE = re.compile(r"^\d{4}\.[a-z0-9][a-z0-9-]*\.\d+$", re.IGNORECASE)


def normalize_identifier(identifier: str) -> str:
    """Normalize an ACL Anthology paper id, dropping a trailing format suffix."""
    value = identifier.strip().strip("/")
    for suffix in (".bib", ".pdf", ".abstract"):
        value = value.removesuffix(suffix)
    if _LEGACY_ID_RE.match(value.upper()) is not None:
        return value.upper()
    if _MODERN_ID_RE.match(value) is not None:
        return value.lower()
    raise ValueError(f"Malformed ACL Anthology id: {identifier!r}")


def record_url(identifier: str) -> str:
    """Return the canonical ACL Anthology paper URL."""
    return f"{BASE_URL}/{normalize_identifier(identifier)}/"


def request_url(identifier: str) -> str:
    """Return the ACL Anthology BibTeX URL for one paper."""
    return f"{BASE_URL}/{quote(normalize_identifier(identifier), safe='.')}.bib"


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an ACL Anthology paper."""
    del dialect
    normalized = normalize_identifier(identifier)
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(
            request_url(normalized),
            accept="application/x-bibtex",
            label=f"ACL Anthology {normalized}",
        )
    )
    return bibtex_metadata(
        text,
        provider=PROVIDER_NAME,
        identifier_kind="acl",
        identifier=normalized,
        url=record_url(normalized),
    )
