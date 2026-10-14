"""Saved queries: named selector expressions stored in ``pynakes-meta``."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.lint import lint
from pynakes.saved_queries import (
    NoCitationSourcesError,
    query_uses_citations,
    saved_queries,
    saved_query,
    select_entries,
    validate_query_name,
    validate_saved_query,
)

runner = CliRunner()

LIBRARY = (
    "@comment{pynakes-meta:\n"
    "tex-sources: paper.tex\n"
    "}\n"
    "\n"
    "@book{Newton1687,\n"
    "  author = {Isaac Newton},\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  year = {1687}\n"
    "}\n"
    "\n"
    "@book{Euler1748,\n"
    "  author = {Leonhard Euler},\n"
    "  title = {Introductio in analysin infinitorum},\n"
    "  year = {1748}\n"
    "}\n"
    "\n"
    "@book{Hooke1665,\n"
    "  author = {Robert Hooke},\n"
    "  title = {Micrographia},\n"
    "  year = {1665}\n"
    "}\n"
)


def _library(tmp_path: Path) -> Path:
    bib = tmp_path / "lib.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    (tmp_path / "paper.tex").write_text("\\cite{Hooke1665}\n", encoding="utf-8")
    return bib


def _json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    assert "Traceback" not in result.output
    return result.exit_code, json.loads(result.output)


def _keys(payload: dict) -> list[str]:
    return [entry["key"] for entry in payload["entries"]]


# --- storage ---------------------------------------------------------------------


def test_set_stores_one_metadata_line(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, payload = _json("query", "set", str(bib), "early", "year < 1700")

    assert code == 0
    assert payload["created"] is True
    assert payload["parsed"] == {"field": "year", "op": "<", "value": "1700"}
    text = bib.read_text(encoding="utf-8")
    assert text == LIBRARY.replace(
        "tex-sources: paper.tex\n", "tex-sources: paper.tex\nquery-early: year < 1700\n"
    )


def test_set_validates_with_the_selector_grammar(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    before = bib.read_bytes()

    code, payload = _json("query", "set", str(bib), "broken", "year >>")

    assert code == 1 and payload["error"] == "InvalidInput"
    assert bib.read_bytes() == before


@pytest.mark.parametrize("name", ["", "two words", "-dash", "semi;colon", "brace{"])
def test_invalid_names_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid query name"):
        validate_query_name(name)


@pytest.mark.parametrize(
    "expression",
    ["", "title contains '{unbalanced'", "year > 1\nor year < 2"],
)
def test_expressions_that_cannot_live_on_a_metadata_line_are_refused(expression: str) -> None:
    with pytest.raises(ValueError):
        validate_saved_query("q", expression)


def test_replacing_a_query_keeps_one_line(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "early", "year < 1700")

    code, payload = _json("query", "set", str(bib), "Early", "year < 1680")

    assert code == 0 and payload["created"] is False
    assert [q.expression for q in saved_queries(Bibliography.open(bib).lib)] == ["year < 1680"]


def test_metadata_set_validates_a_query_key_too(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, payload = _json("metadata", "set", str(bib), "query-x", "title ~")

    assert code == 1 and payload["error"] == "InvalidInput"


def test_lint_reports_a_stored_query_that_no_longer_parses(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    bib.write_text(LIBRARY.replace("tex-sources", "query-bad: year >>\ntex-sources"))

    issues = lint(Bibliography.open(bib).lib, base_dir=tmp_path)

    assert [issue.type for issue in issues if issue.field == "query-bad"] == [
        "invalid_metadata_value"
    ]
    code, payload = _json("query", "run", str(bib), "bad")
    assert code == 1 and "no longer parses" in payload["message"]


# --- list / run / remove ---------------------------------------------------------


def test_list_describes_each_query(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    bib.write_text(
        LIBRARY.replace("tex-sources", "query-early: year < 1700\nquery-bad: (\ntex-sources")
    )

    code, payload = _json("query", "list", str(bib))

    assert code == 0 and payload["count"] == 2
    early, bad = payload["queries"]
    assert early["name"] == "early" and early["valid"] and not early["uses_citations"]
    assert bad["valid"] is False and bad["parsed"] is None and bad["error"]


def test_run_returns_matches_in_file_order(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "early", "year < 1700")

    code, payload = _json("query", "run", str(bib), "EARLY")

    assert code == 0
    assert payload["name"] == "early" and payload["expression"] == "year < 1700"
    assert _keys(payload) == ["Newton1687", "Hooke1665"]
    assert payload["page"]["total"] == 2


def test_a_saved_query_reflects_later_edits(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "noted", "note exists")
    _code, before = _json("query", "run", str(bib), "noted")

    runner.invoke(app, ["ref", "edit", str(bib), "Euler1748", "--field", "note=two volumes"])
    _code, after = _json("query", "run", str(bib), "noted")

    assert _keys(before) == []
    assert _keys(after) == ["Euler1748"]


def test_run_pages_with_inclusions_and_projection(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "all", "*")

    _code, first = _json(
        "query",
        "run",
        str(bib),
        "all",
        "--limit",
        "2",
        "--select",
        "year",
        "--include",
        "materials",
    )
    _code, rest = _json(
        "query", "run", str(bib), "all", "--limit", "2", "--select", "year",
        "--cursor", first["page"]["next_cursor"],
    )  # fmt: skip

    assert _keys(first) + _keys(rest) == ["Newton1687", "Euler1748", "Hooke1665"]
    assert first["entries"][0]["fields"] == {"year": "1687"}
    assert first["entries"][0]["missing"] == ["materials"]


def test_editing_the_query_invalidates_its_cursor(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "all", "*")
    _code, first = _json("query", "run", str(bib), "all", "--limit", "1")
    _json("query", "set", str(bib), "all", "year > 1600")

    code, payload = _json("query", "run", str(bib), "all", "--cursor", first["page"]["next_cursor"])

    # The library changed, so the snapshot check fires before the request check.
    assert code == 2 and payload["error"] == "StaleCursor"


def test_used_resolves_against_linked_tex_sources(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "cited", "used")

    code, payload = _json("query", "run", str(bib), "cited")

    assert code == 0 and _keys(payload) == ["Hooke1665"]


def test_used_without_tex_sources_is_no_sources(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    bib.write_text(LIBRARY.replace("tex-sources: paper.tex", "query-cited: unused"))

    code, payload = _json("query", "run", str(bib), "cited")

    assert code == 1 and payload["error"] == "NoSources"


def test_unknown_query_names_the_available_ones(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "early", "year < 1700")

    code, payload = _json("query", "run", str(bib), "late")

    assert code == 1 and payload["error"] == "KeyNotFound"
    assert payload["available"] == ["early"]


def test_remove_restores_the_original_bytes(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _json("query", "set", str(bib), "early", "year < 1700")

    code, payload = _json("query", "remove", str(bib), "early")

    assert code == 0 and payload["expression"] == "year < 1700"
    assert bib.read_text(encoding="utf-8") == LIBRARY


def test_human_output(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    assert "no saved queries" in runner.invoke(app, ["query", "list", str(bib)]).output
    runner.invoke(app, ["query", "set", str(bib), "early", "year < 1700"])

    listed = runner.invoke(app, ["query", "list", str(bib)]).output
    ran = runner.invoke(app, ["query", "run", str(bib), "early"]).output
    again = runner.invoke(app, ["query", "set", str(bib), "early", "year < 1700"]).output

    assert "early: year < 1700" in listed
    assert "query 'early' matches 2 entries" in ran and "@book{Hooke1665}" in ran
    assert "already saved" in again


# --- Python API ------------------------------------------------------------------


def test_select_entries_keeps_duplicate_keys(fixtures_dir: Path) -> None:
    lib = Bibliography.open(fixtures_dir / "duplicate_entries.bib").lib

    entries, warnings = select_entries(lib, "key = Smith2020")

    assert len(entries) == 2 and warnings == []


def test_select_entries_accepts_explicit_cited_keys(tmp_path: Path) -> None:
    lib = Bibliography.open(_library(tmp_path)).lib

    entries, _warnings = select_entries(lib, "unused", cited_keys={"Newton1687"})

    assert [entry.key for entry in entries] == ["Euler1748", "Hooke1665"]


def test_select_entries_without_sources_raises(tmp_path: Path) -> None:
    lib = Bibliography.from_text(LIBRARY.replace("tex-sources: paper.tex\n", "")).lib

    with pytest.raises(NoCitationSourcesError):
        select_entries(lib, "used")


def test_query_lookup_and_citation_detection(tmp_path: Path) -> None:
    lib = Bibliography.from_text(
        LIBRARY.replace("tex-sources", "query-Mixed: not (used)\ntex-sources")
    ).lib

    assert saved_query(lib, "mixed") is not None and saved_query(lib, "other") is None
    assert query_uses_citations(validate_saved_query("q", "year > 1 and not (used or *)"))
    assert not query_uses_citations(validate_saved_query("q", "year > 1 or group G"))
