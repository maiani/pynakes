"""Tests for the shared ``--where`` selector grammar."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.model import BibEntry
from pynakes.query import FUZZY_THRESHOLD, field_value, fuzzy_score, parse_query

_LIB = (
    "@book{Newton1687,\n"
    "  author = {Newton, Isaac},\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  year = {1687},\n"
    "  groups = {Classics; Physics}\n"
    "}\n\n"
    "@article{Euler1748,\n"
    "  author = {Euler, Leonhard},\n"
    "  title = {Introductio in Analysin Infinitorum},\n"
    "  journal = {Opera Omnia},\n"
    "  date = {1748-04-15},\n"
    "  doi = {10.0000/euler},\n"
    "  abstract = {}\n"
    "}\n"
)


def _keys(expr: str, **kwargs) -> list[str]:
    lib = parse_bib(_LIB)
    predicate = parse_query(expr, **kwargs)
    return [entry.key for entry in lib.entries.values() if predicate(entry)]


# --- single predicates -----------------------------------------------------


def test_contains_equality_and_exists_keep_working() -> None:
    assert _keys('title contains "principia"') == ["Newton1687"]
    assert _keys("type = article") == ["Euler1748"]
    assert _keys('key == "Newton1687"') == ["Newton1687"]
    assert _keys("doi exists") == ["Euler1748"]


def test_missing_covers_absent_and_empty_fields() -> None:
    # `abstract = {}` is present but empty: "entries missing an abstract"
    # must include it, which is why `missing` is not merely `not exists`.
    assert _keys("abstract missing") == ["Newton1687", "Euler1748"]
    assert _keys("abstract exists") == ["Euler1748"]


def test_inequality_is_true_for_an_absent_field() -> None:
    assert _keys('journal != "Opera Omnia"') == ["Newton1687"]


def test_numeric_comparison_orders_by_value_not_text() -> None:
    lib = parse_bib("@article{A, year={999}}\n@article{B, year={1000}}\n")
    predicate = parse_query("year > 999")
    assert [e.key for e in lib.entries.values() if predicate(e)] == ["B"]


def test_year_falls_back_to_the_date_field() -> None:
    assert _keys("year >= 1700") == ["Euler1748"]
    assert _keys("year exists") == ["Newton1687", "Euler1748"]


def test_date_range_filtering() -> None:
    assert _keys("date >= 1748-01 and date <= 1748-12") == ["Euler1748"]
    assert _keys("date >= 1749-01") == []


def test_date_falls_back_to_year_month_day() -> None:
    lib = parse_bib("@article{A, year={1900}, month={jun}, day={4}}\n")
    entry = lib.entries["A"]
    assert field_value(entry, "date") == "1900-06-04"
    assert parse_query("date >= 1900-06")(entry)
    assert not parse_query("date >= 1900-07")(entry)


def test_in_list_membership_and_negation() -> None:
    assert _keys("key in [Newton1687, Euler1748]") == ["Newton1687", "Euler1748"]
    assert _keys("type in [book]") == ["Newton1687"]
    assert _keys("type not in [book]") == ["Euler1748"]


def test_matches_is_a_regular_expression() -> None:
    assert _keys('title matches "^Introductio"') == ["Euler1748"]
    assert _keys(r'doi matches "^10\.\d+/"') == ["Euler1748"]


def test_fuzzy_operator_tolerates_misspellings() -> None:
    assert _keys('title ~ "princpia mathematica"') == ["Newton1687"]
    assert _keys('title ~ "quantum chromodynamics"') == []


def test_group_predicate_accepts_both_spellings() -> None:
    assert _keys('group "Physics"') == ["Newton1687"]
    assert _keys("group=Physics") == ["Newton1687"]
    assert _keys('group "Nonexistent"') == []


def test_used_predicates_need_cited_keys() -> None:
    assert _keys("used", cited_keys={"Euler1748"}) == ["Euler1748"]
    assert _keys("unused", cited_keys={"Euler1748"}) == ["Newton1687"]
    with pytest.raises(ValueError, match="needs cited keys"):
        parse_query("used")


def test_catch_all_matches_everything() -> None:
    assert _keys("*") == ["Newton1687", "Euler1748"]


def test_bucket_keywords_are_still_usable_as_field_names() -> None:
    # `used` is a bucket predicate only in predicate position; followed by an
    # operator it is an ordinary field, so no cited-key set is needed.
    entry = BibEntry("A", "article", {"used": "yes"})

    assert parse_query("used contains yes")(entry)
    assert parse_query("used exists")(entry)
    assert parse_query("used = yes")(entry)


def test_group_predicate_needs_a_non_empty_name() -> None:
    with pytest.raises(ValueError, match="needs a group name"):
        parse_query('group ""')


def test_date_is_absent_without_a_year() -> None:
    assert field_value(BibEntry("A", "article", {"month": "jun"}), "date") is None


def test_field_names_are_matched_case_insensitively() -> None:
    entry = BibEntry("A", "article", {"Journal": "Nature"})
    assert parse_query('journal = "nature"')(entry)


# --- boolean composition ---------------------------------------------------


def test_and_binds_tighter_than_or() -> None:
    # book and 1687, or anything with a DOI: both entries qualify, and the
    # precedence is what makes the first branch not swallow the second.
    assert _keys("type = book and year = 1687 or doi exists") == ["Newton1687", "Euler1748"]


def test_parentheses_override_precedence() -> None:
    assert _keys("type = book and (year = 1748 or doi exists)") == []


def test_not_negates_a_predicate_and_a_group() -> None:
    assert _keys("not doi exists") == ["Newton1687"]
    assert _keys('not group "Physics"') == ["Euler1748"]


def test_composed_selector_mixes_bucket_and_field_predicates() -> None:
    assert _keys("used and year >= 1700", cited_keys={"Euler1748", "Newton1687"}) == ["Euler1748"]


def test_parsed_expression_is_describable() -> None:
    described = parse_query("year >= 2025 and not type in [book]").to_dict()
    assert described == {
        "and": [
            {"field": "year", "op": ">=", "value": "2025"},
            {"not": {"field": "type", "op": "in", "values": ["book"]}},
        ]
    }


# --- errors ----------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "   ",
        "title",
        "title contains",
        "title contains a and",
        "title frobnicates x",
        "(type = book",
        "type = book)",
        'title contains "unterminated',
        "key in []",
        "key in [a",
        "group",
        "title matches (",
    ],
)
def test_malformed_expressions_raise(expr: str) -> None:
    with pytest.raises(ValueError, match="Invalid query expression"):
        parse_query(expr)


# --- fuzzy scoring ---------------------------------------------------------


def test_fuzzy_score_is_one_for_a_normalized_substring() -> None:
    assert fuzzy_score("The {DNA} Helix, Revisited", "dna helix") == 1.0


def test_fuzzy_score_rejects_short_needles() -> None:
    # A short needle would reach the threshold against almost anything by
    # similarity alone, so below the minimum length only a substring counts.
    assert fuzzy_score("Principia", "prx") == 0.0
    assert fuzzy_score("Principia", "pri") == 1.0


def test_fuzzy_score_reaches_the_threshold_for_a_misspelling() -> None:
    assert fuzzy_score("Quantum Computing", "quantom computting") >= FUZZY_THRESHOLD
    assert fuzzy_score("Quantum Computing", "medieval history") < FUZZY_THRESHOLD


# --- comparison fallbacks and descriptions ---------------------------------


def test_ordered_comparison_falls_back_to_text() -> None:
    entry = BibEntry("A", "article", {"journal": "Nature"})

    assert parse_query('journal >= "Journal of Physics"')(entry)
    assert not parse_query('journal < "Journal of Physics"')(entry)


def test_numeric_month_is_accepted_when_composing_a_date() -> None:
    entry = BibEntry("A", "article", {"year": "1900", "month": "6", "day": "4"})

    assert field_value(entry, "date") == "1900-06-04"
    # An out-of-range month is not a month, so the date stays year-only.
    assert field_value(BibEntry("B", "article", {"year": "1900", "month": "13"}), "date") == "1900"


def test_not_in_is_true_for_an_absent_field() -> None:
    entry = BibEntry("A", "article", {})

    assert parse_query("journal not in [Nature]")(entry)
    assert not parse_query("journal in [Nature]")(entry)


def test_fuzzy_score_is_zero_for_an_empty_side() -> None:
    assert fuzzy_score("", "principia") == 0.0
    assert fuzzy_score("Principia", "") == 0.0


def test_every_predicate_kind_describes_itself() -> None:
    assert parse_query("*").to_dict() == {"predicate": "*"}
    assert parse_query("used", cited_keys=set()).to_dict() == {"predicate": "used"}
    assert parse_query("unused", cited_keys=set()).to_dict() == {"predicate": "unused"}
    assert parse_query('group "ML"').to_dict() == {"predicate": "group", "name": "ML"}
    assert parse_query("doi exists or title contains x").to_dict() == {
        "or": [
            {"field": "doi", "op": "exists"},
            {"field": "title", "op": "contains", "value": "x"},
        ]
    }


@pytest.mark.parametrize(
    ("expr", "detail"),
    [
        ('title matches "(unclosed"', "Invalid regular expression"),
        ("title contains !x", "unexpected character"),
        ('"quoted" = x', "expected a field name"),
        ("title ) x", "expected an operator"),
        ("title 42", "unknown operator"),
        ("key in [a b]", "expected ']'"),
    ],
)
def test_error_messages_name_the_expression_and_the_reason(expr: str, detail: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        parse_query(expr)

    assert repr(expr) in str(excinfo.value)
    assert detail in str(excinfo.value)
