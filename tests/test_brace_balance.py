"""User-supplied values with unbalanced braces are refused before staging."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes._text_utils import unbalanced_brace
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app

runner = CliRunner()

SOURCE = (
    "@comment{pynakes-meta:\n"
    "group-tree: Physics||2||1||StaticGroup|||0|||\n"
    "}\n\n"
    "@book{Newton1687,\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  groups = {Physics},\n"
    "}\n"
)

BAD = "Laws of {Motion"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", None),
        ("{Balanced} {nested {deep}}", None),
        (r"escaped \{ pair \}", None),
        ("open { only", "{"),
        ("close } only", "}"),
        ("} reversed {", "}"),
        # The parser counts an escaped brace like any other, as BibTeX does.
        (r"escaped \{ alone", "{"),
    ],
)
def test_unbalanced_brace_mirrors_the_parser(value: str, expected: str | None) -> None:
    assert unbalanced_brace(value) == expected
    text = "@misc{K, title = {" + value + "}}\n"
    if expected is None:
        assert parse_bib(text).entries["K"].fields["title"] == value
    else:
        with pytest.raises(Exception):  # noqa: B017 - any parse failure will do
            reparsed = parse_bib(text)
            assert reparsed.entries["K"].fields["title"] == value


COMMANDS = {
    "fields set": ["fields", "set", "{bib}", "title", BAD],
    "fields append": ["fields", "append", "{bib}", "keywords", BAD],
    "ref add --field": [
        "ref",
        "add",
        "{bib}",
        "Euler1748",
        "--type",
        "book",
        "--field",
        f"title={BAD}",
    ],
    "ref edit --field": ["ref", "edit", "{bib}", "Newton1687", "--field", f"title={BAD}"],
    "corpus batch fields.set": [
        "corpus",
        "batch",
        "{bib}",
        "--ops",
        json.dumps(
            [
                {"op": "fields.set", "field": "note", "value": "fine"},
                {"op": "fields.set", "field": "title", "value": BAD},
            ]
        ),
    ],
    "corpus batch ref.edit": [
        "corpus",
        "batch",
        "{bib}",
        "--ops",
        json.dumps([{"op": "ref.edit", "key": "Newton1687", "fields": {"title": BAD}}]),
    ],
    "corpus batch metadata.set": [
        "corpus",
        "batch",
        "{bib}",
        "--ops",
        json.dumps([{"op": "metadata.set", "key": "tex-sources", "value": "{paper.tex"}]),
    ],
    "groups add-entry": [
        "groups",
        "add-entry",
        "{bib}",
        "Newton1687",
        "{Mechanics",
        "--create",
    ],
    "groups add-group": ["groups", "add-group", "{bib}", "Mechanics}"],
    "groups rename-group": ["groups", "rename-group", "{bib}", "Physics", "{Physics"],
    "groups update-group": [
        "groups",
        "update-group",
        "{bib}",
        "Physics",
        "--description",
        "Classical {mechanics",
    ],
    "metadata set": ["metadata", "set", "{bib}", "tex-sources", "paper}.tex"],
}


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_unbalanced_value_is_refused_before_anything_is_written(name: str, tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(SOURCE, encoding="utf-8")
    args = [arg.replace("{bib}", str(bib)) if arg == "{bib}" else arg for arg in COMMANDS[name]]

    result = runner.invoke(app, [*args, "--json"])

    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert data["error"] == "InvalidInput"
    assert "unmatched" in data["message"]
    assert bib.read_text(encoding="utf-8") == SOURCE


def test_balanced_and_escaped_pairs_are_still_accepted(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(SOURCE, encoding="utf-8")
    value = r"Laws of {Motion} with \{ and \}"

    result = runner.invoke(app, ["fields", "set", str(bib), "title", value, "--json"])

    assert result.exit_code == 0, result.output
    assert parse_bib(bib.read_text(encoding="utf-8")).entries["Newton1687"].fields["title"] == value
