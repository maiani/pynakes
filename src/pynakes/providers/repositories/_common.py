"""Shared normalization helpers for repository import clients."""

from __future__ import annotations

import html
import re
from datetime import datetime
from html.parser import HTMLParser

from pynakes._calendar import MONTH_NUM_TO_ABBR
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.records import ReferenceMetadata


def clean_text(value: object) -> str:
    """Return collapsed, HTML-unescaped text for a provider value."""
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(value).split())


def person_name(value: object) -> str:
    """Return a display name from a string or common person-object shapes."""
    if isinstance(value, str):
        return clean_text(value)
    if not isinstance(value, dict):
        return ""
    given = clean_text(
        value.get("given")
        or value.get("firstName")
        or value.get("first_name")
        or value.get("given_name")
    )
    family = clean_text(
        value.get("family")
        or value.get("lastName")
        or value.get("last_name")
        or value.get("family_name")
    )
    if given or family:
        return " ".join(part for part in (given, family) if part)
    return clean_text(value.get("name") or value.get("fullName") or value.get("full_name"))


def add_date_fields(fields: dict[str, str], date: str, dialect: str) -> None:
    """Add an ISO-like date using fields appropriate for ``dialect``."""
    normalized = _normalize_date(clean_text(date))
    match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$", normalized)
    if match is None:
        return
    year, month, _day = match.groups()
    if dialect.lower() == "biblatex":
        fields["date"] = normalized
    else:
        fields["year"] = year
        if month in MONTH_NUM_TO_ABBR:
            fields["month"] = MONTH_NUM_TO_ABBR[month]


def _normalize_date(value: str) -> str:
    value = value[:10] if re.match(r"^\d{4}-\d{2}-\d{2}T", value) else value
    value = value.replace("/", "-")
    if re.fullmatch(r"\d{4}(?:-\d{1,2}(?:-\d{1,2})?)?", value):
        return "-".join(
            part.zfill(2) if index else part for index, part in enumerate(value.split("-"))
        )
    for pattern in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


def repository_metadata(
    *,
    provider: str,
    identifier_kind: str,
    identifier: str,
    dialect: str,
    title: str,
    authors: list[str] | None = None,
    published: str = "",
    abstract: str = "",
    url: str = "",
    doi: str = "",
    entry_type: str | None = None,
    fields: dict[str, str] | None = None,
    identifiers: dict[str, str] | None = None,
) -> ReferenceMetadata:
    """Build a normalized record from common repository metadata."""
    normalized_fields = dict(fields or {})
    title = clean_text(title)
    if not title:
        raise ProviderFetchError(f"{provider} returned no title for {identifier!r}")
    normalized_fields["title"] = title
    clean_authors = [name for value in (authors or []) if (name := clean_text(value))]
    if clean_authors:
        normalized_fields["author"] = " and ".join(clean_authors)
    add_date_fields(normalized_fields, published, dialect)
    if abstract := clean_text(abstract):
        normalized_fields["abstract"] = abstract
    if url := clean_text(url):
        normalized_fields["url"] = url
    if doi := clean_text(doi):
        normalized_fields["doi"] = doi

    normalized_identifiers = {identifier_kind: identifier}
    normalized_identifiers.update(identifiers or {})
    if doi:
        normalized_identifiers["doi"] = doi
    return ReferenceMetadata(
        provider=provider,
        entry_type=entry_type or ("online" if dialect.lower() == "biblatex" else "misc"),
        fields=normalized_fields,
        identifiers=normalized_identifiers,
    )


class _CitationMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {name.lower(): value for name, value in attrs if value is not None}
        key = values.get("name") or values.get("property")
        content = values.get("content")
        if key and content:
            self.values.setdefault(key.lower(), []).append(clean_text(content))


def metadata_from_citation_html(
    text: str,
    *,
    provider: str,
    identifier_kind: str,
    identifier: str,
    dialect: str,
    canonical_url: str,
    extra_fields: dict[str, str] | None = None,
    entry_type: str | None = None,
) -> ReferenceMetadata:
    """Parse standard ``citation_*``/Dublin Core metadata from a landing page."""
    parser = _CitationMetaParser()
    parser.feed(text)
    values = parser.values

    def first(*names: str) -> str:
        for name in names:
            candidates = values.get(name.lower(), [])
            if candidates and candidates[0]:
                return candidates[0]
        return ""

    authors = values.get("citation_author", [])
    if not authors:
        authors = values.get("dc.creator", []) or values.get("dc.creator.personalname", [])
    doi = first("citation_doi", "dc.identifier.doi")
    fields = dict(extra_fields or {})
    report_number = first("citation_technical_report_number")
    if report_number:
        fields["number"] = report_number
    return repository_metadata(
        provider=provider,
        identifier_kind=identifier_kind,
        identifier=identifier,
        dialect=dialect,
        title=first("citation_title", "dc.title", "og:title"),
        authors=authors,
        published=first("citation_publication_date", "citation_date", "dc.date"),
        abstract=first("citation_abstract", "dc.description", "description"),
        url=first("citation_public_url", "og:url") or canonical_url,
        doi=doi,
        entry_type=entry_type,
        fields=fields,
    )
