"""CSL-JSON and RIS interchange (import/export) tests."""

import json

from pynakes.bibtex_parser import parse_bib
from pynakes.interchange import export_library, import_library

_SRC = (
    "@article{Smith2020, author = {Smith, John and Doe, Jane}, title = {A Study},\n"
    "  journal = {Journal of Examples}, year = {2020}, volume = {5}, number = {2},\n"
    "  pages = {10--20}, doi = {10.1/x}, month = {mar}}\n"
    "@incollection{Roe2019, author = {Roe, R.}, editor = {Ed, E.}, title = {A Chapter},\n"
    "  booktitle = {Big Book}, publisher = {Press}, year = {2019}}\n"
)


def test_csl_json_export_shape() -> None:
    items = json.loads(export_library(parse_bib(_SRC), "csl-json"))
    article = next(i for i in items if i["id"] == "Smith2020")
    assert article["type"] == "article-journal"
    assert article["container-title"] == "Journal of Examples"
    assert article["page"] == "10-20"
    assert article["issue"] == "2"
    assert article["author"] == [
        {"family": "Smith", "given": "John"},
        {"family": "Doe", "given": "Jane"},
    ]
    assert article["issued"] == {"date-parts": [[2020, 3]]}
    chapter = next(i for i in items if i["id"] == "Roe2019")
    assert chapter["type"] == "chapter"
    assert chapter["container-title"] == "Big Book"  # booktitle -> container-title


def test_csl_json_round_trip_preserves_core_fields() -> None:
    csl = export_library(parse_bib(_SRC), "csl-json")
    lib = import_library(csl, "csl-json")
    article = lib.entries["Smith2020"]
    assert article.type == "article"
    assert article.fields["journal"] == "Journal of Examples"  # container -> journal
    assert article.fields["pages"] == "10--20"
    assert article.fields["author"] == "Smith, John and Doe, Jane"
    assert article.fields["year"] == "2020"
    # A chapter's container-title comes back as booktitle, not journal.
    chapter = lib.entries["Roe2019"]
    assert chapter.type == "incollection"
    assert chapter.fields["booktitle"] == "Big Book"
    assert "journal" not in chapter.fields


def test_ris_export_shape() -> None:
    ris = export_library(parse_bib(_SRC), "ris")
    record = ris.split("\n\n")[0].splitlines()
    assert record[0] == "TY  - JOUR"
    assert "AU  - Smith, John" in record
    assert "AU  - Doe, Jane" in record
    assert "JO  - Journal of Examples" in record
    assert "SP  - 10" in record and "EP  - 20" in record
    assert "PY  - 2020" in record
    assert record[-1] == "ER  - "


def test_ris_round_trip_preserves_core_fields() -> None:
    ris = export_library(parse_bib(_SRC), "ris")
    lib = import_library(ris, "ris")
    entries = list(lib.entries.values())
    article = next(e for e in entries if e.type == "article")
    assert article.fields["journal"] == "Journal of Examples"
    assert article.fields["author"] == "Smith, John and Doe, Jane"
    assert article.fields["pages"] == "10--20"
    assert article.fields["year"] == "2020"
    chapter = next(e for e in entries if e.type == "incollection")
    assert chapter.fields["booktitle"] == "Big Book"
    assert chapter.fields["editor"] == "Ed, E."


def test_import_assigns_unique_keys() -> None:
    ris = "TY  - JOUR\nTI  - X\nPY  - 2020\nER  - \n\nTY  - JOUR\nTI  - X\nPY  - 2020\nER  - \n"
    lib = import_library(ris, "ris")
    keys = [e.key for e in lib.entries.values()]
    assert len(keys) == 2
    assert len(set(keys)) == 2  # no collision


def test_empty_input_is_tolerated() -> None:
    assert list(import_library("", "csl-json").entries.values()) == []
    assert list(import_library("", "ris").entries.values()) == []
    assert export_library(parse_bib(""), "ris") == ""
    assert export_library(parse_bib(""), "csl-json") == "[]"
