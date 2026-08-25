"""American Physical Society Harvest API metadata provider.

APS documents Harvest as the supported source of journal metadata.  Access can
be granted by the caller's institution IP range, or by an APS-issued bearer
token; this module intentionally does not query APS's Cloudflare-protected
website export endpoint.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._calendar import MONTH_NUM_TO_ABBR
from pynakes._identifiers import normalize_doi
from pynakes.model import BibEntry
from pynakes.providers._common import clean_text
from pynakes.providers._http import fetch_json
from pynakes.providers.preferred_metadata import preferred_metadata_provider
from pynakes.providers.records import ReferenceMetadata

PROVIDER_NAME = "American Physical Society"
API_URL = "https://harvest.aps.org/v2/journals/articles/"
ARTICLE_JSON = "application/vnd.tesseract.article+json"
TOKEN_ENV_VAR = "PYNAKES_APS_API_TOKEN"
RawFetcher = Callable[[str], dict | None]


def request_url(doi: str, journal: str | None) -> str | None:
    """Return Harvest's article endpoint for a known APS journal, or ``None``."""
    normalized = normalize_doi(doi)
    if not normalized.lower().startswith("10.1103/"):
        return None
    if preferred_metadata_provider(journal) != "aps":
        return None
    return f"{API_URL}{quote(normalized, safe='/')}"


def fetch_article(
    doi: str,
    journal: str | None,
    *,
    cache_file: str | Path | None = None,
    token: str | None = None,
) -> dict | None:
    """Fetch one APS record, using institutional IP access or an optional token."""
    normalized = normalize_doi(doi)
    url = request_url(normalized, journal)
    if url is None:
        return None
    access_token = token if token is not None else os.environ.get(TOKEN_ENV_VAR)
    headers = {"Accept": ARTICLE_JSON}
    if access_token and access_token.strip():
        headers["Authorization"] = f"Bearer {access_token.strip()}"
    response = fetch_json(
        url,
        namespace="aps-harvest",
        identifier=normalized,
        provider=PROVIDER_NAME,
        cache_file=cache_file,
        headers=headers,
    )
    if response is None:
        return None
    data = response.get("data")
    return data if isinstance(data, dict) else None


def fetch_metadata(
    doi: str,
    journal: str | None,
    *,
    cache_file: str | Path | None = None,
    token: str | None = None,
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata | None:
    """Return normalized APS metadata for one recognized APS journal article."""
    normalized = normalize_doi(doi)
    if request_url(normalized, journal) is None:
        return None
    article = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_article(normalized, journal, cache_file=cache_file, token=token)
    )
    if article is None:
        return None
    return _metadata_from_article(article, normalized)


def fetch_entry(
    doi: str, journal: str | None, *, cache_file: str | Path | None = None
) -> BibEntry | None:
    """Fetch one APS Harvest record as a :class:`~pynakes.model.BibEntry`.

    Returns ``None`` when the DOI/journal doesn't identify a Harvest-backed
    APS journal, or when Harvest has no record for it. Raises
    :class:`~pynakes.providers._http.ProviderFetchError` on transport failure.
    """
    normalized = normalize_doi(doi)
    metadata = fetch_metadata(normalized, journal, cache_file=cache_file)
    if metadata is None:
        return None
    return BibEntry(key=normalized, type=metadata.entry_type, fields=metadata.fields)


def _metadata_from_article(article: dict, doi: str) -> ReferenceMetadata:
    fields: dict[str, str] = {}
    _set_nested(fields, "title", article, "title", "value")
    _set_nested(fields, "journal", article, "journal", "abbreviatedName")
    _set_nested(fields, "volume", article, "volume", "number")
    _set_nested(fields, "number", article, "issue", "number")
    _set_value(fields, "pages", article.get("pageStart"))
    _set_value(fields, "numpages", article.get("numPages"))
    _set_nested(fields, "publisher", article, "publisher", "name")
    _set_date_fields(fields, article.get("date"))
    authors = _authors(article.get("authors"))
    if authors:
        fields["author"] = " and ".join(authors)
    identifiers = article.get("identifiers")
    article_doi = identifiers.get("doi") if isinstance(identifiers, dict) else doi
    _set_value(fields, "doi", article_doi)
    if fields.get("doi"):
        fields["url"] = f"https://link.aps.org/doi/{fields['doi']}"
    return ReferenceMetadata(
        provider=PROVIDER_NAME,
        entry_type="article",
        fields=fields,
        identifiers={"doi": fields.get("doi", doi)},
    )


def _set_nested(fields: dict[str, str], field: str, article: dict, *path: str) -> None:
    value: object = article
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    _set_value(fields, field, value)


def _set_value(fields: dict[str, str], field: str, value: object) -> None:
    clean = clean_text(str(value)) if isinstance(value, (str, int)) else ""
    if clean:
        fields[field] = clean


def _set_date_fields(fields: dict[str, str], value: object) -> None:
    date = clean_text(value)
    if len(date) < 4 or not date[:4].isdigit():
        return
    fields["year"] = date[:4]
    if len(date) >= 7:
        fields.update(month=MONTH_NUM_TO_ABBR.get(date[5:7], ""))
        if not fields["month"]:
            del fields["month"]


def _authors(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for author in value:
        if not isinstance(author, dict):
            continue
        surname = clean_text(author.get("surname"))
        firstname = clean_text(author.get("firstname"))
        name = (
            f"{surname}, {firstname}" if surname and firstname else clean_text(author.get("name"))
        )
        if name:
            names.append(name)
    return names
