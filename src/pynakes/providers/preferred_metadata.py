"""Journal-specific preferred metadata sources for conservative enrichment.

The registry selects one source before the universal DOI resolver.  It avoids
probing several websites for the same article simply to combine their fields;
DOI content negotiation remains the fallback when a preferred source is
unavailable.
"""

from __future__ import annotations

_JOURNAL_PROVIDERS = {
    "physical review a": "aps",
    "phys. rev. a": "aps",
    "physical review b": "aps",
    "phys. rev. b": "aps",
    "physical review c": "aps",
    "phys. rev. c": "aps",
    "physical review d": "aps",
    "phys. rev. d": "aps",
    "physical review e": "aps",
    "phys. rev. e": "aps",
    "physical review letters": "aps",
    "phys. rev. lett.": "aps",
    "physical review x": "aps",
    "phys. rev. x": "aps",
    "reviews of modern physics": "aps",
    "rev. mod. phys.": "aps",
}


def preferred_metadata_provider(journal: str | None) -> str | None:
    """Return the registered metadata source for a journal title, if any."""
    if not journal:
        return None
    return _JOURNAL_PROVIDERS.get(" ".join(journal.lower().split()))
