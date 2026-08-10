"""Tests for compact multi-entry triage summaries."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.triage import abstract_excerpt, entry_summary


def _entry(source: str):
    return next(iter(parse_bib(source).entries.values()))


def test_summary_selects_the_documented_fields_in_order() -> None:
    entry = _entry(
        "@article{Fermi1934,\n"
        "  volume = {88},\n"
        "  doi = {10.1234/example},\n"
        "  journal = {Zeitschrift fur Physik},\n"
        "  year = {1934},\n"
        "  author = {Fermi, Enrico},\n"
        "  title = {Versuch einer Theorie der Betastrahlen},\n"
        "  pages = {161--177}\n"
        "}\n"
    )

    summary = entry_summary(entry)

    assert list(summary) == ["title", "author", "year", "journal", "doi"]
    assert summary["title"] == "Versuch einer Theorie der Betastrahlen"
    assert summary["doi"] == "10.1234/example"


def test_summary_takes_the_first_present_creator_date_and_venue() -> None:
    entry = _entry(
        "@inproceedings{Proceedings2024,\n"
        "  editor = {Blair Example},\n"
        "  date = {2024-06},\n"
        "  booktitle = {Proceedings of the Example Symposium},\n"
        "  publisher = {Example Press},\n"
        "  title = {A Contributed Chapter}\n"
        "}\n"
    )

    summary = entry_summary(entry)

    # author/year are absent, so their alternatives stand in; publisher is a
    # weaker venue than booktitle and is dropped rather than listed twice.
    assert list(summary) == ["title", "editor", "date", "booktitle"]


def test_summary_omits_absent_and_blank_fields() -> None:
    entry = _entry("@misc{Sparse,\n  title = {Only a Title},\n  note = {  }\n}\n")

    assert entry_summary(entry) == {"title": "Only a Title"}


def test_summary_reports_field_names_in_canonical_lowercase() -> None:
    entry = _entry("@article{Mixed,\n  Title = {Mixed Case Field},\n  YEAR = {1900}\n}\n")

    assert entry_summary(entry) == {"title": "Mixed Case Field", "year": "1900"}


def test_summary_accepts_an_explicit_field_mapping() -> None:
    entry = _entry("@article{Child,\n  title = {A Chapter}\n}\n")

    summary = entry_summary(entry, {"title": "A Chapter", "journal": "Inherited Journal"})

    assert summary == {"title": "A Chapter", "journal": "Inherited Journal"}


def test_requested_abstract_is_always_present_and_none_when_unstored() -> None:
    with_abstract = _entry("@article{A,\n  title = {T},\n  abstract = {Some prose.}\n}\n")
    without = _entry("@article{B,\n  title = {T}\n}\n")

    assert entry_summary(with_abstract, include_abstract=True)["abstract"] == "Some prose."
    assert entry_summary(without, include_abstract=True)["abstract"] is None
    assert "abstract" not in entry_summary(with_abstract)


def test_excerpt_collapses_whitespace_and_cuts_at_the_limit() -> None:
    assert abstract_excerpt("one   two\n  three") == "one two three"
    assert abstract_excerpt("abcdefghij", limit=4) == "abcd…"
    assert abstract_excerpt("ab cdefgh", limit=3) == "ab…"
    assert abstract_excerpt("exactly", limit=7) == "exactly"


def test_excerpt_handles_absent_values_and_rejects_a_negative_limit() -> None:
    assert abstract_excerpt(None) == ""
    assert abstract_excerpt("   ") == ""
    with pytest.raises(ValueError):
        abstract_excerpt("text", limit=-1)
