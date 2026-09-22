"""Tests for resolving a written-out reference to records that exist."""

import json

import pytest
from typer.testing import CliRunner

from pynakes import lookup as lookup_ops
from pynakes.cli import app
from pynakes.lookup import candidate_from_work, find_reference
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import crossref

runner = CliRunner()


def work(
    doi: str = "10.5555/engines",
    title: str = "On a Representation of Analytical Engines",
    year: int | None = 1843,
    score: float = 42.0,
    container: str = "Notes of the Analytical Society",
) -> dict:
    """One Crossref search hit, shaped as the works endpoint returns it."""
    record: dict = {
        "DOI": doi,
        "title": [title],
        "container-title": [container],
        "author": [{"given": "Ada", "family": "Lovelace"}],
        "type": "journal-article",
        "score": score,
    }
    if year is not None:
        record["issued"] = {"date-parts": [[year, 7]]}
    return record


def test_candidate_projects_the_fields_a_reader_judges_by() -> None:
    candidate = candidate_from_work(work(), "anything")

    assert candidate is not None
    assert candidate.doi == "10.5555/engines"
    assert candidate.title == "On a Representation of Analytical Engines"
    assert candidate.authors == ["Ada Lovelace"]
    assert candidate.year == "1843"
    assert candidate.container == "Notes of the Analytical Society"
    assert candidate.score == 42.0


def test_a_record_without_a_doi_is_not_a_candidate() -> None:
    """Without a DOI there is nothing to import, so there is nothing to offer."""
    assert candidate_from_work({"title": ["Untraceable"]}, "Untraceable") is None


def test_a_title_inside_the_reference_text_is_a_strong_match() -> None:
    """The query is a whole reference; the title is one part of it.

    Comparing the two end to end scores every correct match low, which is the
    bug this asserts against: the title has to be found *within* the text.
    """
    text = (
        "Lovelace, A. On a Representation of Analytical Engines. "
        "Notes of the Analytical Society, 1843."
    )

    candidate = candidate_from_work(work(score=10.0), text)

    assert candidate is not None
    assert candidate.title_match is True
    assert candidate.strong is True


def test_a_high_index_score_alone_is_a_strong_match() -> None:
    candidate = candidate_from_work(work(score=95.0), "something else entirely")

    assert candidate is not None
    assert candidate.title_match is False
    assert candidate.strong is True


def test_an_unrelated_candidate_is_not_strong() -> None:
    """The invented-reference case: plausible neighbours, nothing that matches."""
    candidate = candidate_from_work(
        work(title="Garden optimization problems for benchmarking annealers", score=36.8),
        "Thornbury and Alvarez, Recursive Gradient Sharpening, 2021",
    )

    assert candidate is not None
    assert candidate.strong is False


def test_find_reference_reports_strong_matches_separately(monkeypatch) -> None:
    monkeypatch.setattr(
        crossref,
        "search_works",
        lambda query, rows=5, cache_file=None: [
            work(score=95.0),
            work(doi="10.5555/other", title="An Unrelated Treatise", score=3.0),
        ],
    )

    report = find_reference("On a Representation of Analytical Engines")

    assert report.source == "crossref"
    assert len(report.candidates) == 2
    assert [candidate.doi for candidate in report.strong_matches] == ["10.5555/engines"]
    assert report.to_dict()["strong_count"] == 1


def test_find_reference_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        find_reference("   ")


def test_cli_requires_online(monkeypatch) -> None:
    """Network access stays explicit, as it does everywhere else in the tool."""

    def refuse(*args, **kwargs):
        raise AssertionError("no provider call may happen without --online")

    monkeypatch.setattr(lookup_ops.crossref, "search_works", refuse)

    result = runner.invoke(app, ["ref", "find", "some reference", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "OnlineLookupRequired"


def test_cli_reports_candidates_as_json(monkeypatch) -> None:
    monkeypatch.setattr(
        lookup_ops.crossref,
        "search_works",
        lambda query, rows=5, cache_file=None: [work(score=95.0)],
    )

    result = runner.invoke(app, ["ref", "find", "Analytical Engines", "--online", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["action"] == "ref_find"
    assert data["count"] == 1
    assert data["strong_count"] == 1
    assert data["candidates"][0]["doi"] == "10.5555/engines"


def test_cli_says_an_empty_result_is_evidence_not_proof(monkeypatch) -> None:
    """An obscure work also matches nothing, so the wording must not overclaim."""
    monkeypatch.setattr(
        lookup_ops.crossref, "search_works", lambda query, rows=5, cache_file=None: []
    )

    result = runner.invoke(app, ["ref", "find", "Invented Work", "--online"])

    assert result.exit_code == 0, result.output
    assert "not proof" in result.output


def test_cli_warns_when_nothing_plainly_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        lookup_ops.crossref,
        "search_works",
        lambda query, rows=5, cache_file=None: [work(title="Something Adjacent", score=20.0)],
    )

    result = runner.invoke(app, ["ref", "find", "Recursive Gradient Sharpening", "--online"])

    assert result.exit_code == 0, result.output
    assert "No candidate plainly matches" in result.output


def test_cli_reports_a_provider_failure_without_a_traceback(monkeypatch) -> None:
    def boom(query, rows=5, cache_file=None):
        raise ProviderFetchError("CrossRef is unavailable")

    monkeypatch.setattr(lookup_ops.crossref, "search_works", boom)

    result = runner.invoke(app, ["ref", "find", "anything", "--online", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "ProviderUnavailable"
