"""Tests for `ref comment`: free-text `%` lines attached above an entry."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.canonical import write_bib_canonical
from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.normalize import sort_entries

runner = CliRunner()

NEWTON = (
    "@book{Newton1687,\n"
    "  author = {Newton, Isaac},\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  year = {1687}\n"
    "}\n"
)
DARWIN = (
    "@article{Darwin1858,\n"
    "  author = {Darwin, Charles},\n"
    "  title = {On the Tendency of Species to Form Varieties},\n"
    "  year = {1858}\n"
    "}\n"
)
REMARK = "checked against the first edition"


def _open(tmp_path: Path, text: str) -> Bibliography:
    path = tmp_path / "refs.bib"
    path.write_bytes(text.encode("utf-8"))
    return Bibliography.open(path)


@pytest.mark.parametrize("le", ["\n", "\r\n"])
def test_adding_a_comment_inserts_one_line_and_nothing_else(tmp_path: Path, le: str) -> None:
    source = (NEWTON + "\n" + DARWIN).replace("\n", le)
    coll = _open(tmp_path, source)

    assert coll.add_entry_comment("Darwin1858", REMARK)

    expected = source.replace("@article{Darwin1858", f"% {REMARK}{le}@article{{Darwin1858")
    assert coll.preview() == expected
    coll.commit()
    assert (tmp_path / "refs.bib").read_bytes() == expected.encode("utf-8")
    reopened = Bibliography.open(tmp_path / "refs.bib")
    assert [text for _slot, text in reopened.entry_comments("Darwin1858")] == [REMARK]
    assert reopened.entry_comments("Newton1687") == []
    # Not repeated.
    assert not reopened.add_entry_comment("Darwin1858", f"  {REMARK} ")


@pytest.mark.parametrize("le", ["\n", "\r\n"])
def test_comments_and_directives_are_told_apart(tmp_path: Path, le: str) -> None:
    source = ("% pynakes: ignore missing_doi\n@comment{an older remark}\n" + NEWTON).replace(
        "\n", le
    )
    coll = _open(tmp_path, source)

    assert [text for _slot, text in coll.entry_comments("Newton1687")] == ["an older remark"]
    assert coll.remove_entry_comment("Newton1687", "an older remark") == 1
    assert coll.preview() == ("% pynakes: ignore missing_doi\n" + NEWTON).replace("\n", le)
    assert [d.verb for d in coll.entry_directives("Newton1687")] == ["ignore"]


def test_a_comment_moves_with_its_entry_and_scrub_removes_it(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text(NEWTON + "\n" + DARWIN, encoding="utf-8")
    result = runner.invoke(app, ["ref", "comment", str(path), REMARK, "--key", "Newton1687"])
    assert result.exit_code == 0, result.output

    lib = parse_bib(path.read_text(encoding="utf-8"))
    sort_entries(lib, [("key", False)])
    output = write_bib_canonical(lib)
    assert f"% {REMARK}\n@book{{Newton1687," in output
    assert output.index("Darwin1858") < output.index("Newton1687")

    public = tmp_path / "public.bib"
    result = runner.invoke(app, ["scrub", str(path), "--out", str(public)])
    assert result.exit_code == 0, result.output
    assert REMARK not in public.read_text(encoding="utf-8")


def test_cli_adds_removes_and_reports(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text(NEWTON + "\n" + DARWIN, encoding="utf-8")

    def run(*args: str) -> dict:
        result = runner.invoke(app, ["ref", "comment", str(path), *args, "--json"])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    added = run(REMARK, "--where", "year < 1800")
    assert added["keys"] == ["Newton1687"] and added["comment"] == REMARK
    assert run(REMARK, "--key", "Newton1687")["modified_entries"] == 0

    removed = run(REMARK, "--key", "Newton1687,Darwin1858", "--remove")
    assert removed["keys"] == ["Newton1687"] and removed["removed"] is True
    assert path.read_text(encoding="utf-8") == NEWTON + "\n" + DARWIN

    missing = run(REMARK, "--key", "Newton1687", "--remove")
    assert [w["type"] for w in missing["warnings"]] == ["comment_not_found"]


@pytest.mark.parametrize(
    "text",
    ["", "   ", "two\nlines", "see @book{Euler1748}", "pynakes: ignore missing_doi"],
)
def test_cli_refuses_text_that_cannot_be_a_comment(tmp_path: Path, text: str) -> None:
    path = tmp_path / "refs.bib"
    path.write_text(NEWTON, encoding="utf-8")

    result = runner.invoke(app, ["ref", "comment", str(path), text, "--key", "Newton1687"])

    assert result.exit_code == 1
    assert "InvalidInput" in result.output
    assert path.read_text(encoding="utf-8") == NEWTON


def test_cli_needs_a_selection(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text(NEWTON, encoding="utf-8")

    result = runner.invoke(app, ["ref", "comment", str(path), REMARK])

    assert result.exit_code == 1
    assert "--key" in result.output
