"""Explicit registry of metadata providers available to reference import."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pynakes.providers.metadata import doi
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
    del dialect
    text = fetcher(identifier) if fetcher is not None else doi.fetch_bibtex(identifier)
    return doi.parse_bibtex(text, identifier)


def _load_arxiv(
    identifier: str,
    dialect: str,
    fetcher: RawMetadataFetcher | None,
) -> ReferenceMetadata:
    return arxiv.fetch_metadata(identifier, dialect=dialect, fetcher=fetcher)


def _load_pmid(
    identifier: str, dialect: str, fetcher: RawMetadataFetcher | None
) -> ReferenceMetadata:
    return pubmed.fetch_metadata(identifier, kind="pmid", dialect=dialect, fetcher=fetcher)


def _load_pmcid(
    identifier: str, dialect: str, fetcher: RawMetadataFetcher | None
) -> ReferenceMetadata:
    return pubmed.fetch_metadata(identifier, kind="pmcid", dialect=dialect, fetcher=fetcher)


def _load_europe_pmc(
    identifier: str, dialect: str, fetcher: RawMetadataFetcher | None
) -> ReferenceMetadata:
    return europe_pmc.fetch_metadata(identifier, dialect=dialect, fetcher=fetcher)


def _load_biorxiv(
    identifier: str, dialect: str, fetcher: RawMetadataFetcher | None
) -> ReferenceMetadata:
    return biorxiv.fetch_metadata(identifier, server="biorxiv", dialect=dialect, fetcher=fetcher)


def _load_medrxiv(
    identifier: str, dialect: str, fetcher: RawMetadataFetcher | None
) -> ReferenceMetadata:
    return biorxiv.fetch_metadata(identifier, server="medrxiv", dialect=dialect, fetcher=fetcher)


def _repository_loader(module: object) -> MetadataLoader:
    def load(
        identifier: str, dialect: str, fetcher: RawMetadataFetcher | None
    ) -> ReferenceMetadata:
        return module.fetch_metadata(identifier, dialect=dialect, fetcher=fetcher)  # type: ignore[attr-defined]

    return load


IMPORT_PROVIDERS: Mapping[str, ImportProvider] = MappingProxyType(
    {
        "doi": ImportProvider("doi", "doi.org", _load_doi),
        "arxiv": ImportProvider("arxiv", "arXiv", _load_arxiv),
        "pmid": ImportProvider("pmid", "PubMed", _load_pmid),
        "pmcid": ImportProvider("pmcid", "PubMed Central", _load_pmcid),
        "europe_pmc": ImportProvider("europe_pmc", "Europe PMC", _load_europe_pmc),
        "ssrn": ImportProvider("ssrn", "SSRN", _repository_loader(ssrn)),
        "nber": ImportProvider("nber", "NBER", _repository_loader(nber)),
        "biorxiv": ImportProvider("biorxiv", "bioRxiv", _load_biorxiv),
        "medrxiv": ImportProvider("medrxiv", "medRxiv", _load_medrxiv),
        "zenodo": ImportProvider("zenodo", "Zenodo", _repository_loader(zenodo)),
        "osf": ImportProvider("osf", "OSF Preprints", _repository_loader(osf)),
        "hal": ImportProvider("hal", "HAL", _repository_loader(hal)),
        "chemrxiv": ImportProvider("chemrxiv", "ChemRxiv", _repository_loader(chemrxiv)),
        "research_square": ImportProvider(
            "research_square", "Research Square", _repository_loader(research_square)
        ),
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
