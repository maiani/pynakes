"""Shared constants for the pynakes package.

Central location for URL endpoints, user-agent strings, and other
cross-module constants that would otherwise be duplicated or pulled
in from peer modules.
"""

from pynakes import __version__

# ---------------------------------------------------------------------------
# User-agent
# ---------------------------------------------------------------------------

USER_AGENT = f"pynakes/{__version__} (mailto:unknown@example.invalid)"

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

OPENALEX_API = "https://api.openalex.org/works/doi:"
DOI_ORG = "https://doi.org"

ARXIV_BASE = "https://arxiv.org"
ARXIV_EXPORT_API = "https://export.arxiv.org/api/query"

# ---------------------------------------------------------------------------
# Field-name tuples used across modules
# ---------------------------------------------------------------------------

NAME_FIELDS = ("author", "editor")
TITLE_FIELDS = ("title", "booktitle", "maintitle", "subtitle")
