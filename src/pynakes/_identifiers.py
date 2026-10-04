"""Shared DOI, arXiv, ISBN, and PII identifier normalization helpers."""

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

_ISBN_LABEL_RE = re.compile(r"^isbn(?:-1[03])?:\s*", re.IGNORECASE)
_ISBN_SEPARATOR_RE = re.compile(r"[\s-]+")
_ISBN10_RE = re.compile(r"^\d{9}[\dX]$")
_ISBN13_RE = re.compile(r"^97[89]\d{10}$")

_PII_LABEL_RE = re.compile(r"^pii:\s*", re.IGNORECASE)
_PII_SEPARATOR_RE = re.compile(r"[\s()-]+")
_PII_RE = re.compile(r"^S[0-9X]{16}$", re.IGNORECASE)


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


#: arXiv registers every submission with DataCite under this DOI prefix.
ARXIV_DOI_PREFIX = "10.48550/arXiv."


def arxiv_doi(identifier: str) -> str:
    """Return the DataCite DOI arXiv registers for ``identifier``.

    A derivation rather than a lookup: no network access, and the result is the
    same string arXiv's own landing page advertises.
    """
    return f"{ARXIV_DOI_PREFIX}{identifier}"


def arxiv_id_from_doi(value: str) -> str | None:
    """Return the arXiv id an arXiv DataCite DOI encodes, or ``None``."""
    doi = value.strip()
    if not doi.lower().startswith(ARXIV_DOI_PREFIX.lower()):
        return None
    return normalize_arxiv(doi[len(ARXIV_DOI_PREFIX) :])


def is_arxiv_doi(value: str) -> bool:
    """Return whether ``value`` (a DOI or DOI URL) is one arXiv registered."""
    try:
        return normalize_doi(value).lower().startswith(ARXIV_DOI_PREFIX.lower())
    except ValueError:
        return False


def looks_like_arxiv_id(value: str) -> bool:
    """Return whether ``value`` has a recognized bare arXiv-id shape."""
    return bool(_ARXIV_NEW_RE.match(value) or _ARXIV_OLD_RE.match(value))


def normalize_isbn(value: str) -> str:
    """Normalize an ISBN-10 or ISBN-13 to its compact, checksum-valid form.

    Accepts hyphenated and spaced forms and an optional ``ISBN:`` label. The
    returned value keeps the supplied ISBN length (10 or 13) with separators
    removed and a trailing check character uppercased; no ISBN-10 to ISBN-13
    conversion is performed, so the identifier stays the one the caller used.
    """
    cleaned = _ISBN_LABEL_RE.sub("", value.strip().strip("{}<>")).strip()
    cleaned = _ISBN_SEPARATOR_RE.sub("", cleaned).upper()
    if _ISBN13_RE.match(cleaned) and _isbn13_check_digit(cleaned[:12]) == cleaned[12]:
        return cleaned
    if _ISBN10_RE.match(cleaned) and _isbn10_check_digit(cleaned[:9]) == cleaned[9]:
        return cleaned
    raise ValueError(f"Malformed ISBN: {value!r}")


def looks_like_isbn(value: str) -> bool:
    """Return whether ``value`` is unambiguously a bare ISBN.

    Deliberately conservative: only separated forms and the ``978``/``979``
    ISBN-13 prefixes are recognized without a label, because a bare run of ten
    digits is indistinguishable from other numeric record ids. An unseparated
    ISBN-10 needs the explicit ``ISBN:`` prefix.
    """
    cleaned = value.strip().strip("{}<>")
    if not cleaned:
        return False
    try:
        normalized = normalize_isbn(cleaned)
    except ValueError:
        return False
    return bool(_ISBN_SEPARATOR_RE.search(cleaned)) or len(normalized) == 13


def _isbn10_check_digit(body: str) -> str:
    total = sum((10 - index) * int(digit) for index, digit in enumerate(body))
    remainder = (11 - total % 11) % 11
    return "X" if remainder == 10 else str(remainder)


def _isbn13_check_digit(body: str) -> str:
    total = sum((3 if index % 2 else 1) * int(digit) for index, digit in enumerate(body))
    return str((10 - total % 10) % 10)


def normalize_pii(value: str) -> str:
    """Normalize an Elsevier Publisher Item Identifier to its compact form.

    Both the punctuated journal form (``S0000-0000(00)00000-0``) and the
    unpunctuated form used in ScienceDirect URLs are accepted; separators are
    removed and the result uppercased. A PII is not resolvable on its own — the
    Elsevier provider maps it to a DOI before fetching metadata.
    """
    cleaned = _PII_LABEL_RE.sub("", value.strip().strip("{}<>")).strip()
    cleaned = _PII_SEPARATOR_RE.sub("", cleaned).upper()
    if not _PII_RE.match(cleaned):
        raise ValueError(f"Malformed Elsevier PII: {value!r}")
    return cleaned
