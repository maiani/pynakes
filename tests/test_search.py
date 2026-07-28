"""Tests for bibliography search."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.query import parse_query
from pynakes.search import _candidate_values, parse_search_query, search_entries

_LIB = (
    "@article{Alpha2024,\n"
    "  author = {Avery Example},\n"
    "  title = {Neural Widgets for Small Libraries},\n"
    "  year = {2024}\n"
    "}\n\n"
    "@book{Beta2023,\n"
    "  author = {Blair Example},\n"
    "  title = {Manual Widgets},\n"
    "  year = {2023}\n"
    "}\n"
)


def test_free_text_terms_are_anded() -> None:
    lib = parse_bib(_LIB)

    results = search_entries(lib, "neural widgets")

    assert [result.key for result in results] == ["Alpha2024"]
    assert results[0].matched_fields == ["title"]


def test_field_scoped_terms() -> None:
    lib = parse_bib(_LIB)

    results = search_entries(lib, "title:manual type:book")

    assert [result.key for result in results] == ["Beta2023"]
    assert results[0].matched_fields == ["title", "type"]


def test_field_limit_restricts_stored_field_search_and_output() -> None:
    lib = parse_bib(_LIB)

    results = search_entries(lib, "example", fields=["title"])

    assert results == []
    title_results = search_entries(lib, "widgets", fields=["title"])
    assert [result.fields for result in title_results] == [
        {"title": "Neural Widgets for Small Libraries"},
        {"title": "Manual Widgets"},
    ]


def test_candidate_values_normalizes_scoped_field_against_filter() -> None:
    entry = parse_bib("@article{A, title={Manual Widgets}}\n").entries["A"]

    assert _candidate_values(entry, "TITLE", {"title"}) == [("title", "Manual Widgets")]
    assert _candidate_values(entry, "TITLE", {"author"}) == []


def test_case_sensitive_search() -> None:
    lib = parse_bib(_LIB)

    assert search_entries(lib, "widgets", case_sensitive=True) == []
    assert [result.key for result in search_entries(lib, "Widgets", case_sensitive=True)] == [
        "Alpha2024",
        "Beta2023",
    ]


def test_limit() -> None:
    lib = parse_bib(_LIB)

    results = search_entries(lib, "widgets", limit=1)

    assert [result.key for result in results] == ["Alpha2024"]


def test_invalid_query_raises() -> None:
    with pytest.raises(ValueError):
        parse_search_query('"unterminated')


_RANK_LIB = (
    "@article{Alpha2024,\n"
    "  title = {Small Libraries},\n"
    "  groups = {widgets},\n"
    "  year = {2024}\n"
    "}\n\n"
    "@book{Beta2023,\n"
    "  title = {Widgets for Everyone},\n"
    "  year = {2023}\n"
    "}\n\n"
    "@misc{widgets_2022,\n"
    "  title = {An Unrelated Note},\n"
    "  year = {2022}\n"
    "}\n"
)


def test_rank_orders_by_match_strength_by_default() -> None:
    lib = parse_bib(_RANK_LIB)

    results = search_entries(lib, "widgets")

    # key match (widgets_2022) > title match (Beta2023) > groups match (Alpha2024)
    assert [result.key for result in results] == ["widgets_2022", "Beta2023", "Alpha2024"]


def test_no_rank_keeps_file_order() -> None:
    lib = parse_bib(_RANK_LIB)

    results = search_entries(lib, "widgets", rank=False)

    assert [result.key for result in results] == ["Alpha2024", "Beta2023", "widgets_2022"]


def test_limit_applies_after_ranking() -> None:
    lib = parse_bib(_RANK_LIB)

    results = search_entries(lib, "widgets", limit=1)

    assert [result.key for result in results] == ["widgets_2022"]


# --- fuzzy matching and match explanations ---------------------------------


def test_fuzzy_finds_a_misspelled_title() -> None:
    lib = parse_bib(_LIB)

    assert search_entries(lib, "nueral widgts") == []
    results = search_entries(lib, "nueral widgts", fuzzy=True)

    assert [result.key for result in results] == ["Alpha2024"]
    assert [match.kind for match in results[0].matches] == ["fuzzy", "fuzzy"]
    assert 0.8 <= results[0].score < 1.0


def test_exact_matches_are_explained_with_field_term_and_excerpt() -> None:
    lib = parse_bib(_LIB)

    (result,) = search_entries(lib, "title:neural")

    assert [(m.field, m.term, m.kind, m.score) for m in result.matches] == [
        ("title", "neural", "exact", 1.0)
    ]
    assert result.matches[0].excerpt == "Neural Widgets for Small Libraries"
    assert result.score == 1.0


def test_excerpt_is_trimmed_around_a_deep_match() -> None:
    long_abstract = "start " + "filler word " * 12 + "needle " + "tail word " * 12
    lib = parse_bib("@article{A,\n  abstract = {" + long_abstract + "}\n}\n")

    (result,) = search_entries(lib, "abstract:needle")

    excerpt = result.matches[0].excerpt
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert "needle" in excerpt
    assert len(excerpt) < len(long_abstract)


def test_exact_matches_outrank_fuzzy_ones_within_a_tier() -> None:
    lib = parse_bib(
        "@article{Fuzzy,\n  title = {Widgts and Gadgets}\n}\n\n"
        "@article{Exact,\n  title = {Widgets and Gadgets}\n}\n"
    )

    results = search_entries(lib, "widgets", fuzzy=True)

    assert [result.key for result in results] == ["Exact", "Fuzzy"]


def test_result_dict_carries_score_and_matches() -> None:
    lib = parse_bib(_LIB)

    payload = search_entries(lib, "title:manual")[0].to_dict()

    assert payload["score"] == 1.0
    assert payload["matches"] == [
        {
            "field": "title",
            "term": "manual",
            "kind": "exact",
            "score": 1.0,
            "excerpt": "Manual Widgets",
        }
    ]


def test_where_selects_the_entries_searched() -> None:
    lib = parse_bib(_LIB)

    results = search_entries(lib, "widgets", where=parse_query("year >= 2024"))

    assert [result.key for result in results] == ["Alpha2024"]
