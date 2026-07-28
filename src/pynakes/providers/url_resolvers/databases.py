"""URL rules for bibliographic databases that publish their own BibTeX."""

from __future__ import annotations

import re

from pynakes.providers.metadata import acl_anthology, dblp, inspire
from pynakes.providers.url_resolvers.registry import URLRule

DATABASE_URL_RULES = (
    URLRule(
        source="INSPIRE-HEP",
        kind="inspire",
        pattern=re.compile(
            r"^https?://(?:www\.)?inspirehep\.net/(?:api/)?literature/(\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=inspire.normalize_identifier,
    ),
    URLRule(
        source="DBLP",
        kind="dblp",
        pattern=re.compile(
            r"^https?://(?:www\.)?dblp(?:\.uni-trier)?\.(?:org|de)/rec/"
            r"([^?#\s]+?)(?:\.(?:html|bib|xml|rdf))?/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=dblp.normalize_identifier,
    ),
    URLRule(
        source="ACL Anthology",
        kind="acl",
        pattern=re.compile(
            r"^https?://(?:www\.)?(?:aclanthology\.org|aclweb\.org/anthology)/"
            r"([^/?#\s]+?)(?:\.(?:bib|pdf))?/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=acl_anthology.normalize_identifier,
    ),
)
