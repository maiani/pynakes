"""Internal factory for repository clients backed by citation meta tags."""

from __future__ import annotations

from collections.abc import Callable

from pynakes.providers._http import fetch_text
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories._common import metadata_from_citation_html

RawFetcher = Callable[[str], str]


def fetch_landing_metadata(
    identifier: str,
    *,
    provider: str,
    identifier_kind: str,
    dialect: str,
    url: str,
    fetcher: RawFetcher | None,
    fields: dict[str, str] | None = None,
    entry_type: str | None = None,
) -> ReferenceMetadata:
    """Fetch and parse one repository landing page."""
    text = (
        fetcher(identifier)
        if fetcher is not None
        else fetch_text(url, accept="text/html", label=f"{provider} {identifier}")
    )
    return metadata_from_citation_html(
        text,
        provider=provider,
        identifier_kind=identifier_kind,
        identifier=identifier,
        dialect=dialect,
        canonical_url=url,
        extra_fields=fields,
        entry_type=entry_type,
    )
