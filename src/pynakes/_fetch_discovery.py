"""Finding a missing arXiv id during ``asset fetch --discover``, and checking it names the work.

Not public API. When a run needs a preprint for an entry that has a DOI but no
arXiv id, :mod:`pynakes._engine_fetch` asks this module to look one up
(OpenAlex, then Semantic Scholar) and to check the answer against arXiv's own
record before anything is downloaded or written:

* ``linked`` — the arXiv record names the same DOI, or its title matches the
  entry's. The id is used and written to the entry when it has no ``eprint``.
* ``ambiguous`` — an id was found but arXiv's record does not confirm it.
  Nothing is used or written; the candidate and its title are reported.
* ``not_found`` — the providers know no arXiv version of the DOI.
* ``not_checked`` — a lookup failed or was throttled, so nothing is known.
  ``retryable`` says whether running again later can change that.

``not_found`` and ``not_checked`` are kept apart on purpose: only the first is
an answer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pynakes._identifiers import canonical_doi, normalize_arxiv
from pynakes._text_utils import title_similarity
from pynakes.editing import set_entry_field
from pynakes.model import BibEntry
from pynakes.providers._http import ProviderFetchError, ProviderRateLimitedError
from pynakes.providers.repositories.arxiv import ArxivRecord

DiscoveryStatus = Literal["linked", "ambiguous", "not_found", "not_checked"]

#: How alike the entry's title and arXiv's must be to confirm an id without a DOI
#: match; the same threshold the published-version checks use.
TITLE_MATCH = 0.86

ArxivLookup = Callable[[str], str | None]
ArxivRecordFetcher = Callable[[str], ArxivRecord]


@dataclass(frozen=True)
class ArxivDiscovery:
    """The outcome of looking up one entry's arXiv id by its DOI."""

    key: str
    doi: str
    status: DiscoveryStatus
    arxiv_id: str | None = None
    verified_by: str | None = None
    message: str = ""
    retryable: bool = False
    written: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """Serialize the outcome for the ``discovered`` list of a fetch report."""
        item: dict[str, object] = {
            "key": self.key,
            "doi": self.doi,
            "status": self.status,
            "arxiv_id": self.arxiv_id,
        }
        if self.verified_by is not None:
            item["verified_by"] = self.verified_by
        if self.message:
            item["message"] = self.message
        if self.status == "not_checked":
            item["retryable"] = self.retryable
        item["written"] = list(self.written)
        return item


def discover_arxiv_id(
    entry: BibEntry,
    doi: str,
    *,
    lookup: ArxivLookup,
    record_fetcher: ArxivRecordFetcher,
) -> ArxivDiscovery:
    """Look up the arXiv id for *doi* and check it against arXiv's record of that id."""
    key = entry.key
    try:
        found = lookup(doi)
    except ProviderRateLimitedError as exc:
        return ArxivDiscovery(key, doi, "not_checked", message=str(exc), retryable=True)
    except ProviderFetchError as exc:
        return ArxivDiscovery(key, doi, "not_checked", message=str(exc), retryable=True)
    arxiv_id = normalize_arxiv(found) if found else None
    if arxiv_id is None:
        return ArxivDiscovery(
            key, doi, "not_found", message="OpenAlex and Semantic Scholar know no arXiv version"
        )
    try:
        record = record_fetcher(arxiv_id)
    except ProviderFetchError as exc:
        return ArxivDiscovery(
            key,
            doi,
            "not_checked",
            arxiv_id=arxiv_id,
            message=f"found arXiv:{arxiv_id} but could not read its arXiv record: {exc}",
            retryable=True,
        )
    verified_by = _verify(entry, doi, record)
    if verified_by is None:
        return ArxivDiscovery(
            key,
            doi,
            "ambiguous",
            arxiv_id=arxiv_id,
            message=f"arXiv:{arxiv_id} is titled {record.title!r}, which does not match "
            "the entry, and arXiv records no matching DOI; not used",
        )
    return ArxivDiscovery(key, doi, "linked", arxiv_id=arxiv_id, verified_by=verified_by)


def _verify(entry: BibEntry, doi: str, record: ArxivRecord) -> str | None:
    """Name the evidence that *record* is the entry's work, or ``None`` when there is none."""
    if record.doi:
        try:
            if canonical_doi(record.doi) == canonical_doi(doi):
                return "arxiv_doi"
        except ValueError:
            pass
    title = entry.fields.get("title", "")
    if title and record.title and title_similarity(title, record.title) >= TITLE_MATCH:
        return "title"
    return None


def link_arxiv_id(entry: BibEntry, arxiv_id: str, dialect: str) -> tuple[str, ...]:
    """Write a confirmed arXiv id to *entry* without replacing anything it already has.

    Sets ``eprint`` only when the entry has none, and the archive field
    (``archiveprefix`` for BibTeX, ``eprinttype`` for BibLaTeX) only when it is
    empty. Returns the names of the fields written.
    """
    if entry.fields.get("eprint", "").strip():
        return ()
    written: list[str] = []
    if set_entry_field(entry, "eprint", arxiv_id):
        written.append("eprint")
    archive_field = "eprinttype" if dialect == "biblatex" else "archiveprefix"
    archive_value = "arxiv" if dialect == "biblatex" else "arXiv"
    if not entry.fields.get(archive_field, "").strip() and set_entry_field(
        entry, archive_field, archive_value
    ):
        written.append(archive_field)
    return tuple(written)
