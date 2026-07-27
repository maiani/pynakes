"""NBER working-paper import from landing-page citation metadata."""

from __future__ import annotations

import re
from collections.abc import Callable

from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories._landing_page import fetch_landing_metadata

RawFetcher = Callable[[str], str]
_PAPER_ID = re.compile(r"^(?:w|t|h)\d+$", re.IGNORECASE)


def normalize_identifier(identifier: str) -> str:
    """Normalize an NBER working-paper id."""
    value = identifier.strip().lower()
    if _PAPER_ID.fullmatch(value) is None:
        raise ValueError(f"Malformed NBER working-paper id: {identifier!r}")
    return value


def record_url(identifier: str) -> str:
    """Return the canonical NBER working-paper URL."""
    return f"https://www.nber.org/papers/{normalize_identifier(identifier)}"


def fetch_metadata(
    identifier: str,
    *,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize an NBER working paper."""
    normalized = normalize_identifier(identifier)
    return fetch_landing_metadata(
        normalized,
        provider="NBER",
        identifier_kind="nber",
        dialect=dialect,
        url=record_url(normalized),
        fetcher=fetcher,
        fields={
            "number": normalized,
            "institution": "National Bureau of Economic Research",
            "type": "Working Paper",
        },
        entry_type="techreport",
    )
