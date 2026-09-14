"""Explicit registry of metadata providers available to reference import."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pynakes.providers.metadata import (
    acl_anthology,
    crossref,
    datacite,
    dblp,
    doi,
    elsevier,
    iacr,
    inspire,
    openalex,
    openlibrary,
    semantic_scholar,
    zbmath,
)
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories import (
    arxiv,
    biorxiv,
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

RawMetadataFetcher = Callable[[str], str]
MetadataLoader = Callable[[str, str, RawMetadataFetcher | None], ReferenceMetadata]


@dataclass(frozen=True)
class ImportProvider:
    """One provider capable of loading normalized reference metadata."""

    kind: str
    name: str
    load: MetadataLoader


def _load_doi(
    identifier: str,
    dialect: str,
    fetcher: RawMetadataFetcher | None,
) -> ReferenceMetadata:
    text = fetcher(identifier) if fetcher is not None else doi.fetch_bibtex(identifier)
    return doi.parse_bibtex(text, identifier, dialect=dialect)


def _client_loader(module: object, **fixed: object) -> MetadataLoader:
    """Adapt any client exposing ``fetch_metadata(identifier, dialect, fetcher, **fixed)``.

    ``fixed`` supplies extra keyword arguments a client's ``fetch_metadata``
    requires beyond the common ``dialect``/``fetcher`` pair — for example
    PubMed's ``kind`` or bioRxiv/medRxiv's ``server`` — so registrations that
    would otherwise need a one-off closure can stay a single expression.
    """

    def load(
        identifier: str, dialect: str, fetcher: RawMetadataFetcher | None
    ) -> ReferenceMetadata:
        return module.fetch_metadata(  # type: ignore[attr-defined]
            identifier, dialect=dialect, fetcher=fetcher, **fixed
        )

    return load


IMPORT_PROVIDERS: Mapping[str, ImportProvider] = MappingProxyType(
    {
        "doi": ImportProvider("doi", "doi.org", _load_doi),
        "arxiv": ImportProvider("arxiv", "arXiv", _client_loader(arxiv)),
        "pmid": ImportProvider("pmid", "PubMed", _client_loader(pubmed, kind="pmid")),
        "pmcid": ImportProvider("pmcid", "PubMed Central", _client_loader(pubmed, kind="pmcid")),
        "europe_pmc": ImportProvider("europe_pmc", "Europe PMC", _client_loader(europe_pmc)),
        "ssrn": ImportProvider("ssrn", "SSRN", _client_loader(ssrn)),
        "nber": ImportProvider("nber", "NBER", _client_loader(nber)),
        "biorxiv": ImportProvider("biorxiv", "bioRxiv", _client_loader(biorxiv, server="biorxiv")),
        "medrxiv": ImportProvider("medrxiv", "medRxiv", _client_loader(biorxiv, server="medrxiv")),
        "zenodo": ImportProvider("zenodo", "Zenodo", _client_loader(zenodo)),
        "osf": ImportProvider("osf", "OSF Preprints", _client_loader(osf)),
        "hal": ImportProvider("hal", "HAL", _client_loader(hal)),
        "chemrxiv": ImportProvider("chemrxiv", "ChemRxiv", _client_loader(chemrxiv)),
        "research_square": ImportProvider(
            "research_square", "Research Square", _client_loader(research_square)
        ),
        "pii": ImportProvider("pii", "Elsevier ScienceDirect", _client_loader(elsevier)),
        "isbn": ImportProvider("isbn", "Open Library", _client_loader(openlibrary)),
        "inspire": ImportProvider("inspire", "INSPIRE-HEP", _client_loader(inspire)),
        "dblp": ImportProvider("dblp", "DBLP", _client_loader(dblp)),
        "acl": ImportProvider("acl", "ACL Anthology", _client_loader(acl_anthology)),
        "crossref": ImportProvider("crossref", "CrossRef", _client_loader(crossref)),
        "datacite": ImportProvider("datacite", "DataCite", _client_loader(datacite)),
        "openalex": ImportProvider("openalex", "OpenAlex", _client_loader(openalex)),
        "semantic_scholar": ImportProvider(
            "semantic_scholar", "Semantic Scholar", _client_loader(semantic_scholar)
        ),
        "iacr": ImportProvider("iacr", "IACR ePrint Archive", _client_loader(iacr)),
        "zbmath": ImportProvider("zbmath", "zbMATH Open", _client_loader(zbmath)),
    }
)


def get_import_provider(kind: str) -> ImportProvider:
    """Return the registered provider for ``kind``.

    The registry is explicit and ordered in source rather than populated by
    dynamic discovery, keeping import behavior deterministic and reviewable.
    """
    try:
        return IMPORT_PROVIDERS[kind]
    except KeyError as exc:
        raise KeyError(f"No import provider registered for identifier kind {kind!r}") from exc
