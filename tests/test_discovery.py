"""Library auto-discovery skips only REVTeX's generated <jobname>Notes.bib."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.cli_common import is_auxiliary_bib_file

runner = CliRunner()

REVTEX_NOTES = (
    "@CONTROL{REVTEX42Control}\n"
    '@CONTROL{apsrev42Control,author="08",editor="1",pages="0",title="0",year="1"}\n'
    "@Misc{Note1,\n  note = {A generated footnote.}\n}\n"
)
LIBRARY = "@book{Newton1687,\n  title = {Principia}\n}\n"


@pytest.mark.parametrize("name", ["notes.bib", "LectureNotes.bib", "fieldnotes.bib"])
def test_a_user_library_named_like_notes_is_auto_detected(
    name: str, tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / name).write_text(LIBRARY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["inspect", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["file"] == name


def test_revtex_notes_need_both_the_name_and_the_control_entry(tmp_path: Path) -> None:
    generated = tmp_path / "paperNotes.bib"
    generated.write_text(REVTEX_NOTES, encoding="utf-8")
    renamed = tmp_path / "paper-refs.bib"
    renamed.write_text(REVTEX_NOTES, encoding="utf-8")

    assert is_auxiliary_bib_file(generated)
    assert not is_auxiliary_bib_file(renamed)


def test_a_skipped_notes_file_is_named_in_the_error(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "paperNotes.bib").write_text(REVTEX_NOTES, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["inspect", "--json"])

    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["error"] == "InvalidInput"
    assert "skipped REVTeX-generated paperNotes.bib" in data["message"]
    assert "No *.bib file found" not in data["message"]


def test_a_skipped_notes_file_is_named_for_a_library_first_positional(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "paperNotes.bib").write_text(REVTEX_NOTES, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["keys", "rename", "Old1687", "New1687", "--json"])

    assert result.exit_code == 1, result.output
    assert "skipped REVTeX-generated paperNotes.bib" in json.loads(result.output)["message"]


def test_format_recursive_formats_a_user_notes_library(tmp_path: Path) -> None:
    (tmp_path / "LectureNotes.bib").write_text("@book{Newton1687,title={Principia}}\n")
    (tmp_path / "paperNotes.bib").write_text(REVTEX_NOTES, encoding="utf-8")

    result = runner.invoke(app, ["format", str(tmp_path), "--recursive", "--check", "--json"])

    assert "LectureNotes.bib" in result.output
    assert "paperNotes.bib" not in result.output
