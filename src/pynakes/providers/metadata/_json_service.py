"""Shared normalization for services that answer with a JSON record.

Crossref, DataCite, OpenAlex, and Semantic Scholar each publish their own JSON
metadata format rather than a bespoke BibTeX or XML response. Their client
modules differ only in the request they make, the envelope shape their JSON
wraps the record in, and the field mapping into
:class:`~pynakes.providers.records.ReferenceMetadata`, so the shared
fetch-decode-unwrap step lives here — the JSON counterpart to
:mod:`pynakes.providers.metadata._bibtex_service`.

The registry hands provider clients a *text* fetcher (``Callable[[str], str]``),
so an injected fetcher's response is decoded with ``json.loads`` here rather
than reused as one of the module's own ``urlopen``-based dict fetchers, whose
callable shape is different (they take a ``Request`` object, not an
identifier) and which typically already unwrap their provider's envelope.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pynakes.providers._http import ProviderFetchError
from pynakes.providers.records import ReferenceMetadata

RawFetcher = Callable[[str], str]
RecordFetcher = Callable[[str], dict | None]
Envelope = Callable[[dict], object | None]
RecordConverter = Callable[[dict, str, str], ReferenceMetadata]


def _identity_envelope(data: dict) -> object | None:
    return data


def json_metadata(
    identifier: str,
    *,
    provider: str,
    dialect: str,
    fetcher: RawFetcher | None,
    fetch_record: RecordFetcher,
    convert: RecordConverter,
    envelope: Envelope = _identity_envelope,
) -> ReferenceMetadata:
    """Fetch, unwrap, and convert one provider's JSON record.

    When ``fetcher`` is supplied (the registry's injected text fetcher, or a
    test double) its response is decoded with ``json.loads`` and ``envelope``
    extracts the record from the provider's response shape. Otherwise
    ``fetch_record`` — the module's own network client — is called directly;
    it is expected to return the record already unwrapped, since existing
    clients such as :func:`pynakes.providers.metadata.crossref.fetch_work_by_doi`
    already do so. Either way, a missing or empty record raises
    :class:`~pynakes.providers._http.ProviderFetchError`, and a successfully
    unwrapped record is handed to ``convert`` to build the normalized
    :class:`~pynakes.providers.records.ReferenceMetadata`.
    """
    if fetcher is not None:
        text = fetcher(identifier)
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderFetchError(
                f"{provider} returned invalid JSON for {identifier!r}"
            ) from exc
        record = envelope(raw) if isinstance(raw, dict) else None
    else:
        record = fetch_record(identifier)

    if not isinstance(record, dict) or not record:
        raise ProviderFetchError(f"{provider} has no record for {identifier!r}")
    return convert(record, identifier, dialect)
