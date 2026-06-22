"""JabRef feature-parity tests (golden vectors).

The input→expected vectors below are lifted from JabRef's own formatter tests
(JabRef, MIT License),
``jablib/src/test/java/org/jabref/logic/formatter/bibtexfields/``:
``NormalizeDateFormatterTest``, ``NormalizeMonthFormatterTest``,
``NormalizePagesFormatterTest``, ``NormalizeNamesFormatterTest``.

Running JabRef itself in the suite would violate the determinism invariant (JVM,
version drift), so we capture JabRef's behavior as static golden data instead.
Parity is asserted at the field-value level — the only level where it is
meaningful, since JabRef rewrites whole files on save while pynakes preserves
them.
"""

import pytest

from pynakes.authors import normalize_name_list
from pynakes.bibtex_parser import parse_bib
from pynakes.formatters import normalize_date, normalize_month, normalize_page_numbers
from pynakes.normalize import normalize_library

# --- normalize_date --------------------------------------------------------

DATE_VECTORS = [
    ("2015-11-08", "2015-11-08"),
    ("2015-1-08", "2015-01-08"),
    ("2015-1-8", "2015-01-08"),
    ("2015-11", "2015-11"),
    ("2015-1", "2015-01"),
    ("11/15", "2015-11"),
    ("1/15", "2015-01"),
    ("01/15", "2015-01"),
    ("11/2015", "2015-11"),
    ("1/2015", "2015-01"),
    ("01/2015", "2015-01"),
    ("November 08, 2015", "2015-11-08"),
    ("November 8, 2015", "2015-11-08"),
    ("November, 2015", "2015-11"),
    ("08.11.2015", "2015-11-08"),
    ("8.11.2015", "2015-11-08"),
    ("15.11.2015", "2015-11-15"),
    ("08.01.2015", "2015-01-08"),
    ("8.01.2015", "2015-01-08"),
    ("15.01.2015", "2015-01-15"),
    ("08.1.2015", "2015-01-08"),
    ("8.1.2015", "2015-01-08"),
    ("15.1.2015", "2015-01-15"),
    ("29.11.2003", "2003-11-29"),  # getExampleInput()
    ("2020/2021", "2020/2021"),  # year range — kept
]


@pytest.mark.parametrize("value,expected", DATE_VECTORS)
def test_normalize_date_parity(value: str, expected: str) -> None:
    assert normalize_date(value) == expected


# --- normalize_month -------------------------------------------------------

MONTH_VECTORS = [
    ("December", "#dec#"),  # getExampleInput()
    ("#apr#", "#apr#"),
]


@pytest.mark.parametrize("value,expected", MONTH_VECTORS)
def test_normalize_month_parity(value: str, expected: str) -> None:
    assert normalize_month(value) == expected


# --- normalize_page_numbers ------------------------------------------------

PAGE_VECTORS = [
    ("1", "1"),
    ("1-2", "1--2"),
    ("1–2", "1--2"),  # en dash
    ("1—2", "1--2"),  # em dash
    ("1,2,3", "1,2,3"),
    ("43+", "43+"),
    ("   1  - 2 ", "1--2"),
    ("   1  ", "1"),
    ("   1 -- 2  ", "1--2"),
    ("43 -- 103", "43--103"),
    ("1--2", "1--2"),
    ("1---2", "1--2"),
    ("{1}-{2}", "1--2"),
    ("12", "12"),
    ("some-text", "some--text"),
    ("pages 1-50", "pages 1--50"),
    ("-43", "--43"),
    ("some-text-with-dashes", "some-text-with-dashes"),
    ("{A}", "{A}"),
    ("Invalid", "Invalid"),
    ("R1-R50", "R1--R50"),
    ("1 — 50", "1--50"),
    ("p.50", "50"),
    ("pp.50", "50"),
    ("40&50", "40&50"),
    ("2:1-2:33", "2:1--2:33"),
    ("2:1--2:33", "2:1--2:33"),
    ("1 - 2", "1--2"),  # getExampleInput()
    ("R404–R405", "R404--R405"),
]


@pytest.mark.parametrize("value,expected", PAGE_VECTORS)
def test_normalize_page_numbers_parity(value: str, expected: str) -> None:
    assert normalize_page_numbers(value) == expected


# --- normalize_names -------------------------------------------------------
#
# pynakes' author normalizer is NOT (yet) a full JabRef AuthorList parser. The
# vectors pynakes already satisfies are asserted; the harder ones (initials
# expansion, name affixes, LaTeX-brace names, irregular comma/semicolon layouts)
# are tracked as a 1.0 parity gap in DEVPLAN and marked xfail so closing the gap
# trips an xpass.

NAME_VECTORS_OK = [
    ("{Society of Automotive Engineers}", "{Society of Automotive Engineers}"),
    ("Hans von Zimmer", "von Zimmer, Hans"),
    ("Staci Bilbo; Morten Alver", "Bilbo, Staci and Alver, Morten"),
    ("Staci Bilbo; Morten Alver; Test Name", "Bilbo, Staci and Alver, Morten and Name, Test"),
]

NAME_VECTORS_GAP = [
    ("Staci D Bilbo", "Bilbo, Staci D."),
    ("Smith SH", "Smith, S. H."),
    ("S Smith", "Smith, S."),
    ("SH Smith", "Smith, S. H."),
    ("Surname, jr, First, Surname2, First2", "Surname, jr, First and Surname2, First2"),
    # comma-separated multi-author lists (pynakes splits only on ';'/'and')
    (
        "Hans von Zimmer, Michael van Oberbergern, Kevin zu Berger",
        "von Zimmer, Hans and van Oberbergern, Michael and zu Berger, Kevin",
    ),
]


@pytest.mark.parametrize("value,expected", NAME_VECTORS_OK)
def test_normalize_names_parity_supported(value: str, expected: str) -> None:
    assert normalize_name_list(value) == expected


@pytest.mark.xfail(reason="JabRef AuthorList-parser parity is a tracked 1.0 gap (DEVPLAN)")
@pytest.mark.parametrize("value,expected", NAME_VECTORS_GAP)
def test_normalize_names_parity_gap(value: str, expected: str) -> None:
    assert normalize_name_list(value) == expected


# --- integration: saveActions drive the field formatters -------------------


def test_normalize_applies_saveactions_field_formatters() -> None:
    text = (
        "@comment{jabref-meta: saveActions:enabled;\n"
        "date[normalize_date]\nmonth[normalize_month]\npages[normalize_page_numbers]\n;}\n\n"
        "@article{A,\n"
        "  title = {T},\n"
        "  date = {8.1.2015},\n"
        "  month = {December},\n"
        "  pages = {1 - 2}\n"
        "}\n"
    )
    lib = parse_bib(text)
    report = normalize_library(lib)

    entry = lib.entries["A"]
    assert entry.fields["date"] == "2015-01-08"
    assert entry.fields["month"] == "#dec#"
    assert entry.fields["pages"] == "1--2"
    assert report.save_action_fields == 3


def test_normalize_skips_formatters_without_saveactions() -> None:
    # No saveActions → date/month/pages are left untouched (no pynakes-meta or
    # flag drives them).
    text = "@article{A,\n  title = {T},\n  pages = {1 - 2}\n}\n"
    lib = parse_bib(text)
    normalize_library(lib)
    assert lib.entries["A"].fields["pages"] == "1 - 2"
