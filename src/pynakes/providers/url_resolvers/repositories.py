"""URL rules for scholarly repositories and preprint archives."""

from __future__ import annotations

import re

from pynakes._identifiers import normalize_arxiv, normalize_doi
from pynakes.providers.metadata import iacr
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


def _rfc_doi(number: str) -> str:
    """Build an RFC's DOI from its number, unpadded (see :mod:`pynakes.importer`).

    ``10.17487/rfc<N>`` is the DOI registered with Crossref for RFC N. The
    registered form is *not* zero-padded — a padded form such as
    ``10.17487/RFC0791`` is only a 301 alias to the unpadded DOI, and for the
    lowest-numbered RFCs (e.g. RFC 20) the padded form does not resolve at
    all — so the number is normalized with ``int()`` to strip any padding a
    caller supplied.
    """
    return normalize_doi(f"10.17487/rfc{int(number)}")


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
    URLRule(
        source="IACR ePrint Archive",
        kind="iacr",
        pattern=re.compile(
            r"^https?://(?:www\.)?eprint\.iacr\.org/(\d{4}/\d+)(?:\.pdf)?/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=iacr.normalize_identifier,
    ),
    # RFCs are standards-track documents archived by the RFC Editor — a
    # document repository in the same sense as arXiv or the ePrint Archive
    # above, not a commercial publisher (hence not in publishers.py) and not
    # a third-party metadata index describing someone else's publication
    # (hence not in databases.py). Every RFC's DOI is deterministic, so no
    # provider module or registry entry is needed: these rules resolve
    # straight to kind="doi".
    URLRule(
        source="RFC Editor",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?datatracker\.ietf\.org/doc/(?:html/)?rfc(\d+)/?"
            r"(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_rfc_doi,
    ),
    URLRule(
        source="RFC Editor",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?rfc-editor\.org/(?:info|rfc)/rfc(\d+)(?:\.(?:txt|html))?"
            r"/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_rfc_doi,
    ),
    URLRule(
        source="RFC Editor",
        kind="doi",
        pattern=re.compile(
            r"^https?://(?:www\.)?tools\.ietf\.org/html/rfc(\d+)/?(?:[?#].*)?$",
            re.IGNORECASE,
        ),
        extract=lambda match: match.group(1),
        normalize=_rfc_doi,
    ),
)
