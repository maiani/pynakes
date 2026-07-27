"""Publisher URL rules that expose a canonical DOI in their path."""

from __future__ import annotations

import re

from pynakes._identifiers import normalize_doi
from pynakes.providers.url_resolvers.registry import URLRule

PUBLISHER_URL_RULES = (
    URLRule(
        source="Nature",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?nature\.com/articles/([^/?#\s]+)",
            re.IGNORECASE,
        ),
        extract=lambda match: f"10.1038/{match.group(1)}",
        normalize=normalize_doi,
    ),
    URLRule(
        source="American Physical Society",
        kind="doi",
        pattern=re.compile(
            r"^https?://journals\.aps\.org/\w+/(?:abstract|pdf)/(10\.\d{4,9}/\S+?)"
            r"(?:[/?#]|$)",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=normalize_doi,
    ),
)


def extract_publisher_doi(url: str) -> str | None:
    """Extract a DOI from a supported publisher URL."""
    for rule in PUBLISHER_URL_RULES:
        resolved = rule.resolve(url)
        if resolved is not None:
            return resolved.identifier
    return None
