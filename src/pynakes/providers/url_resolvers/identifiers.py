"""URL rules for identifier authorities."""

from __future__ import annotations

import re

from pynakes._identifiers import normalize_doi
from pynakes.providers.url_resolvers.registry import URLRule

IDENTIFIER_URL_RULES = (
    URLRule(
        source="doi.org",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:(?:dx|www)\.)?doi\.org/(10\.\d{4,9}/\S+?)(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=normalize_doi,
    ),
)
