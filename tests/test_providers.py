"""External provider client tests."""

import json
import re
from pathlib import Path

import httpx
import pytest

from pynakes.provider_cache import open_cache
from pynakes.providers import _network, identity, publisher
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


@pytest.mark.parametrize(
    "supplied,expected",
    [
        ("2446\u20132449", "2446--2449"),  # Crossref and friends render U+2013
        ("2446\u20142449", "2446--2449"),  # em-dash
        ("231-252", "231--252"),  # a lone hyphen is not BibTeX's range either
        ("pp. 12--34", "12--34"),
        ("e0123456", "e0123456"),  # an article number is not a range
        ("7,41,73--97", "7,41,73--97"),  # a page list is not a simple range
    ],
)
def test_reference_metadata_spells_page_ranges_the_way_bibtex_does(
    supplied: str, expected: str
) -> None:
    """Every provider builds one of these, so the repair belongs here, not per-client.

    A raw en-dash renders under UTF-8 plus inputenc but breaks 8-bit bibtex with
    some styles, and is near-indistinguishable from a hyphen in review.
    """
    metadata = ReferenceMetadata(
        provider="Example", entry_type="article", fields={"pages": supplied}
    )

    assert metadata.fields["pages"] == expected
    if supplied != expected:
        # The expression is what the writer emits, so it has to move too.
        assert metadata.field_expressions["pages"] == f"{{{expected}}}"
    else:
        assert "pages" not in metadata.field_expressions


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
            "https://www.nature.com/articles/s41535-099-00042-7",
            "doi",
            "10.1038/s41535-099-00042-7",
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

    url = publisher_pdf_url("https://journals.aps.org/prb/abstract/10.1103/PhysRevB.999.224421")
    assert url == "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.999.224421"


def test_publisher_pdf_url_no_match_returns_none() -> None:
    from pynakes.providers.pdf_overrides import publisher_pdf_url

    url = publisher_pdf_url("https://example.com/some/article")
    assert url is None


def test_publisher_pdf_url_doi_prefix_aps() -> None:
    from pynakes.providers.pdf_overrides import publisher_pdf_url

    url = publisher_pdf_url(
        "https://doi.org/10.1103/h3pd-x9mv",
        doi="10.1103/h3pd-x9mv",
    )
    assert url == "https://harvest.aps.org/v2/journals/articles/10.1103/h3pd-x9mv/fulltext"


def test_publisher_pdf_url_doi_prefix_no_doi_skips_doi_rules() -> None:
    from pynakes.providers.pdf_overrides import publisher_pdf_url

    url = publisher_pdf_url("https://doi.org/10.1103/h3pd-x9mv")
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

    _mock_guarded_client(monkeypatch, handler)

    artifacts = publisher.discover_artifacts_for_doi("10.5555/entitled")

    assert artifacts.published_pdf_url == "https://doi.org/article/main.pdf"
    assert artifacts.supplement_pdf_urls == (
        "https://doi.org/10.5555/files/supporting-information.pdf",
    )


def _mock_guarded_client(monkeypatch: pytest.MonkeyPatch, handler) -> list[dict]:
    """Serve requests from *handler* inside the guarded client, keeping its request guard.

    Returns the keyword arguments of every client built, so a test can check
    the guard's configuration.
    """
    transport = httpx.MockTransport(handler)
    original = httpx.Client
    built: list[dict] = []

    def client(**kwargs):
        built.append(dict(kwargs))
        return original(**{**kwargs, "transport": transport})

    monkeypatch.setattr(httpx, "Client", client)
    return built


def test_discover_publisher_artifacts_uses_the_guarded_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _mock_guarded_client(
        monkeypatch,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html; charset=latin-1"}, content=b"<html></html>"
        ),
    )

    publisher.discover_artifacts_for_doi("10.5555/entitled")

    assert len(built) == 1
    assert built[0]["trust_env"] is False
    assert isinstance(built[0]["transport"], _network.PublicTransport)
    assert built[0]["event_hooks"]["request"]


def test_discover_publisher_artifacts_refuses_a_redirect_to_a_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://10.0.0.7/landing"})

    _mock_guarded_client(monkeypatch, handler)

    with pytest.raises(ProviderFetchError, match="non-public"):
        publisher.discover_artifacts_for_doi("10.5555/entitled")
    assert requested == ["https://doi.org/10.5555/entitled"]


def test_discover_publisher_artifacts_refuses_a_host_resolving_privately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://landing.example/article"})

    _mock_guarded_client(monkeypatch, handler)
    monkeypatch.setattr(
        _network,
        "_getaddrinfo",
        lambda host, port: ["192.168.1.20"] if host == "landing.example" else ["93.184.216.34"],
    )

    with pytest.raises(ProviderFetchError, match="non-public"):
        publisher.discover_artifacts_for_doi("10.5555/entitled")


def test_discover_publisher_artifacts_with_an_injected_opener_follows_the_final_url() -> None:
    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def __init__(self) -> None:
            self._body = b'<meta name="citation_pdf_url" content="/main.pdf">'

        def geturl(self) -> str:
            return "https://landing.example/article/42"

        def read(self, size: int = -1) -> bytes:
            body, self._body = self._body, b""
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    artifacts = publisher.discover_artifacts_for_doi(
        "10.5555/entitled", opener=lambda request, timeout: Response()
    )

    assert artifacts.landing_url == "https://landing.example/article/42"
    assert artifacts.published_pdf_url == "https://landing.example/main.pdf"
