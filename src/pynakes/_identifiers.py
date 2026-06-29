"""Shared DOI and arXiv identifier normalization helpers."""

import re

_DOI_URL_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_DOI_LABEL_RE = re.compile(r"^doi:\s*", re.IGNORECASE)
_DOI_IN_TEXT_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)(10\.\d{4,9}/\S+)",
    re.IGNORECASE,
)

_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#\s]+)", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.IGNORECASE)
_ARXIV_NEW_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE)
_ARXIV_OLD_RE = re.compile(r"^[a-z][a-z-]+(\.[a-z]{2})?/\d{7}(v\d+)?$", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    """Normalize a DOI or DOI URL to the canonical bare DOI string."""
    doi = value.strip()
    doi = _DOI_URL_PREFIX_RE.sub("", doi)
    doi = _DOI_LABEL_RE.sub("", doi).strip()
    doi = doi.strip("<> \t\r\n")
    if not _DOI_RE.match(doi):
        raise ValueError(f"Malformed DOI: {value!r}")
    return doi


def canonical_doi(value: str) -> str:
    """Return a lowercase DOI string suitable for equality checks."""
    return normalize_doi(value).lower()


def doi_from_text(value: str) -> str | None:
    """Return the first normalized DOI embedded in ``value``, if present."""
    match = _DOI_IN_TEXT_RE.search(value)
    if match is None:
        return None
    try:
        return normalize_doi(match.group(1).rstrip(").,;"))
    except ValueError:
        return None


def normalize_arxiv(value: str) -> str | None:
    """Normalize an arXiv id/URL to its bare, version-stripped, lowercase form."""
    cleaned = value.strip().strip("{}<>")
    cleaned = re.sub(r"^arxiv:\s*", "", cleaned, flags=re.IGNORECASE)
    match = _ARXIV_URL_RE.search(cleaned)
    if match:
        cleaned = match.group(1)
    cleaned = cleaned.removesuffix(".pdf")
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned)
    cleaned = cleaned.strip("/")
    return cleaned.lower() or None


def arxiv_id_from_text(value: str) -> str | None:
    """Return the normalized arXiv id embedded in ``value``, if present."""
    match = _ARXIV_URL_RE.search(value)
    if match is None:
        return None
    return normalize_arxiv(match.group(1))


def looks_like_arxiv_id(value: str) -> bool:
    """Return whether ``value`` has a recognized bare arXiv-id shape."""
    return bool(_ARXIV_NEW_RE.match(value) or _ARXIV_OLD_RE.match(value))
