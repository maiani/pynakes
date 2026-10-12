"""CLI overwrite, conversion, output-stream, and multi-file error contracts."""

import hashlib
import json

import pytest
from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.cli_errors import CATALOGUE
from pynakes.io import encode_text

runner = CliRunner()
LIBRARY = "@book{Newton1687,title={Principia},year={1687}}\n"


@pytest.mark.parametrize(
    "args",
    [
        ["format", "{bib}", "--out", "{out}"],
        ["scrub", "{bib}", "--out", "{out}"],
        ["convert", "{bib}", "--to", "ris", "--out", "{out}"],
        ["convert", "{ris}", "--from", "ris", "--out", "{out}"],
        ["tex", "scan", "{bib}", "{tex}", "--out", "{out}"],
        ["corpus", "combine", "{bib}", "{other}", "--out", "{out}"],
        ["corpus", "split", "{bib}", "--route", "{out}=*"],
        ["init", "{out}"],
    ],
)
def test_each_output_command_requires_force_to_replace(tmp_path, args):
    bib = tmp_path / "refs.bib"
    other = tmp_path / "other.bib"
    tex = tmp_path / "paper.tex"
    ris = tmp_path / "refs.ris"
    out = tmp_path / "out.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    other.write_text("@book{Hooke1665,title={Micrographia}}", encoding="utf-8")
    tex.write_text(r"\cite{Newton1687}", encoding="utf-8")
    ris.write_text("TY  - BOOK\nTI  - Principia\nPY  - 1687\nER  -\n", encoding="utf-8")
    out.write_text("existing output", encoding="utf-8")
    argv = [arg.format(bib=bib, other=other, tex=tex, ris=ris, out=out) for arg in args]
    result = runner.invoke(app, [*argv, "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error"] == "FileExists"
    assert out.read_text(encoding="utf-8") == "existing output"
    result = runner.invoke(app, [*argv, "--force", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "success"
    assert out.read_text(encoding="utf-8") != "existing output"
    assert bib.read_text(encoding="utf-8") == LIBRARY


@pytest.mark.parametrize("encoding", ["latin-1", "utf-16-le", "utf-8-sig"])
def test_conversion_import_diff_and_digest_use_exact_source_bytes(tmp_path, encoding):
    source = tmp_path / "source.ris"
    source.write_bytes(encode_text("TY  - BOOK\nTI  - Caf\u00e9\nER  -\n", encoding))
    out = tmp_path / "out.bib"
    out.write_bytes(encode_text("@book{Newton1687,title={Principia}}\r\n", encoding))
    before = out.read_bytes()
    args = [
        "convert",
        str(source),
        "--from",
        "ris",
        "--out",
        str(out),
        "--force",
        "--diff",
        "--json",
    ]
    bad = runner.invoke(app, [*args, "--expect-sha256", "0" * 64])
    assert bad.exit_code == 2, bad.output
    assert json.loads(bad.stdout)["error"] == "ExternalModification"
    assert out.read_bytes() == before
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    result = runner.invoke(app, [*args, "--expect-sha256", digest])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["source_sha256"] == digest
    assert "Principia" in data["diff"]
    assert "Caf\u00e9" in data["diff"]


def test_format_out_and_stdout_leave_input_alone(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_bytes(LIBRARY.encode("utf-8"))  # no newline translation on Windows
    out = tmp_path / "out.bib"
    result = runner.invoke(app, ["format", str(bib), "--out", str(out), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["out"] == str(out)
    streamed = runner.invoke(app, ["format", str(bib), "--out", "-"])
    assert streamed.exit_code == 0, streamed.output
    assert streamed.stdout == out.read_text(encoding="utf-8")
    assert bib.read_text(encoding="utf-8") == LIBRARY


def test_ref_remove_refuses_ambiguous_key(tmp_path):
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY * 2, encoding="utf-8")
    result = runner.invoke(app, ["ref", "remove", str(bib), "Newton1687", "--json"])
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["error"] == "DuplicateCitationKey"
    assert bib.read_text(encoding="utf-8") == LIBRARY * 2


@pytest.mark.parametrize(
    "family", [["lint"], ["verify"], ["keys", "check"], ["dedupe", "check"], ["asset", "check"]]
)
def test_multi_file_failures_use_catalogued_codes(tmp_path, family):
    bib = tmp_path / "refs.bib"
    missing = tmp_path / "missing.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    result = runner.invoke(app, [*family, str(bib), str(missing), "--json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.stdout)
    failures = [row for row in data["files"] if row["status"] == "error"]
    assert len(failures) == 1
    assert failures[0]["error"] in CATALOGUE
    assert failures[0]["error"] == "FileNotFound"


@pytest.mark.parametrize(
    "command",
    [
        ["format", "--alignment", "unknown"],
        ["convert", "--to", "unknown"],
        ["asset", "fetch", "--material", "unknown"],
        ["ref", "import", "10.5555/invented", "--key-source", "unknown"],
    ],
)
def test_invalid_option_values_are_json_errors(tmp_path, command):
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    split = 2 if command[0] in {"ref", "asset"} else 1
    result = runner.invoke(app, [*command[:split], str(bib), *command[split:], "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error"] == "UsageError"


def test_closed_stdout_does_not_attempt_a_second_error_envelope(tmp_path, monkeypatch):
    import pynakes.cli_common as common

    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    calls = []

    def closed(*args, **kwargs):
        calls.append(args)
        raise BrokenPipeError("closed")

    monkeypatch.setattr(common.typer, "echo", closed)
    result = runner.invoke(app, ["inspect", str(bib), "--json"])
    assert result.exit_code == 1
    assert len(calls) == 1
    assert isinstance(result.exception, SystemExit)
