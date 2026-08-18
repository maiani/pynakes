"""URL rules for bibliographic databases and metadata indexes."""

from __future__ import annotations

import re

from pynakes.providers.metadata import (
    acl_anthology,
    crossref,
    datacite,
    dblp,
    inspire,
    openalex,
    semantic_scholar,
    zbmath,
)
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
    URLRule(
        source="CrossRef",
        kind="crossref",
        pattern=re.compile(
            r"^https?://api\.crossref\.org/works/(.+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=crossref.normalize_identifier,
    ),
    URLRule(
        source="DataCite",
        kind="datacite",
        pattern=re.compile(
            r"^https?://api\.datacite\.org/dois/(.+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=datacite.normalize_identifier,
    ),
    URLRule(
        source="OpenAlex",
        kind="openalex",
        pattern=re.compile(
            r"^https?://(?:www\.)?(?:api\.)?openalex\.org/(?:works/)?([Ww]\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=openalex.normalize_identifier,
    ),
    URLRule(
        source="Semantic Scholar",
        kind="semantic_scholar",
        pattern=re.compile(
            r"^https?://(?:www\.)?semanticscholar\.org/paper/(?:[^/?#\s]+/)?([0-9a-f]{40})/?"
            r"(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=semantic_scholar.normalize_identifier,
    ),
    URLRule(
        source="zbMATH Open",
        kind="zbmath",
        pattern=re.compile(
            r"^https?://(?:www\.)?zbmath\.org/(\d{4}\.\d{5}|\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=zbmath.normalize_identifier,
    ),
)
