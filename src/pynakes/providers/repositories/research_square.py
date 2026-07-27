"""Research Square import from landing-page citation metadata."""

from __future__ import annotations

import re
from collections.abc import Callable

from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories._landing_page import fetch_landing_metadata

RawFetcher = Callable[[str], str]
_RECORD_ID = re.compile(r"^rs-\d+$", re.IGNORECASE)


def normalize_identifier(identifier: str) -> str:
    """Normalize a Research Square manuscript id, dropping a version."""
    value = identifier.strip().lower()
    value = re.sub(r"/v\d+$", "", value)
    if _RECORD_ID.fullmatch(value) is None:
        raise ValueError(f"Malformed Research Square manuscript id: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return the canonical Research Square landing page."""
    return f"https://www.researchsquare.com/article/{normalize_identifier(identifier)}"


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize a Research Square preprint."""
    normalized = normalize_identifier(identifier)
    return fetch_landing_metadata(
        normalized,
        provider="Research Square",
        identifier_kind="research_square",
        dialect=dialect,
        url=record_url(normalized),
        fetcher=fetcher,
        fields={"researchsquare": normalized, "archivePrefix": "Research Square"},
    )
