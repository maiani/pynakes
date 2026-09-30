"""Multi-file gate checks (``--strict``) and the pre-commit hook manifest.

These cover the CI / pre-commit surface: read-only checks run over one or many
files, ``--strict`` turning findings into a non-zero exit, the aggregate
multi-file JSON envelope, and the shipped ``.pre-commit-hooks.yaml``.
"""

import json
import shlex
from pathlib import Path

import yaml
from typer.testing import CliRunner

from pynakes.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent

# simple.bib is clean (only advisory warnings); duplicate_entries.bib has
# duplicate-key *errors*.
CLEAN = FIXTURES / "simple.bib"
WITH_ERRORS = FIXTURES / "duplicate_entries.bib"


def _bib(tmp_path: Path, name: str, src: Path) -> Path:
    dst = tmp_path / name
    dst.write_text(src.read_text())
    return dst


class TestLintStrict:
    def test_clean_file_passes_strict(self, tmp_path: Path) -> None:
        bib = _bib(tmp_path, "a.bib", CLEAN)
        # Warnings only (a missing DOI) — --strict must not fail.
        result = runner.invoke(app, ["lint", str(bib), "--strict"])
        assert result.exit_code == 0, result.output

    def test_errors_fail_strict(self, tmp_path: Path) -> None:
        bib = _bib(tmp_path, "a.bib", WITH_ERRORS)
        result = runner.invoke(app, ["lint", str(bib), "--strict"])
        assert result.exit_code == 1, result.output

    def test_errors_without_strict_still_exit_zero(self, tmp_path: Path) -> None:
        # Backward-compatible default: report, don't gate.
        bib = _bib(tmp_path, "a.bib", WITH_ERRORS)
        result = runner.invoke(app, ["lint", str(bib)])
        assert result.exit_code == 0, result.output

    def test_single_file_envelope_unchanged_by_strict(self, tmp_path: Path) -> None:
        # --strict must not alter the documented per-file envelope keys.
        bib = _bib(tmp_path, "a.bib", CLEAN)
        result = runner.invoke(app, ["lint", str(bib), "--strict", "--json"])
        data = json.loads(result.output)
        assert set(data) == {
            "status",
            "action",
            "file",
            "issue_count",
            "errors",
            "warnings",
            "info",
            "by_category",
            "issues",
        }
        assert "files" not in data  # not the aggregate shape


class TestLintMultiFile:
    def test_aggregate_envelope(self, tmp_path: Path) -> None:
        clean = _bib(tmp_path, "clean.bib", CLEAN)
        errs = _bib(tmp_path, "errs.bib", WITH_ERRORS)
        result = runner.invoke(app, ["lint", str(clean), str(errs), "--json"])
        assert result.exit_code == 0, result.output  # no --strict → exit 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["action"] == "lint"
        assert data["strict"] is False
        assert len(data["files"]) == 2
        assert {f["file"] for f in data["files"]} == {str(clean), str(errs)}
        assert data["summary"]["files"] == 2
        assert data["summary"]["failed_files"] == 1  # only errs has errors
        assert data["summary"]["errors"] >= 3

    def test_strict_fails_when_any_file_has_errors(self, tmp_path: Path) -> None:
        clean = _bib(tmp_path, "clean.bib", CLEAN)
        errs = _bib(tmp_path, "errs.bib", WITH_ERRORS)
        result = runner.invoke(app, ["lint", str(clean), str(errs), "--strict", "--json"])
        assert result.exit_code == 1, result.output
        assert json.loads(result.output)["strict"] is True

    def test_strict_passes_when_all_clean(self, tmp_path: Path) -> None:
        a = _bib(tmp_path, "a.bib", CLEAN)
        b = _bib(tmp_path, "b.bib", CLEAN)
        result = runner.invoke(app, ["lint", str(a), str(b), "--strict"])
        assert result.exit_code == 0, result.output

    def test_unreadable_file_is_error_and_fails(self, tmp_path: Path) -> None:
        clean = _bib(tmp_path, "clean.bib", CLEAN)
        missing = tmp_path / "nope.bib"
        # No --strict, but an unreadable file always fails the run.
        result = runner.invoke(app, ["lint", str(clean), str(missing), "--json"])
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["status"] == "error"
        err = next(f for f in data["files"] if f["file"] == str(missing))
        assert err["status"] == "error"
        assert err["error"] == "FileNotFoundError"
        assert data["summary"]["failed_files"] == 1

    def test_human_output_labels_each_file(self, tmp_path: Path) -> None:
        clean = _bib(tmp_path, "clean.bib", CLEAN)
        errs = _bib(tmp_path, "errs.bib", WITH_ERRORS)
        result = runner.invoke(app, ["lint", str(clean), str(errs)])
        assert f"# {clean}" in result.output
        assert f"# {errs}" in result.output
        assert "2 file(s) checked" in result.output


class TestOtherStrictChecks:
    def test_keys_check_strict(self, tmp_path: Path) -> None:
        errs = _bib(tmp_path, "errs.bib", WITH_ERRORS)
        assert runner.invoke(app, ["keys", "check", str(errs)]).exit_code == 0
        assert runner.invoke(app, ["keys", "check", str(errs), "--strict"]).exit_code == 1

    def test_keys_check_strict_clean(self, tmp_path: Path) -> None:
        clean = _bib(tmp_path, "clean.bib", CLEAN)
        assert runner.invoke(app, ["keys", "check", str(clean), "--strict"]).exit_code == 0

    def test_files_check_strict(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T},\n  file = {missing.pdf}\n}\n")
        assert runner.invoke(app, ["asset", "check", str(bib)]).exit_code == 0
        assert runner.invoke(app, ["asset", "check", str(bib), "--strict"]).exit_code == 1

    def test_files_check_strict_ok(self, tmp_path: Path) -> None:
        (tmp_path / "A.pdf").write_text("pdf")
        bib = tmp_path / "refs.bib"
        bib.write_text("@article{A,\n  title = {T},\n  file = {A:A.pdf:PDF}\n}\n")
        assert runner.invoke(app, ["asset", "check", str(bib), "--strict"]).exit_code == 0

    def test_dedupe_check_strict(self, tmp_path: Path) -> None:
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{A,\n  title = {T},\n  doi = {10.5555/abc}\n}\n"
            "@article{B,\n  title = {T},\n  doi = {10.5555/ABC}\n}\n"
        )
        assert runner.invoke(app, ["dedupe", "check", str(bib)]).exit_code == 0
        assert runner.invoke(app, ["dedupe", "check", str(bib), "--strict"]).exit_code == 1

    def test_verify_offline_multi_file(self, tmp_path: Path) -> None:
        a = _bib(tmp_path, "a.bib", CLEAN)
        b = _bib(tmp_path, "b.bib", CLEAN)
        result = runner.invoke(app, ["verify", str(a), str(b), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == "verify"
        assert len(data["files"]) == 2


class TestPreCommitHooks:
    def test_manifest_is_valid(self) -> None:
        manifest = REPO_ROOT / ".pre-commit-hooks.yaml"
        assert manifest.exists()
        hooks = yaml.safe_load(manifest.read_text())
        ids = {h["id"] for h in hooks}
        assert ids == {
            "pynakes-lint",
            "pynakes-keys-check",
            "pynakes-files-check",
            "pynakes-dedupe-check",
        }
        for hook in hooks:
            # Every gate hook is a read-only, strict pynakes check on .bib files.
            assert hook["entry"].startswith("pynakes ")
            assert hook["entry"].endswith("--strict")
            assert hook["language"] == "python"
            assert hook["files"] == r"\.bib$"

    def test_every_hook_entry_runs_on_a_clean_library(self, tmp_path: Path) -> None:
        # The files-check hook once named a command renamed away in 0.5.0 and
        # failed for every user who enabled it; run each entry for real.
        bib = tmp_path / "refs.bib"
        bib.write_text(
            "@article{Euler1748,\n  author = {Euler, Leonhard},\n"
            "  title = {Introductio},\n  journal = {Opera},\n  year = {1748}\n}\n"
        )
        hooks = yaml.safe_load((REPO_ROOT / ".pre-commit-hooks.yaml").read_text())
        for hook in hooks:
            argv = shlex.split(hook["entry"])[1:]

            result = runner.invoke(app, [*argv, str(bib)])

            assert result.exit_code == 0, (hook["id"], result.output)
