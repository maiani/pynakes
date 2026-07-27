"""URL rules for scholarly repositories and preprint archives."""

from __future__ import annotations

import re

from pynakes._identifiers import normalize_arxiv, normalize_doi
from pynakes.providers.repositories import (
    chemrxiv,
    europe_pmc,
    hal,
    nber,
    osf,
    pubmed,
    research_square,
    ssrn,
    zenodo,
)
from pynakes.providers.url_resolvers.registry import URLRule


def _pmid(value: str) -> str:
    return pubmed.canonical_identifier(value, kind="pmid")


def _pmcid(value: str) -> str:
    return pubmed.canonical_identifier(value, kind="pmcid")


def _biorxiv_doi(value: str) -> str:
    value = re.sub(r"v\d+(?:\..*)?$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\.(?:full|abstract|article-info|figures-only)(?:\.pdf)?$", "", value)
    return normalize_doi(value)


REPOSITORY_URL_RULES = (
    URLRule(
        source="arXiv",
        kind="arxiv",
        pattern=re.compile(
            r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(.*?)(?:\.pdf)?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=normalize_arxiv,
    ),
    URLRule(
        source="PubMed",
        kind="pmid",
        pattern=re.compile(
            r"^https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/?(?:[?#].*)?$", re.IGNORECASE
        ),
        extract=lambda match: match.group(1),
        normalize=_pmid,
    ),
    URLRule(
        source="PubMed",
        kind="pmid",
        pattern=re.compile(
            r"^https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pubmed/(\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_pmid,
    ),
    URLRule(
        source="PubMed Central",
        kind="pmcid",
        pattern=re.compile(
            r"^https?://(?:www\.)?pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_pmcid,
    ),
    URLRule(
        source="PubMed Central",
        kind="pmcid",
        pattern=re.compile(
            r"^https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/(PMC\d+)/?"
            r"(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_pmcid,
    ),
    URLRule(
        source="Europe PMC",
        kind="europe_pmc",
        pattern=re.compile(
            r"^https?://(?:www\.)?europepmc\.org/article/([^/?#]+)/([^/?#]+)",
            re.IGNORECASE,
        ),
        extract=lambda match: f"{match.group(1)}:{match.group(2)}",
        normalize=europe_pmc.normalize_identifier,
    ),
    URLRule(
        source="SSRN",
        kind="ssrn",
        pattern=re.compile(
            r"^https?://papers\.ssrn\.com/(?:sol3/)?(?:papers\.cfm)?"
            r"(?:\?[^#]*\babstract_id=|/abstract=)(\d+)(?:[&#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=ssrn.normalize_identifier,
    ),
    URLRule(
        source="SSRN",
        kind="ssrn",
        pattern=re.compile(
            r"^https?://(?:www\.)?ssrn\.com/abstract=(\d+)(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=ssrn.normalize_identifier,
    ),
    URLRule(
        source="NBER",
        kind="nber",
        pattern=re.compile(
            r"^https?://(?:www\.)?nber\.org/papers/((?:w|t|h)\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=nber.normalize_identifier,
    ),
    URLRule(
        source="bioRxiv",
        kind="biorxiv",
        pattern=re.compile(
            r"^https?://(?:www\.)?biorxiv\.org/content/(10\.\d{4,9}/[^?#]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_biorxiv_doi,
    ),
    URLRule(
        source="medRxiv",
        kind="medrxiv",
        pattern=re.compile(
            r"^https?://(?:www\.)?medrxiv\.org/content/(10\.\d{4,9}/[^?#]+?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_biorxiv_doi,
    ),
    URLRule(
        source="Zenodo",
        kind="zenodo",
        pattern=re.compile(
            r"^https?://(?:www\.)?zenodo\.org/records?/(\d+)/?(?:[?#].*)?$", re.IGNORECASE
        ),
        extract=lambda match: match.group(1),
        normalize=zenodo.normalize_identifier,
    ),
    URLRule(
        source="OSF Preprints",
        kind="osf",
        pattern=re.compile(
            r"^https?://(?:www\.)?osf\.io/preprints/(?:[^/?#]+/)?([^/?#]+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=osf.normalize_identifier,
    ),
    URLRule(
        source="HAL",
        kind="hal",
        pattern=re.compile(
            r"^https?://(?:(?:[^./]+\.)?hal\.science|hal\.archives-ouvertes\.fr)/"
            r"((?:hal|inria|tel|pastel)-\d+(?:v\d+)?)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=hal.normalize_identifier,
    ),
    URLRule(
        source="ChemRxiv",
        kind="chemrxiv",
        pattern=re.compile(
            r"^https?://(?:(?:www\.)?chemrxiv\.org|www\.cambridge\.org)"
            r"/engage/chemrxiv/article-details/"
            r"([^/?#]+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=chemrxiv.normalize_identifier,
    ),
    URLRule(
        source="Research Square",
        kind="research_square",
        pattern=re.compile(
            r"^https?://(?:www\.)?researchsquare\.com/article/(rs-\d+(?:/v\d+)?)"
            r"/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=research_square.normalize_identifier,
    ),
)
