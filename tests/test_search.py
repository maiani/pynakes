"""Tests for bibliography search."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.search import parse_search_query, search_entries

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
