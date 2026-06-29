"""External provider client tests."""

import json
from pathlib import Path

from pynakes.providers import arxiv, identity, openalex, semantic_scholar
from pynakes.providers._http import ProviderFetchError, cache_path

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


def test_fetch_openalex_work_reads_deterministic_cache(tmp_path: Path) -> None:
    path = cache_path(tmp_path, "openalex", "10.5555/published-first", ".json")
    assert path is not None
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(OPENALEX_WORK), encoding="utf-8")

    work = openalex.fetch_work_by_doi("10.5555/published-first", cache_dir=tmp_path)

    assert work == OPENALEX_WORK


def test_fetch_semantic_scholar_paper_reads_deterministic_cache(tmp_path: Path) -> None:
    path = cache_path(tmp_path, "semantic_scholar", "10.5555/published-first", ".json")
    assert path is not None
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(SEMANTIC_SCHOLAR_PAPER), encoding="utf-8")

    paper = semantic_scholar.fetch_paper_by_doi("10.5555/published-first", cache_dir=tmp_path)

    assert paper == SEMANTIC_SCHOLAR_PAPER
