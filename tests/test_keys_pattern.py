"""Inferring a library's citation-key pattern: `keys pattern` and the import hint."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import importer as importer_ops
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.keys import infer_key_pattern

runner = CliRunner()

WORKS = (
    ("Newton", "Isaac", "Philosophiae Naturalis Principia Mathematica", "1687"),
    ("Euler", "Leonhard", "Introductio in Analysin Infinitorum", "1748"),
    ("Gauss", "Carl Friedrich", "Disquisitiones Arithmeticae", "1801"),
)


def _library(keys: list[str], extra: str = "") -> str:
    entries = [
        f"@article{{{key}, author={{{last}, {first}}}, title={{{title}}}, year={{{year}}}}}\n"
        for key, (last, first, title, year) in zip(keys, WORKS, strict=True)
    ]
    return extra + "".join(entries)


@pytest.mark.parametrize(
    ("keys", "pattern"),
    [
        (
            ["Newton1687Philosophiae", "Euler1748Introductio", "Gauss1801Disquisitiones"],
            "[Auth][year][Veryshorttitle]",
        ),
        (
            [
                "Newton1687PhilosophiaeNaturalis",
                "Euler1748IntroductioIn",
                "Gauss1801DisquisitionesArithmeticae",
            ],
            "[Auth][year][Camel2]",
        ),
        (["newton1687", "euler1748", "gauss1801"], "[auth][year]"),
        # A disambiguating letter suffix still matches the pattern.
        (["Newton1687a", "Euler1748", "Gauss1801b"], "[Auth][year]"),
    ],
)
def test_infers_the_pattern_most_keys_follow(keys: list[str], pattern: str) -> None:
    inference = infer_key_pattern(parse_bib(_library(keys)))

    assert inference.pattern == pattern
    assert inference.matched == inference.checked == 3


def test_mixed_keys_infer_no_pattern() -> None:
    inference = infer_key_pattern(parse_bib(_library(["Newton1687", "euler-1748", "G1801"])))

    assert inference.pattern is None
    assert inference.matched == 0
    assert inference.checked == 3


def test_too_few_entries_infer_no_pattern() -> None:
    source = "@article{Newton1687, author={Newton, Isaac}, title={Principia}, year={1687}}\n"

    assert infer_key_pattern(parse_bib(source)).pattern is None


def test_entries_with_nothing_to_build_a_key_from_are_not_counted() -> None:
    source = _library(["newton1687", "euler1748", "gauss1801"]) + "@misc{SM, note={See below}}\n"

    inference = infer_key_pattern(parse_bib(source))

    assert inference.checked == 3
    assert inference.pattern == "[auth][year]"


def test_keys_pattern_reports_and_suggests(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(_library(["newton1687", "euler1748", "gauss1801"]), encoding="utf-8")

    result = runner.invoke(app, ["keys", "pattern", str(bib), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["configured"] is None
    assert data["inferred"]["pattern"] == "[auth][year]"
    assert data["suggestion"] == f"pynakes metadata set {bib} key-pattern '[auth][year]'"


def test_keys_pattern_with_a_stored_pattern_suggests_nothing(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    meta = "@comment{pynakes-meta: key-pattern: [auth][year];}\n\n"
    bib.write_text(_library(["newton1687", "euler1748", "gauss1801"], meta), encoding="utf-8")

    data = json.loads(runner.invoke(app, ["keys", "pattern", str(bib), "--json"]).output)

    assert data["configured"] == "[auth][year]"
    assert data["suggestion"] is None


@pytest.fixture
def lowercase_library(tmp_path: Path, monkeypatch) -> Path:
    record = (
        "@article{Provider, author = {Lovelace, Ada}, title = {Notes on the Engine},"
        " journal = {Notes}, year = {1843}, doi = {10.5555/notes}}\n"
    )
    monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", lambda doi: record)
    bib = tmp_path / "refs.bib"
    bib.write_text(_library(["newton1687", "euler1748", "gauss1801"]), encoding="utf-8")
    return bib


def test_import_warns_when_generated_keys_ignore_the_library_style(
    lowercase_library: Path,
) -> None:
    result = runner.invoke(
        app, ["ref", "import", str(lowercase_library), "10.5555/notes", "--json"]
    )

    assert result.exit_code == 0, result.output
    warning = next(w for w in json.loads(result.output)["warnings"])
    assert warning["type"] == "key_pattern_unset"
    assert warning["pattern"] == "[auth][year]"
    assert "metadata set" in warning["message"]


def test_import_with_a_named_key_does_not_warn(lowercase_library: Path) -> None:
    result = runner.invoke(
        app, ["ref", "import", str(lowercase_library), "10.5555/notes=lovelace1843", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["warnings"] == []


def test_import_following_a_stored_pattern_does_not_warn(lowercase_library: Path) -> None:
    text = lowercase_library.read_text(encoding="utf-8")
    lowercase_library.write_text(
        "@comment{pynakes-meta: key-pattern: [auth][year];}\n\n" + text, encoding="utf-8"
    )

    result = runner.invoke(
        app, ["ref", "import", str(lowercase_library), "10.5555/notes", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["warnings"] == []
    assert data["key"] == "lovelace1843"
