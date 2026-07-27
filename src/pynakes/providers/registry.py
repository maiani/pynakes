"""Explicit registry of metadata providers available to reference import."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pynakes.providers.metadata import doi
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.repositories import arxiv

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


IMPORT_PROVIDERS: Mapping[str, ImportProvider] = MappingProxyType(
    {
        "doi": ImportProvider("doi", "doi.org", _load_doi),
        "arxiv": ImportProvider("arxiv", "arXiv", _load_arxiv),
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
