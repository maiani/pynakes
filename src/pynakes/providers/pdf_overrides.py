"""Publisher-specific PDF URL construction overrides.

When OpenAlex's ``best_oa_location`` identifies a publisher landing page but
does not provide a direct ``pdf_url``, rules in :file:`pdf_overrides.json`
construct the PDF URL from the landing page URL or DOI.

This ensures OA papers hosted by participating publishers are still
discoverable as published PDFs even when third-party metadata providers lack
the direct download link.
"""

from __future__ import annotations

import json
from typing import Any


def _load_rules() -> list[dict[str, Any]]:
    try:
        from importlib.resources import files
    except ImportError:
        from importlib_resources import files  # type: ignore[import-not-found,no-redef]

    ref = files(__package__) / "pdf_overrides.json"  # type: ignore[arg-type]
    data = json.loads(ref.read_text(encoding="utf-8"))
    return data.get("rules", [])


_RULES: list[dict[str, Any]] | None = None


def _rules() -> list[dict[str, Any]]:
    global _RULES
    if _RULES is None:
        _RULES = _load_rules()
    return _RULES


def publisher_pdf_url(landing_page_url: str, doi: str | None = None) -> str | None:
    """Construct a PDF URL from a publisher landing page URL (and optional DOI).

    Applies the rules from :file:`pdf_overrides.json`.  Rules can match on:
    * ``url_contains`` — substring match on the landing page URL, then apply
      a string replacement (``from`` → ``to``) or append a suffix.
    * ``doi_prefix`` — DOI prefix match (requires *doi*), then apply a
      ``doi_to_url`` template with ``{doi}`` placeholder.
    """
    for rule in _rules():
        if "doi_prefix" in rule and doi and doi.startswith(rule["doi_prefix"]):
            if "doi_to_url" in rule:
                return rule["doi_to_url"].replace("{doi}", doi)

        needle = rule.get("url_contains")
        if needle and needle in landing_page_url:
            if "from" in rule and "to" in rule:
                result = landing_page_url.replace(rule["from"], rule["to"], 1)
                if result != landing_page_url:
                    return result
            if "append" in rule:
                return landing_page_url + rule["append"]
    return None
