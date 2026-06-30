"""Semantic Scholar provider helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from pynakes._identifiers import arxiv_id_from_text, normalize_arxiv, normalize_doi
from pynakes.providers._http import fetch_json, iter_strings

GRAPH_API_URL = "https://api.semanticscholar.org/graph/v1"


def fetch_paper_by_doi(
    doi: str,
    *,
    cache_dir: str | Path | None = None,
    urlopen: Callable[..., object] | None = None,
) -> dict | None:
    """Fetch Semantic Scholar paper metadata by DOI."""
    normalized = normalize_doi(doi)
    url = f"{GRAPH_API_URL}/paper/DOI:{quote(normalized, safe='')}?fields=externalIds,url"
    return fetch_json(
        url,
        namespace="semantic_scholar",
        identifier=normalized,
        provider="Semantic Scholar",
        cache_dir=cache_dir,
        opener=urlopen,
    )


def arxiv_id_from_paper(paper: dict) -> str | None:
    """Return the arXiv id in Semantic Scholar metadata, if any."""
    external_ids = paper.get("externalIds")
    if isinstance(external_ids, dict):
        for name, value in external_ids.items():
            if name.lower() == "arxiv" and isinstance(value, str):
                return normalize_arxiv(value)
    for value in iter_strings(paper):
        arxiv_id = arxiv_id_from_text(value)
        if arxiv_id:
            return arxiv_id
    return None
