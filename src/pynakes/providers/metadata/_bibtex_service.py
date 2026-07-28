"""Shared normalization for services that publish their own BibTeX.

Several sources — INSPIRE-HEP, DBLP, the ACL Anthology, and DOI-backed
publisher paths — answer with a BibTeX record instead of a bespoke JSON or XML
format. Their client modules differ only in the request they make and the
identifier they record, so the shared parse-and-relabel step lives here.
"""

from __future__ import annotations

from collections.abc import Iterable

from pynakes.providers.metadata import doi as doi_provider
from pynakes.providers.records import ReferenceMetadata


def bibtex_metadata(
    text: str,
    *,
    provider: str,
    identifier_kind: str,
    identifier: str,
    doi: str | None = None,
    url: str | None = None,
    drop_fields: Iterable[str] = (),
    keep_provider_key: bool = True,
) -> ReferenceMetadata:
    """Normalize a provider BibTeX response into a labeled metadata record.

    ``drop_fields`` removes service bookkeeping fields that are not
    bibliographic data. ``url`` is applied only when the record has none, so
    provider-supplied links win. ``keep_provider_key`` should be false when the
    service's own key is unusable as a citation key.
    """
    metadata = doi_provider.parse_bibtex(text, doi)
    metadata.provider = provider
    for name in drop_fields:
        metadata.fields.pop(name, None)
        metadata.field_expressions.pop(name, None)
    if url:
        metadata.fields.setdefault("url", url)
    metadata.identifiers[identifier_kind] = identifier
    if not keep_provider_key:
        metadata.provider_key = None
    return metadata
