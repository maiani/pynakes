"""Cross-provider identity resolution helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pynakes._identifiers import normalize_doi
from pynakes.providers import openalex, semantic_scholar
from pynakes.providers._http import ProviderFetchError


def resolve_arxiv_id_for_doi(
    doi: str,
    *,
    cache_dir: str | Path | None = None,
    openalex_fetcher: Callable[[str], dict | None] | None = None,
    semantic_scholar_fetcher: Callable[[str], dict | None] | None = None,
) -> str | None:
    """Resolve a DOI to an arXiv id through OpenAlex, then Semantic Scholar."""
    normalized = normalize_doi(doi)
    openalex_error: ProviderFetchError | None = None
    try:
        if openalex_fetcher is None:
            work = openalex.fetch_work_by_doi(normalized, cache_dir=cache_dir)
        else:
            work = openalex_fetcher(normalized)
        if work is not None:
            arxiv_id = openalex.arxiv_id_from_work(work)
            if arxiv_id:
                return arxiv_id
    except ProviderFetchError as exc:
        openalex_error = exc

    try:
        if semantic_scholar_fetcher is None:
            paper = semantic_scholar.fetch_paper_by_doi(normalized, cache_dir=cache_dir)
        else:
            paper = semantic_scholar_fetcher(normalized)
    except ProviderFetchError as exc:
        if openalex_error is not None:
            raise ProviderFetchError(f"{openalex_error}; {exc}") from exc
        raise
    if paper is None:
        if openalex_error is not None:
            raise openalex_error
        return None
    return semantic_scholar.arxiv_id_from_paper(paper)
