"""`ref import IDENTIFIER=KEY`: naming citation keys for imported references."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import importer as importer_ops
from pynakes.cli import app

runner = CliRunner()


def _record(doi: str, title: str) -> str:
    return (
        "@article{Provider,\n"
        "  author = {Ada Lovelace},\n"
        f"  title = {{{title}}},\n"
        "  journal = {Notes},\n"
        "  year = {1843},\n"
        f"  doi = {{{doi}}}\n"
        "}\n"
    )


@pytest.fixture
def bib(tmp_path: Path, monkeypatch) -> Path:
    known = {
        "10.5555/one": _record("10.5555/one", "First Work"),
        "10.5555/two": _record("10.5555/two", "Second Work"),
    }

    def fetch(doi: str) -> str:
        if doi not in known:
            raise importer_ops.ReferenceImportError(f"DOI not found: {doi}")
        return known[doi]

    monkeypatch.setattr(importer_ops, "fetch_bibtex_for_doi", fetch)
    path = tmp_path / "refs.bib"
    path.write_text("@article{Taken1900, title={Already Here}, year={1900}}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("arXiv:2301.00001=Lovelace1843", ("arXiv:2301.00001", "Lovelace1843")),
        ("10.5555/one=Babbage1822", ("10.5555/one", "Babbage1822")),
        ("  10.5555/one = Babbage1822  ", ("10.5555/one", "Babbage1822")),
        ("PMID:12345678=Snow1855", ("PMID:12345678", "Snow1855")),
        ("10.5555/one", ("10.5555/one", None)),
        # A key starts with a letter, so a DOI ending in "=1" stays one DOI.
        ("10.5555/x=1", ("10.5555/x=1", None)),
        # The text before "=" must be an identifier on its own.
        ("not-an-identifier=Key1900", ("not-an-identifier=Key1900", None)),
        # An "=" after a URL query-parameter name belongs to the URL.
        (
            "https://arxiv.org/abs/2301.00001?context=physics",
            ("https://arxiv.org/abs/2301.00001?context=physics", None),
        ),
        (
            "https://arxiv.org/abs/2301.00001?context=physics=Lovelace1843",
            ("https://arxiv.org/abs/2301.00001?context=physics", "Lovelace1843"),
        ),
    ],
)
def test_split_identifier_key(value: str, expected: tuple[str, str | None]) -> None:
    assert importer_ops.split_identifier_key(value) == expected


def test_several_identifiers_take_their_named_keys(bib: Path) -> None:
    result = runner.invoke(
        app,
        ["ref", "import", str(bib), "10.5555/one=Lovelace1843", "10.5555/two", "--json"],
    )

    assert result.exit_code == 0, result.output
    results = json.loads(result.output)["results"]
    assert results[0]["key"] == "Lovelace1843"
    assert results[0]["key_source"] == "user"
    assert results[1]["key_source"] == "generated"
    assert "@article{Lovelace1843," in bib.read_text(encoding="utf-8")


def test_piped_lines_can_name_keys(bib: Path) -> None:
    result = runner.invoke(
        app,
        ["ref", "import", str(bib), "-", "--json"],
        input="10.5555/one = Lovelace1843\n10.5555/two=Babbage1822\n",
    )

    assert result.exit_code == 0, result.output
    text = bib.read_text(encoding="utf-8")
    assert "@article{Lovelace1843," in text
    assert "@article{Babbage1822," in text


def test_a_taken_key_fails_only_its_identifier(bib: Path) -> None:
    result = runner.invoke(
        app,
        ["ref", "import", str(bib), "10.5555/one=Taken1900", "10.5555/two", "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["imported"] == 1
    failed = data["results"][0]
    assert failed["status"] == "failed"
    assert failed["reason"] == "key_conflict"
    assert failed["key"] == "Taken1900"
    assert bib.read_text(encoding="utf-8").count("@article{Taken1900,") == 1


def test_a_single_pair_names_the_key(bib: Path) -> None:
    result = runner.invoke(app, ["ref", "import", str(bib), "10.5555/one=Lovelace1843", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["key"] == "Lovelace1843"
    assert data["key_source"] == "user"


def test_key_option_and_pair_together_are_refused(bib: Path) -> None:
    original = bib.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        ["ref", "import", str(bib), "10.5555/one=Lovelace1843", "--key", "Other", "--json"],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error"] == "InvalidInput"
    assert "IDENTIFIER=KEY" in data["message"]
    assert bib.read_text(encoding="utf-8") == original
