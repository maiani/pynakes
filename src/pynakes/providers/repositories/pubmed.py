"""PubMed and PubMed Central metadata import through NCBI EFetch."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from urllib.parse import urlencode

from pynakes.providers._common import clean_text, person_name, repository_metadata
from pynakes.providers._http import ProviderFetchError, fetch_text
from pynakes.providers.records import ReferenceMetadata

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
RawFetcher = Callable[[str], str]


def canonical_identifier(identifier: str, *, kind: str) -> str:
    """Normalize a PMID or PMCID."""
    value = identifier.strip()
    if kind == "pmcid":
        value = value.upper()
        if not value.startswith("PMC"):
            value = f"PMC{value}"
    elif not value.isdigit():
        raise ValueError(f"Malformed PMID: {identifier!r}")
    if kind == "pmcid" and (not value[3:].isdigit()):
        raise ValueError(f"Malformed PMCID: {identifier!r}")
    return value


def record_url(identifier: str, *, kind: str) -> str:
    """Return the public record URL."""
    if kind == "pmcid":
        return f"https://pmc.ncbi.nlm.nih.gov/articles/{identifier}/"
    return f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/"


def efetch_url(identifier: str, *, kind: str) -> str:
    """Return the EFetch XML endpoint for an identifier."""
    database = "pmc" if kind == "pmcid" else "pubmed"
    return f"{EFETCH_URL}?{urlencode({'db': database, 'id': identifier, 'retmode': 'xml'})}"


def _text(element: ET.Element | None) -> str:
    return clean_text("".join(element.itertext())) if element is not None else ""


def _pubmed_metadata(root: ET.Element, identifier: str, dialect: str) -> ReferenceMetadata:
    article = root.find(".//PubmedArticle")
    if article is None:
        raise ProviderFetchError(f"PubMed returned no entry for {identifier!r}")
    citation = article.find("./MedlineCitation")
    journal_article = article.find("./MedlineCitation/Article")
    if citation is None or journal_article is None:
        raise ProviderFetchError(f"PubMed returned an incomplete entry for {identifier!r}")
    authors = []
    for author in journal_article.findall("./AuthorList/Author"):
        collective = _text(author.find("./CollectiveName"))
        name = collective or person_name(
            {
                "given": _text(author.find("./ForeName")),
                "family": _text(author.find("./LastName")),
            }
        )
        if name:
            authors.append(name)
    journal = _text(journal_article.find("./Journal/Title"))
    article_date = journal_article.find("./ArticleDate")
    date = ""
    if article_date is not None:
        date = "-".join(
            part
            for part in (
                _text(article_date.find("./Year")),
                _text(article_date.find("./Month")),
                _text(article_date.find("./Day")),
            )
            if part
        )
    if not date:
        pub_date = journal_article.find("./Journal/JournalIssue/PubDate")
        if pub_date is not None:
            year = _text(pub_date.find("./Year"))
            month = _text(pub_date.find("./Month"))
            day = _text(pub_date.find("./Day"))
            date = "-".join(part for part in (year, month, day) if part)
    identifiers: dict[str, str] = {"pmid": identifier}
    doi = ""
    pmcid = ""
    for article_id in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        id_type = (article_id.get("IdType") or "").lower()
        value = _text(article_id)
        if id_type == "doi":
            doi = value
        elif id_type == "pmc":
            pmcid = value
            identifiers["pmcid"] = value
    fields: dict[str, str] = {"pmid": identifier}
    if pmcid:
        fields["pmcid"] = pmcid
    if journal:
        fields["journal"] = journal
    volume = _text(journal_article.find("./Journal/JournalIssue/Volume"))
    issue = _text(journal_article.find("./Journal/JournalIssue/Issue"))
    pages = _text(journal_article.find("./Pagination/MedlinePgn"))
    for name, value in (("volume", volume), ("number", issue), ("pages", pages)):
        if value:
            fields[name] = value
    abstract = " ".join(_text(part) for part in journal_article.findall("./Abstract/AbstractText"))
    return repository_metadata(
        provider="PubMed",
        identifier_kind="pmid",
        identifier=identifier,
        dialect=dialect,
        title=_text(journal_article.find("./ArticleTitle")),
        authors=authors,
        published=date,
        abstract=abstract,
        url=record_url(identifier, kind="pmid"),
        doi=doi,
        entry_type="article",
        fields=fields,
        identifiers=identifiers,
    )


def _pmc_metadata(root: ET.Element, identifier: str, dialect: str) -> ReferenceMetadata:
    article = root.find(".//article")
    if article is None:
        raise ProviderFetchError(f"PubMed Central returned no entry for {identifier!r}")
    meta = article.find(".//article-meta")
    if meta is None:
        raise ProviderFetchError(f"PubMed Central returned an incomplete entry for {identifier!r}")
    authors = []
    for contrib in meta.findall("./contrib-group/contrib[@contrib-type='author']"):
        collective = _text(contrib.find("./collab"))
        name_node = contrib.find("./name")
        name = collective
        if not name and name_node is not None:
            name = person_name(
                {
                    "given": _text(name_node.find("./given-names")),
                    "family": _text(name_node.find("./surname")),
                }
            )
        if name:
            authors.append(name)
    identifiers: dict[str, str] = {"pmcid": identifier}
    doi = ""
    pmid = ""
    for article_id in meta.findall("./article-id"):
        id_type = (article_id.get("pub-id-type") or "").lower()
        value = _text(article_id)
        if id_type == "doi":
            doi = value
        elif id_type == "pmid":
            pmid = value
            identifiers["pmid"] = value
    fields: dict[str, str] = {"pmcid": identifier}
    if pmid:
        fields["pmid"] = pmid
    journal = _text(article.find(".//journal-meta/journal-title"))
    if journal:
        fields["journal"] = journal
    pub_date = meta.find("./pub-date[@pub-type='epub']")
    if pub_date is None:
        pub_date = meta.find("./pub-date")
    date = ""
    if pub_date is not None:
        date = "-".join(
            part
            for part in (
                _text(pub_date.find("./year")),
                _text(pub_date.find("./month")),
                _text(pub_date.find("./day")),
            )
            if part
        )
    return repository_metadata(
        provider="PubMed Central",
        identifier_kind="pmcid",
        identifier=identifier,
        dialect=dialect,
        title=_text(meta.find("./title-group/article-title")),
        authors=authors,
        published=date,
        abstract=_text(meta.find("./abstract")),
        url=record_url(identifier, kind="pmcid"),
        doi=doi,
        entry_type="article",
        fields=fields,
        identifiers=identifiers,
    )


def parse_xml(text: str, identifier: str, *, kind: str, dialect: str) -> ReferenceMetadata:
    """Parse an NCBI EFetch response."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProviderFetchError(f"NCBI returned invalid XML for {identifier!r}") from exc
    if kind == "pmcid":
        return _pmc_metadata(root, identifier, dialect)
    return _pubmed_metadata(root, identifier, dialect)


def fetch_metadata(
    identifier: str,
    *,
    kind: str,
    dialect: str = "bibtex",
    fetcher: RawFetcher | None = None,
) -> ReferenceMetadata:
    """Fetch and normalize PubMed or PubMed Central metadata."""
    normalized = canonical_identifier(identifier, kind=kind)
    text = (
        fetcher(normalized)
        if fetcher is not None
        else fetch_text(
            efetch_url(normalized, kind=kind),
            accept="application/xml",
            label=f"{kind.upper()} {normalized}",
        )
    )
    return parse_xml(text, normalized, kind=kind, dialect=dialect)
