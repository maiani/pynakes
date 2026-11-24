"""Formatting several explicit inputs and the opt-in formatter hook."""

import json
import shlex
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()
SOURCE = "@book{Newton1687,title={Principia},year={1687}}\n"


def libraries(tmp_path: Path) -> list[Path]:
    paths = [tmp_path / "first library.bib", tmp_path / "second.bib"]
    for path in paths:
        path.write_text(SOURCE)
    return paths


def test_many_profiles_and_idempotence(tmp_path: Path) -> None:
    first, second = libraries(tmp_path)
    second.write_text("@comment{pynakes-meta: format-indent: 4;}\n" + SOURCE)
    result = runner.invoke(app, ["format", str(first), str(second), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"] == {"files": 2, "modified": 2, "failed": 0}
    assert [item["file"] for item in payload["files"]] == [str(first), str(second)]
    assert "\n  title =" in first.read_text()
    assert "\n    title =" in second.read_text()
    before = [path.read_bytes() for path in (first, second)]
    again = runner.invoke(app, ["format", str(first), str(second), "--check", "--json"])
    assert again.exit_code == 0, again.output
    assert json.loads(again.output)["modified"] is False
    assert [path.read_bytes() for path in (first, second)] == before


@pytest.mark.parametrize("mode", ["--check", "--dry-run"])
def test_many_preview_is_read_only_and_includes_diffs(tmp_path: Path, mode: str) -> None:
    paths = libraries(tmp_path)
    result = runner.invoke(app, ["format", *map(str, paths), mode, "--diff", "--json"])
    assert result.exit_code == (1 if mode == "--check" else 0), result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert all(item["modified"] and item["diff"] for item in payload["files"])
    assert all(path.read_text() == SOURCE for path in paths)


def test_many_errors_continue_and_report_each_file(tmp_path: Path) -> None:
    first, second = libraries(tmp_path)
    first.write_text("@book{Newton1687,title={Principia},title={Duplicate}}\n")
    missing = tmp_path / "missing.bib"
    before = first.read_bytes()
    result = runner.invoke(app, ["format", str(first), str(missing), str(second), "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["error"] == "MultiFileFormatError"
    assert payload["summary"] == {"files": 3, "modified": 1, "failed": 2}
    assert payload["files"][0]["error"] == "FormatLintError"
    assert payload["files"][0]["issues"]
    assert payload["files"][1]["error"] == "FileNotFound"
    assert first.read_bytes() == before
    assert second.read_text() != SOURCE


@pytest.mark.parametrize(
    "options", [["--out", "-"], ["--expect-sha256", "0" * 64], ["--recursive"], ["-"]]
)
def test_many_refuses_single_input_options_before_writes(
    tmp_path: Path, options: list[str]
) -> None:
    paths = libraries(tmp_path)
    result = runner.invoke(app, ["format", *map(str, paths), *options, "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error"] == "InvalidInput"
    assert all(path.read_text() == SOURCE for path in paths)


def test_file_option_and_autodetection_still_work(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "refs.bib"
    path.write_text(SOURCE)
    monkeypatch.chdir(tmp_path)
    for args in (["--file", str(path)], []):
        result = runner.invoke(app, ["format", *args, "--check", "--json"])
        assert result.exit_code == 1, result.output
        assert "files" not in json.loads(result.output)
    assert path.read_text() == SOURCE


def test_hook_formats_multiple_paths_and_second_run_is_unchanged(tmp_path: Path) -> None:
    paths = libraries(tmp_path)
    hooks = yaml.safe_load((Path(__file__).parents[1] / ".pre-commit-hooks.yaml").read_text())
    hook = next(item for item in hooks if item["id"] == "pynakes-fix")
    args = [*shlex.split(hook["entry"])[1:], "--mode", "layout-only", *map(str, paths)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    formatted = [path.read_bytes() for path in paths]
    assert all(path.read_text() != SOURCE for path in paths)
    assert runner.invoke(app, args).exit_code == 0
    assert [path.read_bytes() for path in paths] == formatted


def test_human_output_names_failed_files_and_shows_diffs(tmp_path: Path) -> None:
    paths = libraries(tmp_path)
    missing = tmp_path / "missing.bib"
    result = runner.invoke(app, ["format", *map(str, paths), str(missing), "--dry-run", "--diff"])
    assert result.exit_code == 1
    assert str(missing) in result.output
    assert "+  title = {Principia}," in result.output
    assert all(path.read_text() == SOURCE for path in paths)
