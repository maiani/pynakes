"""`ref import --cache-file` and per-identifier progress."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import importer as importer_ops
from pynakes import provider_cache
from pynakes.cli import app
from pynakes.provider_cache import cache_scope, open_cache

runner = CliRunner()


def _record(doi: str) -> str:
    # Pages present, so the import asks no second provider for a locator.
    return (
        "@article{Provider, author = {Lovelace, Ada}, title = {Notes},"
        f" journal = {{Notes}}, year = {{1843}}, pages = {{1--10}}, doi = {{{doi}}}}}\n"
    )


@pytest.fixture
def calls(monkeypatch) -> list[str]:
    asked: list[str] = []

    def fetch_bibtex(doi: str, timeout: float = 0) -> str:
        asked.append(doi)
        return _record(doi)

    monkeypatch.setattr(importer_ops.doi_provider, "fetch_bibtex", fetch_bibtex)
    return asked


def test_a_cache_file_spares_the_second_run_its_lookups(tmp_path: Path, calls: list[str]) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("", encoding="utf-8")
    cache = tmp_path / "providers.jsonl"
    args = ["ref", "import", str(bib), "10.5555/one", "10.5555/two", "--cache-file", str(cache)]

    preview = runner.invoke(app, [*args, "--dry-run", "--json"])
    provider_cache.reset_instances()  # a second process: only the file remains
    applied = runner.invoke(app, [*args, "--json"])

    assert preview.exit_code == 0, preview.output
    assert applied.exit_code == 0, applied.output
    assert calls == ["10.5555/one", "10.5555/two"]
    assert json.loads(applied.output)["imported"] == 2
    assert cache.is_file()


def test_without_a_cache_file_nothing_is_written(tmp_path: Path, calls: list[str]) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("", encoding="utf-8")

    result = runner.invoke(app, ["ref", "import", str(bib), "10.5555/one", "--json"])

    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in tmp_path.iterdir()) == ["refs.bib"]


def test_cache_scope_points_the_default_cache_at_the_file(tmp_path: Path) -> None:
    cache = tmp_path / "providers.jsonl"

    with cache_scope(cache):
        open_cache(None).put("doi", "10.5555/one", "bib", "@misc{X}")

    assert open_cache(cache).get("doi", "10.5555/one", "bib") == "@misc{X}"
    assert open_cache(None).get("doi", "10.5555/one", "bib") is None


def test_several_identifiers_report_progress_on_stderr(tmp_path: Path, calls: list[str]) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("", encoding="utf-8")

    result = runner.invoke(app, ["ref", "import", str(bib), "10.5555/one", "10.5555/two"])

    assert result.exit_code == 0, result.output
    assert "[1/2] 10.5555/one" in result.stderr
    assert "[2/2] 10.5555/two" in result.stderr
    assert "[1/2]" not in result.stdout


def test_json_runs_keep_stderr_silent(tmp_path: Path, calls: list[str]) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("", encoding="utf-8")

    result = runner.invoke(app, ["ref", "import", str(bib), "10.5555/one", "10.5555/two", "--json"])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    json.loads(result.stdout)
