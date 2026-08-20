"""External provider client tests."""

import json
import re
from pathlib import Path

import httpx
import pytest

from pynakes.provider_cache import open_cache
from pynakes.providers import identity, publisher
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import openalex, semantic_scholar
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.registry import get_import_provider
from pynakes.providers.repositories import arxiv
from pynakes.providers.url_resolvers import URLRule, resolve_reference_url, resolve_url

OPENALEX_WORK = {
    "locations": [
        {"landing_page_url": "https://doi.org/10.5555/published-first"},
        {"landing_page_url": "https://arxiv.org/abs/2401.00001v3"},
    ]
}

OPENALEX_WORK_WITHOUT_ARXIV = {
    "locations": [
        {"landing_page_url": "https://doi.org/10.5555/published-first"},
    ]
}

SEMANTIC_SCHOLAR_PAPER = {
    "externalIds": {
        "DOI": "10.5555/published-first",
        "ArXiv": "2402.00002v4",
    },
    "url": "https://www.semanticscholar.org/paper/test",
}


def test_reference_metadata_normalizes_names_and_serializes_copies() -> None:
    metadata = ReferenceMetadata(
        provider=" Example ",
        entry_type="ARTICLE",
        fields={" title ": "Test"},
        identifiers={"DOI": "10.5555/test"},
        provider_key="provider-key",
    )

    assert metadata.provider == "Example"
    assert metadata.entry_type == "article"
    assert metadata.fields == {"title": "Test"}
    assert metadata.identifier("doi") == "10.5555/test"
    assert metadata.to_dict()["fields"] == {"title": "Test"}


def test_import_provider_registry_loads_normalized_doi_metadata() -> None:
    provider = get_import_provider("doi")
    metadata = provider.load(
        "10.5555/test",
        "bibtex",
        lambda identifier: f"@article{{provider-key, title = {{Test}}, doi = {{{identifier}}}}}",
    )

    assert provider.name == "doi.org"
    assert metadata.provider_key == "provider-key"
    assert metadata.identifier("doi") == "10.5555/test"


def test_doi_provider_normalizes_identifier_field_expression() -> None:
    metadata = get_import_provider("doi").load(
        "10.5555/test",
        "bibtex",
        lambda identifier: (
            f"@article{{provider-key, title = {{Test}}, doi = {{https://doi.org/{identifier}}}}}"
        ),
    )

    assert metadata.fields["doi"] == "10.5555/test"
    assert metadata.field_expressions["doi"] == "{10.5555/test}"


def test_import_provider_registry_rejects_unknown_kind() -> None:
    with pytest.raises(KeyError, match="No import provider"):
        get_import_provider("unknown")


@pytest.mark.parametrize(
    "url,kind,identifier,source",
    [
        ("https://doi.org/10.5555/test", "doi", "10.5555/test", "doi.org"),
        ("https://arxiv.org/pdf/2301.00001v2.pdf", "arxiv", "2301.00001", "arXiv"),
        (
            "https://www.nature.com/articles/s41535-025-00801-3",
            "doi",
            "10.1038/s41535-025-00801-3",
            "Nature",
        ),
    ],
)
def test_reference_url_registry_resolves_ordered_rules(
    url: str,
    kind: str,
    identifier: str,
    source: str,
) -> None:
    resolved = resolve_reference_url(url)

    assert resolved is not None
    assert (resolved.kind, resolved.identifier, resolved.source) == (kind, identifier, source)


def test_url_registry_accepts_extension_rules() -> None:
    rule = URLRule(
        source="Example Repository",
        kind="example",
        pattern=re.compile(r"^https://example\.org/records/(\d+)$"),
        extract=lambda match: match.group(1),
        normalize=lambda identifier: identifier,
    )

    resolved = resolve_url("https://example.org/records/42", (rule,))

    assert resolved is not None
    assert resolved.identifier == "42"


def test_arxiv_material_urls_normalize_identifiers() -> None:
    assert arxiv.pdf_url("https://arxiv.org/pdf/2101.00001v2.pdf") == (
        "https://arxiv.org/pdf/2101.00001"
    )
    assert arxiv.source_url("arXiv:hep-th/9901001v3") == (
        "https://arxiv.org/e-print/hep-th/9901001"
    )


def test_resolve_arxiv_id_for_doi_scans_openalex_locations() -> None:
    resolved = identity.resolve_arxiv_id_for_doi(
        "10.5555/published-first",
        openalex_fetcher=lambda doi: OPENALEX_WORK,
        semantic_scholar_fetcher=lambda doi: SEMANTIC_SCHOLAR_PAPER,
    )

    assert resolved == "2401.00001"


def test_resolve_arxiv_id_for_doi_falls_back_to_semantic_scholar() -> None:
    resolved = identity.resolve_arxiv_id_for_doi(
        "10.5555/published-first",
        openalex_fetcher=lambda doi: OPENALEX_WORK_WITHOUT_ARXIV,
        semantic_scholar_fetcher=lambda doi: SEMANTIC_SCHOLAR_PAPER,
    )

    assert resolved == "2402.00002"


def test_resolve_arxiv_id_for_doi_uses_fallback_after_openalex_error() -> None:
    def failing_openalex(doi: str) -> dict | None:
        raise ProviderFetchError("OpenAlex test failure")

    resolved = identity.resolve_arxiv_id_for_doi(
        "10.5555/published-first",
        openalex_fetcher=failing_openalex,
        semantic_scholar_fetcher=lambda doi: SEMANTIC_SCHOLAR_PAPER,
    )

    assert resolved == "2402.00002"


def test_resolve_arxiv_id_for_doi_combines_provider_failures() -> None:
    def fail_openalex(doi: str) -> dict | None:
        raise ProviderFetchError("OpenAlex unavailable")

    def fail_semantic_scholar(doi: str) -> dict | None:
        raise ProviderFetchError("Semantic Scholar unavailable")

    with pytest.raises(
        ProviderFetchError, match="OpenAlex unavailable; Semantic Scholar unavailable"
    ):
        identity.resolve_arxiv_id_for_doi(
            "10.5555/published-first",
            openalex_fetcher=fail_openalex,
            semantic_scholar_fetcher=fail_semantic_scholar,
        )


def test_resolve_arxiv_id_for_doi_propagates_fallback_failure() -> None:
    def fail_semantic_scholar(doi: str) -> dict | None:
        raise ProviderFetchError("Semantic Scholar unavailable")

    with pytest.raises(ProviderFetchError, match="Semantic Scholar unavailable"):
        identity.resolve_arxiv_id_for_doi(
            "10.5555/published-first",
            openalex_fetcher=lambda doi: None,
            semantic_scholar_fetcher=fail_semantic_scholar,
        )


def test_resolve_arxiv_id_for_doi_preserves_openalex_failure_when_fallback_is_empty() -> None:
    def fail_openalex(doi: str) -> dict | None:
        raise ProviderFetchError("OpenAlex unavailable")

    with pytest.raises(ProviderFetchError, match="OpenAlex unavailable"):
        identity.resolve_arxiv_id_for_doi(
            "10.5555/published-first",
            openalex_fetcher=fail_openalex,
            semantic_scholar_fetcher=lambda doi: None,
        )


def test_resolve_arxiv_id_for_doi_returns_none_when_providers_have_no_match() -> None:
    assert (
        identity.resolve_arxiv_id_for_doi(
            "10.5555/published-first",
            openalex_fetcher=lambda doi: None,
            semantic_scholar_fetcher=lambda doi: None,
        )
        is None
    )


def test_fetch_openalex_work_reads_deterministic_cache(tmp_path: Path) -> None:
    cache_file = tmp_path / ".pynakes-cache"
    cache = open_cache(cache_file)
    assert cache is not None
    cache.put("openalex", "10.5555/published-first", "json", json.dumps(OPENALEX_WORK))

    work = openalex.fetch_work_by_doi("10.5555/published-first", cache_file=cache_file)

    assert work == OPENALEX_WORK


def test_fetch_semantic_scholar_paper_reads_deterministic_cache(tmp_path: Path) -> None:
    cache_file = tmp_path / ".pynakes-cache"
    cache = open_cache(cache_file)
    assert cache is not None
    cache.put(
        "semantic_scholar",
        "10.5555/published-first",
        "json",
        json.dumps(SEMANTIC_SCHOLAR_PAPER),
    )

    paper = semantic_scholar.fetch_paper_by_doi("10.5555/published-first", cache_file=cache_file)

    assert paper == SEMANTIC_SCHOLAR_PAPER


def test_publisher_pdf_url_abstract_to_pdf() -> None:
    from pynakes.providers.pdf_overrides import publisher_pdf_url

    url = publisher_pdf_url("https://journals.aps.org/prb/abstract/10.1103/PhysRevB.111.224421")
    assert url == "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.111.224421"


def test_publisher_pdf_url_no_match_returns_none() -> None:
    from pynakes.providers.pdf_overrides import publisher_pdf_url

    url = publisher_pdf_url("https://example.com/some/article")
    assert url is None


def test_publisher_pdf_url_doi_prefix_aps() -> None:
    from pynakes.providers.pdf_overrides import publisher_pdf_url

    url = publisher_pdf_url(
        "https://doi.org/10.1103/f6nc-vsnx",
        doi="10.1103/f6nc-vsnx",
    )
    assert url == "http://harvest.aps.org/v2/journals/articles/10.1103/f6nc-vsnx/fulltext"


def test_publisher_pdf_url_doi_prefix_no_doi_skips_doi_rules() -> None:
    from pynakes.providers.pdf_overrides import publisher_pdf_url

    url = publisher_pdf_url("https://doi.org/10.1103/f6nc-vsnx")
    assert url is None


def test_discover_publisher_artifacts_reads_pdf_meta_and_supplement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://doi.org/10.5555/entitled"
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html"},
            content=(
                b'<meta name="citation_pdf_url" content="/article/main.pdf">'
                b'<a href="files/supporting-information.pdf">Supporting information</a>'
            ),
        )

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("pynakes.providers.publisher.httpx.Client", MockClient)

    artifacts = publisher.discover_artifacts_for_doi("10.5555/entitled")

    assert artifacts.published_pdf_url == "https://doi.org/article/main.pdf"
    assert artifacts.supplement_pdf_urls == (
        "https://doi.org/10.5555/files/supporting-information.pdf",
    )
