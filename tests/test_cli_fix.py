"""Configured fixer, multi-file normalization, and their write safeguards."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.engine import Bibliography

runner = CliRunner()
SOURCE = "@misc{ChosenKey,author={Newton, Isaac},title={Principia},year={1687},doi={https://doi.org/10.1234/example}}\n"


def library(tmp_path: Path, name: str = "refs.bib", settings: str = "") -> Path:
    path = tmp_path / name
    path.write_text(f"@comment{{pynakes-meta:\nnormalize-dois: true\n{settings}\n}}\n" + SOURCE)
    return path


def run(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.output)


def test_fix_previews_then_applies_both_phases_idempotently(tmp_path: Path) -> None:
    path = library(tmp_path)
    before = path.read_bytes()
    code, preview = run("fix", str(path), "--dry-run", "--diff")
    assert code == 0 and preview["modified"]
    assert preview["operations"]["dois"] == 1
    assert "+  doi = {10.1234/example}," in preview["diff"]
    assert path.read_bytes() == before
    code, applied = run("fix", str(path), "--expect-sha256", preview["source_sha256"])
    assert code == 0 and applied["modified"]
    assert "@misc{ChosenKey," in path.read_text()
    assert "https://doi.org/" not in path.read_text()
    formatted = path.read_bytes()
    code, again = run("fix", str(path))
    assert code == 0 and not again["modified"]
    assert path.read_bytes() == formatted


def test_fix_mode_settings_and_flag_override_both_directions(tmp_path: Path) -> None:
    first = library(tmp_path, "first.bib", "fix-mode: layout-only")
    second = library(tmp_path, "second.bib")
    code, payload = run("fix", str(first), str(second))
    assert code == 0
    assert [r["mode"] for r in payload["files"]] == ["layout-only", "normalize-and-format"]
    assert "https://doi.org/" in first.read_text()
    assert "https://doi.org/" not in second.read_text()
    assert run("fix", str(first), "--mode", "normalize-and-format")[0] == 0
    assert "https://doi.org/" not in first.read_text()
    second = library(tmp_path, "second.bib")
    assert run("fix", str(second), "--mode", "layout-only")[0] == 0
    assert "https://doi.org/" in second.read_text()


def test_fix_mode_is_editable_and_validated(tmp_path: Path) -> None:
    path = library(tmp_path)
    assert run("metadata", "set", str(path), "fix-mode", "layout-only")[0] == 0
    code, result = run("fix", str(path))
    assert code == 0 and result["mode"] == "layout-only"
    assert run("metadata", "set", str(path), "fix-mode", "invalid")[0] == 1


def test_fix_api_stages_without_writing(tmp_path: Path) -> None:
    path = library(tmp_path)
    before = path.read_bytes()
    coll = Bibliography.open(path)
    report = coll.fix()
    assert report is not None and report.dois == 1
    assert "https://doi.org/" not in coll.preview()
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="Invalid fix mode"):
        coll.fix("invalid")


def test_fix_refuses_lossy_input_and_continues_other_files(tmp_path: Path) -> None:
    broken = library(tmp_path, "broken.bib")
    broken.write_text(SOURCE.replace("title={Principia}", "title={Principia},title={Duplicate}"))
    before = broken.read_bytes()
    valid = library(tmp_path, "valid.bib")
    code, result = run("fix", str(broken), str(valid))
    assert code == 1 and result["error"] == "MultiFileError"
    assert result["files"][0]["error"] == "FormatLintError"
    assert result["files"][0]["issues"]
    assert result["files"][1]["modified"]
    assert broken.read_bytes() == before
    assert "https://doi.org/" not in valid.read_text()


@pytest.mark.parametrize("command", ["fix", "normalize"])
def test_missing_tex_safeguard_survives_multi_file_dispatch(tmp_path: Path, command: str) -> None:
    blocked = library(tmp_path, "blocked.bib", "normalize-keys: true\ntex-sources: absent.tex")
    valid = library(tmp_path, "valid.bib")
    before = blocked.read_bytes()
    code, result = run(command, str(blocked), str(valid))
    assert code == 1
    assert result["files"][0]["error"] == "MissingTexSource"
    assert result["files"][0]["sources"] == [str(tmp_path / "absent.tex")]
    assert result["files"][1]["modified"]
    assert blocked.read_bytes() == before


def test_configured_key_rename_updates_linked_tex(tmp_path: Path) -> None:
    path = library(tmp_path, settings="normalize-keys: true\ntex-sources: paper.tex")
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\cite{ChosenKey}")
    assert run("fix", str(path), "--dry-run")[0] == 0
    assert tex.read_text() == r"\cite{ChosenKey}"
    code, payload = run("fix", str(path))
    assert code == 0 and payload["operations"]["keys"] == 1
    assert tex.read_text() == r"\cite{Newton1687Principia}"


def test_normalize_many_profiles_preview_errors_and_single_envelope(tmp_path: Path) -> None:
    first = library(tmp_path, "first.bib")
    second = library(tmp_path, "second.bib")
    second.write_text(second.read_text().replace("normalize-dois: true", "normalize-dois: false"))
    before = [p.read_bytes() for p in (first, second)]
    code, result = run(
        "normalize", str(first), str(second), "--only", "dois", "--dry-run", "--diff"
    )
    assert code == 0
    assert [r["operations"]["dois"] for r in result["files"]] == [1, 0]
    assert result["files"][0]["diff"]
    assert [p.read_bytes() for p in (first, second)] == before
    code, result = run("normalize", str(tmp_path / "missing.bib"), str(first), "--only", "dois")
    assert code == 1 and result["files"][0]["error"] == "FileNotFound"
    assert result["files"][1]["modified"]
    code, single = run("normalize", str(first))
    assert code == 0 and "files" not in single


@pytest.mark.parametrize("command", ["fix", "normalize"])
def test_multi_digest_rejected_before_any_write(tmp_path: Path, command: str) -> None:
    first = library(tmp_path, "first.bib")
    second = library(tmp_path, "second.bib")
    before = [p.read_bytes() for p in (first, second)]
    code, result = run(command, str(first), str(second), "--expect-sha256", "0" * 64)
    assert code == 1 and result["error"] == "InvalidInput"
    assert [p.read_bytes() for p in (first, second)] == before


def test_fix_stale_digest_is_a_conflict_and_leaves_source_unchanged(tmp_path: Path) -> None:
    path = library(tmp_path)
    before = path.read_bytes()
    code, result = run("fix", str(path), "--expect-sha256", "0" * 64)
    assert code == 2 and result["status"] == "conflict" and result["options"]
    assert path.read_bytes() == before


def test_multi_conflicts_keep_exit_two_and_options(tmp_path: Path, monkeypatch) -> None:
    from pynakes.engine import ExternalModificationError

    first = library(tmp_path, "first.bib")
    second = library(tmp_path, "second.bib")
    original_commit = Bibliography.commit

    def guarded_commit(self, *args, **kwargs):
        if self.path == first:
            raise ExternalModificationError(first)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(Bibliography, "commit", guarded_commit)
    before = first.read_bytes()
    code, result = run("fix", str(first), str(second))
    assert code == 2 and result["status"] == "conflict"
    assert result["files"][0]["error"] == "ExternalModification"
    assert result["options"][0]["options"]
    assert result["files"][1]["modified"]
    assert first.read_bytes() == before
    # A subsequent ordinary command emits normally after the collector resets.
    assert run("fix", str(second))[0] == 0
