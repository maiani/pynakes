"""Resolve a written-out reference to records that actually exist.

An identifier is a claim that can be checked: ``ref import`` either resolves it
or does not, and ``verify --online`` compares an entry against what the
registrar holds. A reference written out in prose — author, title, venue, year —
carries no such claim, and pynakes had no way to ask whether it describes
anything real.

That matters most where references arrive already written out rather than
copied from a publisher page. A conversational assistant asked for related work
produces exactly this shape, and produces it just as fluently for a paper that
was never written: plausible authors, a plausible title, a plausible venue, and
nothing behind it. The failure is invisible by construction, because the text
looks like every correct reference beside it.

This module asks a bibliographic index what it has and reports the candidates
with the index's own relevance score attached. It deliberately stops there. A
high score is evidence that a matching record exists; a low score or an empty
result is evidence that the index has nothing close, which is not the same as
proof the work is fictitious — a genuinely obscure or very recent reference
also comes back empty. Turning that into a verdict would be a quality judgment
the data does not support, so the caller is told what was found and decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pynakes.providers._common import clean_text, person_name
from pynakes.providers.metadata import crossref
from pynakes.query import fuzzy_score

#: Crossref relevance above which a candidate stands out on the index's own
#: judgement alone. Deliberately high: the score is not normalized across
#: queries — a long reference string scores differently from a bare title — so
#: it is the weaker of the two signals and is used only to annotate, never to
#: accept or reject.
STRONG_MATCH_SCORE = 70.0

#: How strongly a candidate's title must occur in the queried text for the two
#: to be the same work. Containment, not whole-string similarity: the query is a
#: whole reference (authors, venue, year) and the title is one part of it, so
#: comparing them end to end would score every correct match low.
TITLE_MATCH_RATIO = 0.9


@dataclass(frozen=True)
class Candidate:
    """One record an index offered for a written-out reference."""

    doi: str
    title: str
    authors: list[str]
    year: str
    container: str
    entry_type: str
    #: The index's own relevance score, passed through unchanged.
    score: float
    #: Whether the candidate's title matches the queried text closely enough
    #: that the two are almost certainly the same work.
    title_match: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly view of this candidate."""
        return {
            "doi": self.doi,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "container": self.container,
            "entry_type": self.entry_type,
            "score": self.score,
            "title_match": self.title_match,
            "strong": self.strong,
        }

    @property
    def strong(self) -> bool:
        """Whether this candidate is plainly the work the text describes."""
        return self.title_match or self.score >= STRONG_MATCH_SCORE


@dataclass
class LookupReport:
    """What an index had to offer for one written-out reference."""

    query: str
    source: str
    candidates: list[Candidate]

    @property
    def strong_matches(self) -> list[Candidate]:
        """Candidates plainly describing the queried work."""
        return [candidate for candidate in self.candidates if candidate.strong]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly view of the whole report."""
        return {
            "query": self.query,
            "source": self.source,
            "count": len(self.candidates),
            "strong_count": len(self.strong_matches),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def _year_from_issued(work: dict) -> str:
    issued = work.get("issued")
    if not isinstance(issued, dict):
        return ""
    parts = issued.get("date-parts")
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        first = parts[0][0]
        return str(first) if first is not None else ""
    return ""


def candidate_from_work(work: dict, query: str) -> Candidate | None:
    """Project one Crossref work into a candidate, or ``None`` without a DOI."""
    doi = clean_text(work.get("DOI"))
    if not doi:
        return None
    titles = work.get("title")
    title = clean_text(titles[0]) if isinstance(titles, list) and titles else ""
    containers = work.get("container-title")
    container = clean_text(containers[0]) if isinstance(containers, list) and containers else ""
    raw_authors = work.get("author")
    authors = (
        [name for value in raw_authors if (name := person_name(value))]
        if isinstance(raw_authors, list)
        else []
    )
    score = work.get("score")
    return Candidate(
        doi=doi,
        title=title,
        authors=authors,
        year=_year_from_issued(work),
        container=container,
        entry_type=clean_text(work.get("type")),
        score=float(score) if isinstance(score, (int, float)) else 0.0,
        # How strongly the candidate's title occurs *inside* the reference
        # text, using the same matcher `--where 'title ~ ...'` uses, so
        # "the same title" means one thing across the whole tool.
        title_match=bool(title) and fuzzy_score(query, title) >= TITLE_MATCH_RATIO,
    )


def find_reference(
    query: str,
    *,
    rows: int = 5,
    cache_file: str | Path | None = None,
) -> LookupReport:
    """Ask Crossref what it has for a written-out reference.

    Network access is the whole purpose of this call, so it is never implicit:
    nothing else in pynakes reaches it, and the command that does is named for
    what it does.
    """
    works = crossref.search_works(query, rows=rows, cache_file=cache_file)
    candidates = [
        candidate for work in works if (candidate := candidate_from_work(work, query)) is not None
    ]
    return LookupReport(query=query.strip(), source="crossref", candidates=candidates)
