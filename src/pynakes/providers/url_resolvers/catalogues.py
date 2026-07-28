"""URL rules for book catalogues addressed by ISBN."""

from __future__ import annotations

import re

from pynakes._identifiers import normalize_isbn
from pynakes.providers.url_resolvers.registry import URLRule

CATALOGUE_URL_RULES = (
    URLRule(
        source="Open Library",
        kind="isbn",
        pattern=re.compile(
            r"^https?://(?:www\.)?openlibrary\.org/isbn/([0-9Xx\-]+)(?:\.json)?/?"
            r"(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=normalize_isbn,
    ),
)
