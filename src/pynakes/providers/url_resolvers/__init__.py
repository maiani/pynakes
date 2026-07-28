"""Ordered URL recognition for supported reference sources."""

from pynakes.providers.url_resolvers.catalogues import CATALOGUE_URL_RULES
from pynakes.providers.url_resolvers.databases import DATABASE_URL_RULES
from pynakes.providers.url_resolvers.identifiers import IDENTIFIER_URL_RULES
from pynakes.providers.url_resolvers.publishers import (
    PUBLISHER_URL_RULES,
    UNRESOLVABLE_URL_HINTS,
    extract_publisher_doi,
    url_resolution_hint,
)
from pynakes.providers.url_resolvers.registry import ResolvedURL, URLRule, resolve_url
from pynakes.providers.url_resolvers.repositories import REPOSITORY_URL_RULES

DEFAULT_URL_RULES = (
    *IDENTIFIER_URL_RULES,
    *REPOSITORY_URL_RULES,
    *DATABASE_URL_RULES,
    *PUBLISHER_URL_RULES,
    *CATALOGUE_URL_RULES,
)


def resolve_reference_url(value: str) -> ResolvedURL | None:
    """Resolve a supported reference URL to its canonical identifier."""
    return resolve_url(value, DEFAULT_URL_RULES)


__all__ = [
    "CATALOGUE_URL_RULES",
    "DATABASE_URL_RULES",
    "DEFAULT_URL_RULES",
    "PUBLISHER_URL_RULES",
    "REPOSITORY_URL_RULES",
    "UNRESOLVABLE_URL_HINTS",
    "ResolvedURL",
    "URLRule",
    "extract_publisher_doi",
    "resolve_reference_url",
    "resolve_url",
    "url_resolution_hint",
]
