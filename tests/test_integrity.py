"""Tests for integrity verification and enrichment."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes import integrity
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.integrity import enrich_library, verify_library

runner = CliRunner()

PROVIDER_BIBTEX = """@article{provider,
  author = {John Smith},
  title = {A Correct Title},
  journal = {Journal of Tests},
  year = {2024},
  doi = {10.5555/example},
  url = {https://example.test/paper}
}
"""

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v2</id>
    <title>A preprint</title>
    <arxiv:doi>10.5555/published</arxiv:doi>
    <arxiv:journal_ref>Journal of Published Tests 12, 34</arxiv:journal_ref>
  </entry>
</feed>
"""


def test_verify_library_reports_provider_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(integrity, "fetch_doi_bibtex", lambda doi: PROVIDER_BIBTEX)
    lib = parse_bib(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Wrong Title},\n"
        "  year = {2024},\n"
        "  doi = {10.5555/example}\n"
        "}\n"
    )

    report = verify_library(lib, online=True)

    assert report.checked == 1
    assert report.errors == 1
    assert report.issues[0].type == "title_mismatch"


def test_enrich_library_fills_missing_doi_from_url_and_provider_fields(monkeypatch) -> None:
    monkeypatch.setattr(integrity, "fetch_doi_bibtex", lambda doi: PROVIDER_BIBTEX)
    lib = parse_bib(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Correct Title},\n"
        "  url = {https://doi.org/10.5555/example}\n"
        "}\n"
    )

    report = enrich_library(lib, online=True)

    assert report.changed_entries == 1
    assert lib.entries["A"].fields["doi"] == "10.5555/example"
    assert lib.entries["A"].fields["journal"] == "Journal of Tests"
    assert lib.entries["A"].fields["year"] == "2024"


def test_verify_cli_strict_exits_one_with_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(integrity, "fetch_doi_bibtex", lambda doi: PROVIDER_BIBTEX)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Wrong Title},\n"
        "  year = {2024},\n"
        "  doi = {10.5555/example}\n"
        "}\n"
    )

    result = runner.invoke(app, ["verify", str(bib), "--online", "--strict", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 1
    assert data["status"] == "success"
    assert data["action"] == "verify"
    assert data["errors"] == 1


def test_enrich_cli_dry_run_diff_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(integrity, "fetch_doi_bibtex", lambda doi: PROVIDER_BIBTEX)
    bib = tmp_path / "refs.bib"
    original = (
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Correct Title},\n"
        "  url = {https://doi.org/10.5555/example}\n"
        "}\n"
    )
    bib.write_text(original)

    result = runner.invoke(app, ["enrich", str(bib), "--online", "--dry-run", "--diff", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["status"] == "success"
    assert data["action"] == "enrich"
    assert data["modified"] is True
    assert data["changed_fields"] >= 3
    assert "+  doi = {10.5555/example}" in data["diff"]
    assert bib.read_text() == original


def test_published_apply_cli_uses_arxiv_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(integrity, "fetch_arxiv_atom", lambda identifier: ARXIV_XML)
    bib = tmp_path / "refs.bib"
    original = (
        "@misc{Preprint,\n"
        "  author = {Jane Smith},\n"
        "  title = {A Preprint},\n"
        "  eprint = {2301.00001v2},\n"
        "  archivePrefix = {arXiv},\n"
        "  year = {2023}\n"
        "}\n"
    )
    bib.write_text(original)

    result = runner.invoke(
        app,
        ["published", str(bib), "--online", "--apply", "--dry-run", "--diff", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["status"] == "success"
    assert data["action"] == "published_apply"
    assert data["modified"] is True
    assert data["published"] == 1
    assert "+  doi = {10.5555/published}" in data["diff"]
    assert "+  journal = {Journal of Published Tests 12, 34}" in data["diff"]
    assert "-@misc{Preprint," in data["diff"]
    assert "+@article{Preprint," in data["diff"]
    assert bib.read_text() == original
