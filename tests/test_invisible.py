"""Invisible characters: reported by lint, removed by normalize, dropped on import."""

from pynakes._invisible import strip_invisible
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.lint import lint
from pynakes.normalize import NormalizeOptions, normalize_library
from pynakes.providers.records import ReferenceMetadata

BOM = "﻿"
ZWSP = "​"
ZWJ = "‍"

SOURCE = (
    "@article{Euler1748,\n"
    f"  title = {{Introductio in analysin{BOM} infinitorum}},\n"
    f'  note = "see{ZWSP} volume one",\n'
    f"  author = {{Leonhard Eu{ZWJ}ler}},\n"
    "  month = jan,\n"
    "}\n"
)


def test_lint_names_each_invisible_character_and_where_it_is() -> None:
    issues = [issue for issue in lint(parse_bib(SOURCE)) if issue.type == "invisible_character"]

    assert {issue.field for issue in issues} == {"title", "note"}
    title = next(issue for issue in issues if issue.field == "title")
    assert "U+FEFF ZERO WIDTH NO-BREAK SPACE at offset 23" in title.message
    assert title.to_dict()["category"] == "content"
    assert title.to_dict()["fixer"] == "normalize"


def test_normalize_removes_them_keeping_delimiters_and_other_fields() -> None:
    lib = parse_bib(SOURCE)

    report = normalize_library(lib, NormalizeOptions(only=["invisible_characters"]))

    assert report.invisible_characters == 1
    written = write_bib(lib)
    assert "title = {Introductio in analysin infinitorum}," in written
    assert 'note = "see volume one",' in written
    assert "month = jan," in written
    # The zero-width joiner is a legitimate character and stays.
    assert f"Eu{ZWJ}ler" in written


def test_an_imported_record_is_cleaned_on_the_way_in() -> None:
    record = ReferenceMetadata(
        provider="crossref",
        entry_type="article",
        fields={"title": f"Elements{BOM} of Geometry", "journal": f"Annals{ZWSP}"},
    )

    assert record.fields == {"title": "Elements of Geometry", "journal": "Annals"}


def test_visible_text_and_layout_whitespace_are_untouched() -> None:
    text = "Line one\n\tline two with café and α"
    assert strip_invisible(text) is text
