"""End-to-end workflow tests driving the CLI over real temp files.

These exercise multi-operation sequences and confirm the documented agent
contract: structured errors with the right exit codes, dry-run/actual parity,
and idempotence of normalization-style operations.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def bib(tmp_path: Path) -> Path:
    path = tmp_path / "refs.bib"
    path.write_text((FIXTURES / "simple.bib").read_text())
    return path


class TestMultiOperationSequences:
    def test_normalize_then_lint_then_convert_roundtrip(self, bib: Path) -> None:
        # normalize in place
        r = runner.invoke(app, ["normalize", str(bib)])
        assert r.exit_code == 0, r.output

        # lint stays clean
        r = runner.invoke(app, ["lint", str(bib), "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["summary"]["errors"] == 0

        # convert to biblatex, then back to bibtex
        r = runner.invoke(app, ["convert", str(bib), "--to", "biblatex"])
        assert r.exit_code == 0, r.output
        assert "journaltitle" in bib.read_text(encoding="utf-8")

        r = runner.invoke(app, ["convert", str(bib), "--to", "bibtex"])
        assert r.exit_code == 0, r.output
        assert "journaltitle" not in bib.read_text(encoding="utf-8")
        assert "journal" in bib.read_text(encoding="utf-8")

    def test_repair_then_check_keys(self, tmp_path: Path) -> None:
        path = tmp_path / "dups.bib"
        path.write_text((FIXTURES / "duplicate_entries.bib").read_text())

        runner.invoke(app, ["keys", "repair", str(path)])
        r = runner.invoke(app, ["keys", "check", str(path), "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["has_duplicates"] is False


class TestDryRunParity:
    def test_dry_run_matches_actual_then_idempotent(self, bib: Path) -> None:
        before = bib.read_text(encoding="utf-8")

        dry = runner.invoke(app, ["normalize", str(bib), "--dry-run", "--diff"])
        assert dry.exit_code == 0, dry.output
        assert bib.read_text(encoding="utf-8") == before  # dry-run never writes

        real = runner.invoke(app, ["normalize", str(bib)])
        assert real.exit_code == 0, real.output
        after = bib.read_text(encoding="utf-8")
        assert after != before  # something normalized

        # Running again is a no-op: already normalized.
        again = runner.invoke(app, ["normalize", str(bib), "--json"])
        assert json.loads(again.output)["modified"] is False
        assert bib.read_text(encoding="utf-8") == after


class TestErrorContract:
    def test_missing_file_is_structured_error(self, tmp_path: Path) -> None:
        r = runner.invoke(app, ["lint", str(tmp_path / "nope.bib"), "--json"])
        assert r.exit_code == 1
        data = json.loads(r.output)
        assert data["status"] == "error"
        assert data["error"] == "FileNotFound"

    def test_malformed_bib_is_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.bib"
        path.write_text("@article{k, title = {unterminated\n  year = {2020}\n")
        r = runner.invoke(app, ["inspect", str(path), "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["error"] == "ParseError"

    def test_invalid_where_query_is_structured_error(self, bib: Path) -> None:
        r = runner.invoke(
            app, ["fields", "rename", str(bib), "a", "b", "--where", "?!bogus", "--json"]
        )
        assert r.exit_code == 1
        assert json.loads(r.output)["status"] == "error"

    def test_unknown_convert_target_is_error(self, bib: Path) -> None:
        r = runner.invoke(app, ["convert", str(bib), "--to", "rdf", "--json"])
        assert r.exit_code == 1
        assert json.loads(r.output)["status"] == "error"

    def test_no_traceback_on_any_error(self, tmp_path: Path) -> None:
        r = runner.invoke(app, ["lint", str(tmp_path / "missing.bib")])
        assert r.exit_code == 1
        assert "Traceback" not in r.output
