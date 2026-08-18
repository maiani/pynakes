"""Publisher URL rules that expose a canonical identifier in their path.

Most publisher article URLs embed the DOI, so they need a rule here rather than
a provider module. Two kinds of exception exist: ScienceDirect addresses
articles by Publisher Item Identifier, which the Elsevier provider maps to a
DOI, and some platforms publish article URLs that carry no recoverable
identifier at all. The latter are listed in :data:`UNRESOLVABLE_URL_HINTS` so
that `ref import` can say what to do instead of failing generically.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from pynakes._identifiers import normalize_doi, normalize_pii
from pynakes.providers.url_resolvers.registry import URLRule


def _unquoted_doi(value: str) -> str:
    """Normalize a DOI taken from a URL path, decoding a percent-encoded slash."""
    return normalize_doi(unquote(value))


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
    URLRule(
        source="Springer Nature",
        kind="doi",
        pattern=re.compile(
            r"^https?://link\.springer\.com/"
            r"(?:article|chapter|book|protocol|referenceworkentry|"
            r"living-reference-work-entry)/"
            r"((?:10\.\d{4,9}|10\.\d{4,9}%2F)[^?#\s]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="Wiley Online Library",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:[\w-]+\.)*onlinelibrary\.wiley\.com/doi/"
            r"(?:abs/|full/|pdf/|epdf/|pdfdirect/)?"
            r"(10\.\d{4,9}/[^?#\s]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="PLOS",
        kind="doi",
        pattern=re.compile(
            r"^https?://journals\.plos\.org/[\w-]+/article(?:/[\w-]+)?"
            r"\?[^#]*\bid=(10\.\d{4,9}/[^&#\s]+)",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="IOPscience",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?iopscience\.iop\.org/article/"
            r"(10\.\d{4,9}/[^?#\s]+?)"
            r"(?:/(?:meta|pdf|fulltext|references|citations))?/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="SciPost",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?scipost\.org/(10\.\d{4,9}/[^?#\s]+?)"
            r"(?:/pdf)?/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="SciPost",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?scipost\.org/(SciPost[A-Za-z]*\.[\d.]+?)"
            r"(?:/pdf)?/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: f"10.21468/{match.group(1)}",
        normalize=normalize_doi,
    ),
    URLRule(
        source="JSTOR",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?jstor\.org/stable/(10\.\d{4,9}/[^?#\s]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="JSTOR",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?jstor\.org/stable/(\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: f"10.2307/{match.group(1)}",
        normalize=normalize_doi,
    ),
    URLRule(
        source="AIP Publishing",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:aip|pubs)\.scitation\.org/doi/"
            r"(?:abs/|full/|pdf/|epdf/|figure/)?"
            r"(10\.\d{4,9}/[^?#\s]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="ACM Digital Library",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?dl\.acm\.org/doi/"
            r"(?:abs/|full/|pdf/|epdf/|fullHtml/)?"
            r"(10\.\d{4,9}/[^?#\s]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="American Chemical Society",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?pubs\.acs\.org/doi/"
            r"(?:abs/|full/|pdf/|epdf/|book/)?"
            r"(10\.\d{4,9}/[^?#\s]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_unquoted_doi,
    ),
    URLRule(
        source="Royal Society of Chemistry",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?pubs\.rsc\.org/en/content/article"
            r"(?:landing|html|pdf)/\d{4}/[a-z0-9]+/"
            r"([^/?#\s]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: f"10.1039/{match.group(1)}",
        normalize=normalize_doi,
    ),
    URLRule(
        source="Project Euclid",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?projecteuclid\.org/journals/[\w-]+/"
            r"volume-[\w-]+/issue-[\w-]+/[^/?#\s]+/"
            r"(10\.\d{4,9}/[^?#\s]+?)(?:\.(?:full|short))?/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=normalize_doi,
    ),
    URLRule(
        source="Elsevier ScienceDirect",
        kind="pii",
        pattern=re.compile(
            r"^https?://(?:www\.)?(?:sciencedirect\.com/science/article(?:/abs)?"
            r"|linkinghub\.elsevier\.com/retrieve)"
            r"/pii/([0-9SXx()\-]+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=normalize_pii,
    ),
)


# Hosts whose article URLs are recognizable but carry no recoverable
# identifier. Consulted only after every rule has failed, so a host listed here
# can still have working rules for its other URL shapes.
UNRESOLVABLE_URL_HINTS = (
    (
        re.compile(r"^https?://pubs\.aip\.org/", re.IGNORECASE),
        "AIP article URLs on pubs.aip.org address articles by volume, issue, and "
        "an internal article id rather than by DOI, and the page states its DOI "
        "only behind a browser challenge; import the DOI shown on the article "
        "page instead",
    ),
    (
        re.compile(r"^https?://(?:www\.)?iopscience\.iop\.org/", re.IGNORECASE),
        "only IOPscience article URLs of the form "
        "iopscience.iop.org/article/<doi> carry a DOI; import the DOI shown on "
        "the article page instead",
    ),
    (
        re.compile(r"^https?://(?:www\.)?jstor\.org/", re.IGNORECASE),
        "only JSTOR stable URLs whose id is numeric or already a DOI can be "
        "mapped to a DOI; import the DOI shown on the item page instead",
    ),
    (
        re.compile(r"^https?://(?:www\.)?ieeexplore\.ieee\.org/", re.IGNORECASE),
        "IEEE Xplore article URLs address articles by an internal document "
        "number rather than by DOI, and resolving it requires IEEE's metadata "
        "API and a registered key; import the DOI shown on the article page "
        "instead",
    ),
)


def url_resolution_hint(url: str) -> str | None:
    """Return advice for a recognized URL that carries no usable identifier."""
    value = url.strip()
    for pattern, hint in UNRESOLVABLE_URL_HINTS:
        if pattern.match(value):
            return hint
    return None


def extract_publisher_doi(url: str) -> str | None:
    """Extract a DOI from a supported publisher URL.

    Rules that resolve to another identifier kind (such as an Elsevier PII) are
    skipped: this helper is the DOI-only entry point used by asset resolution.
    """
    for rule in PUBLISHER_URL_RULES:
        if rule.kind != "doi":
            continue
        resolved = rule.resolve(url)
        if resolved is not None:
            return resolved.identifier
    return None
