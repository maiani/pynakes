"""Ordered URL recognition for supported reference sources."""

from pynakes.providers.url_resolvers.identifiers import IDENTIFIER_URL_RULES
from pynakes.providers.url_resolvers.publishers import (
    PUBLISHER_URL_RULES,
    extract_publisher_doi,
)
from pynakes.providers.url_resolvers.registry import ResolvedURL, URLRule, resolve_url

DEFAULT_URL_RULES = (*IDENTIFIER_URL_RULES, *PUBLISHER_URL_RULES)


def resolve_reference_url(value: str) -> ResolvedURL | None:
    """Resolve a supported reference URL to its canonical identifier."""
    return resolve_url(value, DEFAULT_URL_RULES)


__all__ = [
    "DEFAULT_URL_RULES",
    "PUBLISHER_URL_RULES",
    "ResolvedURL",
    "URLRule",
    "extract_publisher_doi",
    "resolve_reference_url",
    "resolve_url",
]
