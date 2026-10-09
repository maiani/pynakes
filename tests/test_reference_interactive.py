"""Interactive CLI tests for individual-reference creation and editing.

Interactive mode is triggered by an under-specified invocation (``ref add``
without a key, ``ref edit`` without change options) and requires an interactive
terminal. Under ``CliRunner`` stdin is never a TTY, so tests that drive prompts
force :func:`stdin_is_interactive` to report a terminal.
"""

import json

import pytest
from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()


@pytest.fixture
def terminal(monkeypatch) -> None:
    """Make the under-specified commands believe stdin is a terminal."""
    monkeypatch.setattr("pynakes.cli_commands.add.stdin_is_interactive", lambda: True)
    monkeypatch.setattr("pynakes.cli_commands.edit.stdin_is_interactive", lambda: True)


def test_bare_ref_add_starts_with_key_prompt_and_blank_generates_key(
    tmp_path, monkeypatch, terminal
) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["ref", "add"],
        input=("\n\nAda Lovelace\nNotes on the Analytical Engine\nScientific Memoirs\n1843\n"),
    )

    assert result.exit_code == 0, result.output
    assert result.output.index("Citation key") < result.output.index("Reference type")
    assert "Reference type [article]" in result.output
    assert "Generated citation key: Lovelace1843Notes" in result.output
    assert "Title:" in result.output
    text = bib.read_text()
    assert "@article{Lovelace1843Notes," in text
    assert "title = {Notes on the Analytical Engine}" in text


def test_ref_add_interactive_prompts_only_for_unsupplied_required_fields(
    tmp_path, terminal
) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")

    # Key omitted (so interactive), but the type and some required fields are
    # pre-supplied as options and must not be prompted for again.
    result = runner.invoke(
        app,
        [
            "ref",
            "add",
            "--file",
            str(bib),
            "--type",
            "article",
            "--field",
            "journal=Le Radium",
            "--field",
            "year=1911",
        ],
        input="Curie1911\nMarie Curie\nInvestigations on Radioactive Substances\n",
    )

    assert result.exit_code == 0, result.output
    assert "Author:" in result.output
    assert "Title:" in result.output
    assert "Reference type" not in result.output
    assert "Journal:" not in result.output
    assert "Year:" not in result.output
    text = bib.read_text()
    assert "@article{Curie1911," in text
    assert "author = {Marie Curie}" in text
    assert "title = {Investigations on Radioactive Substances}" in text
    assert "journal = {Le Radium}" in text
    assert "year = {1911}" in text


def test_ref_edit_interactive_uses_current_values_as_defaults(tmp_path, terminal) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Faraday1852,\n"
        "  author = {Michael Faraday},\n"
        "  title = {Experimental Researches in Electricity},\n"
        "  journal = {Philosophical Transactions},\n"
        "  year = {1852}\n"
        "}\n"
    )

    result = runner.invoke(
        app,
        ["ref", "edit", str(bib), "Faraday1852"],
        input="\n\nRevised Experimental Researches in Electricity\n\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "Reference type [article]" in result.output
    assert "Author [Michael Faraday]" in result.output
    assert "Title [Experimental Researches in Electricity]" in result.output
    assert "title = {Revised Experimental Researches in Electricity}" in bib.read_text()


def test_bare_ref_add_rejects_json(tmp_path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")

    result = runner.invoke(app, ["ref", "add", "--file", str(bib), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == "InvalidInput"
    assert "--json" in payload["message"]


def test_bare_ref_add_rejects_non_terminal_stdin(tmp_path, monkeypatch) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("")
    monkeypatch.chdir(tmp_path)
    # No `terminal` fixture: stdin_is_interactive() reports False under CliRunner.

    result = runner.invoke(app, ["ref", "add"])

    assert result.exit_code == 1, result.output
    assert "InvalidInput" in result.output
    assert "interactive terminal" in result.output


def test_bare_ref_edit_rejects_non_terminal_stdin(tmp_path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{Faraday1852,\n  title = {Electricity}\n}\n")

    result = runner.invoke(app, ["ref", "edit", str(bib), "Faraday1852"])

    assert result.exit_code == 1, result.output
    assert "InvalidInput" in result.output
    assert "interactive terminal" in result.output
