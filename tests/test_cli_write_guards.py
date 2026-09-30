"""Commands never destroy their own input, never claim a failed write, and never
print a traceback.

These guard the 0.6.5 stop-ship fixes at the CLI boundary: an output path that
names an input is refused before anything is written, a write that failed is
reported as an error, and unexpected failures still arrive as JSON.
"""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()

LIBRARY = "@article{Euler1748,\n  title = {Introductio},\n  year = {1748}\n}\n"

_needs_posix_permissions = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions enforced for this user",
)


def _library(tmp_path: Path) -> Path:
    bib = tmp_path / "lib.bib"
    bib.write_text(LIBRARY)
    return bib


def _error(result) -> dict:
    assert "Traceback" not in result.output
    return json.loads(result.output)


@pytest.mark.parametrize(
    "args",
    [
        ["convert", "{bib}", "--to", "ris", "--out", "{bib}"],
        ["tex", "scan", "{bib}", "{tex}", "--out", "{bib}"],
        ["tex", "scan", "{bib}", "{tex}", "--out", "{tex}"],
        ["corpus", "split", "{bib}", "--to", "{bib}=*"],
    ],
)
def test_output_naming_an_input_is_refused(tmp_path: Path, args: list[str]) -> None:
    bib = _library(tmp_path)
    tex = tmp_path / "paper.tex"
    tex.write_text("\\cite{Euler1748}\n")
    argv = [a.format(bib=bib, tex=tex) for a in args]

    result = runner.invoke(app, [*argv, "--json"])

    assert result.exit_code == 1, result.output
    assert _error(result)["error"] == "OutputIsInput"
    assert bib.read_text() == LIBRARY
    assert tex.read_text() == "\\cite{Euler1748}\n"


@_needs_posix_permissions
@pytest.mark.parametrize(
    "args",
    [
        ["convert", "{bib}", "--to", "ris", "--out", "{out}/x.ris"],
        ["tex", "scan", "{bib}", "{tex}", "--out", "{out}/used.bib"],
        ["corpus", "split", "{bib}", "--to", "{out}/all.bib=*"],
    ],
)
def test_a_failed_write_is_an_error_not_a_success(tmp_path: Path, args: list[str]) -> None:
    bib = _library(tmp_path)
    tex = tmp_path / "paper.tex"
    tex.write_text("\\cite{Euler1748}\n")
    out = tmp_path / "locked"
    out.mkdir()
    out.chmod(0o555)
    argv = [a.format(bib=bib, tex=tex, out=out) for a in args]

    try:
        result = runner.invoke(app, [*argv, "--json"])
    finally:
        out.chmod(0o755)

    assert result.exit_code == 1, result.output
    assert _error(result)["error"] == "IOError"
    assert list(out.iterdir()) == []


def test_malformed_import_document_is_invalid_input(tmp_path: Path) -> None:
    source = tmp_path / "bad.xml"
    source.write_text("<mods")

    result = runner.invoke(
        app, ["convert", str(source), "--from", "mods", "--out", str(tmp_path / "o.bib"), "--json"]
    )

    assert result.exit_code == 1, result.output
    assert _error(result)["error"] == "InvalidInput"


def test_dedupe_conflict_inside_a_batch_is_a_conflict(tmp_path: Path) -> None:
    bib = tmp_path / "lib.bib"
    original = (
        "@article{Euler1748,\n  title = {Introductio},\n  doi = {10.5555/euler},\n"
        "  year = {1748}\n}\n"
        "@article{Euler1748b,\n  title = {Introductio},\n  doi = {10.5555/euler},\n"
        "  year = {1797}\n}\n"
    )
    bib.write_text(original)
    ops = json.dumps([{"op": "dedupe.merge"}])

    result = runner.invoke(app, ["corpus", "batch", str(bib), "--ops", ops, "--json"])

    assert result.exit_code == 2, result.output
    assert _error(result)["error"] == "DedupeConflict"
    assert bib.read_text() == original


def test_an_unexpected_failure_is_reported_as_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bib = _library(tmp_path)

    def broken(*_args, **_kwargs):
        raise KeyError("boom")

    monkeypatch.setattr("pynakes.cli_commands.inspect.Bibliography.open", broken)

    result = runner.invoke(app, ["inspect", str(bib), "--json"])

    assert result.exit_code == 1, result.output
    data = _error(result)
    assert data["error"] == "InternalError"
    assert "KeyError" in data["message"]
