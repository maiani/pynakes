"""Tests for integrity verification and enrichment."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes import integrity
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.identity import entry_arxiv_id
from pynakes.integrity import (
    compare_entries,
    compare_entry_with_remote,
    enrich_library,
    verify_library,
)
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import doi, openalex, semantic_scholar
from pynakes.providers.repositories import arxiv

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

OPENALEX_WORK = {
    "locations": [
        {"landing_page_url": "https://doi.org/10.5555/published-first"},
        {"landing_page_url": "https://arxiv.org/abs/2401.00001v3"},
    ]
}

OPENALEX_WORK_WITHOUT_ARXIV = {
    "locations": [
        {"landing_page_url": "https://doi.org/10.5555/published-first"},
    ]
}

SEMANTIC_SCHOLAR_PAPER = {
    "externalIds": {
        "DOI": "10.5555/published-first",
        "ArXiv": "2402.00002v4",
    },
    "url": "https://www.semanticscholar.org/paper/test",
}


def test_verify_library_reports_provider_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
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


def test_verify_library_separates_provider_errors(monkeypatch) -> None:
    def fail_fetch(doi: str) -> str:
        raise ProviderFetchError(f"Network error fetching {doi}: temporary failure")

    monkeypatch.setattr(doi, "fetch_bibtex", fail_fetch)
    lib = parse_bib("@article{A,\n  title = {A Paper},\n  doi = {10.5555/example}\n}\n")

    report = verify_library(lib, online=True)

    assert report.checked == 0
    assert report.errors == 1
    assert report.issues[0].type == "provider_error"
    assert report.issues[0].field == "doi"


def test_enrich_library_fills_missing_doi_from_url_and_provider_fields(monkeypatch) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
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


def test_compare_entry_with_remote_lists_differing_and_missing_fields(monkeypatch) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    lib = parse_bib(
        "@article{A,\n"
        "  author = {Someone Else},\n"
        "  title = {A Correct Title},\n"
        "  doi = {10.5555/EXAMPLE}\n"
        "}\n"
    )

    report = compare_entry_with_remote(lib.entries["A"], online=True)

    assert report.source == "doi"
    assert report.identifier == "10.5555/EXAMPLE"
    by_field = {c.field: c for c in report.fields}
    # Matching title is not reported; differing author and missing fields are.
    assert "title" not in by_field
    assert by_field["author"].local == "Someone Else"
    assert by_field["author"].other == "John Smith"
    assert by_field["journal"].local is None
    assert by_field["journal"].other == "Journal of Tests"
    # Same DOI differing only in case is not reported as a difference.
    assert "doi" not in by_field
    assert report.warnings == []


def test_compare_entry_with_remote_falls_back_to_arxiv(monkeypatch) -> None:
    monkeypatch.setattr(arxiv, "fetch_atom", lambda identifier: ARXIV_XML)
    lib = parse_bib(
        "@misc{A,\n  title = {An old title},\n  eprint = {2301.00001},\n"
        "  archiveprefix = {arXiv}\n}\n"
    )

    report = compare_entry_with_remote(lib.entries["A"], online=True)

    assert report.source == "arxiv"
    assert report.identifier == "2301.00001"
    by_field = {c.field: c for c in report.fields}
    assert by_field["title"].other == "A preprint"
    assert by_field["doi"].other == "10.5555/published"
    assert by_field["journal"].other == "Journal of Published Tests 12, 34"


def test_compare_entry_with_remote_offline_warns_without_fetching(monkeypatch) -> None:
    def fail_fetch(d: str) -> str:
        raise AssertionError("should not fetch when offline")

    monkeypatch.setattr(doi, "fetch_bibtex", fail_fetch)
    lib = parse_bib("@article{A,\n  title = {T},\n  doi = {10.5555/example}\n}\n")

    report = compare_entry_with_remote(lib.entries["A"], online=False)

    assert report.fields == []
    assert report.warnings[0]["type"] == "offline"


def test_compare_entry_with_remote_reports_no_identifier() -> None:
    lib = parse_bib("@article{A,\n  title = {T},\n  author = {X}\n}\n")

    report = compare_entry_with_remote(lib.entries["A"], online=True)

    assert report.source is None
    assert report.warnings[0]["type"] == "no_identifier"


def test_compare_entries_lists_differing_and_missing_fields() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  author = {Someone Else},\n"
        "  title = {A Correct Title}\n"
        "}\n"
        "@article{B,\n"
        "  author = {John Smith},\n"
        "  title = {A Correct Title},\n"
        "  journal = {Journal of Tests}\n"
        "}\n"
    )

    report = compare_entries(lib.entries["A"], lib.entries["B"])

    assert report.key == "A"
    assert report.source == "local"
    assert report.identifier == "B"
    by_field = {c.field: c for c in report.fields}
    assert "title" not in by_field
    assert by_field["author"].local == "Someone Else"
    assert by_field["author"].other == "John Smith"
    assert by_field["journal"].local is None
    assert by_field["journal"].other == "Journal of Tests"
    assert report.warnings == []


def test_ref_compare_with_cli_json(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n  author = {Someone Else},\n  title = {A Correct Title}\n}\n"
        "@article{B,\n  author = {John Smith},\n  title = {A Correct Title}\n}\n"
    )

    result = runner.invoke(app, ["ref", "compare", "A", "--with", "B", str(bib), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["source"] == "local"
    assert data["identifier"] == "B"
    fields = {f["field"]: f for f in data["fields"]}
    assert fields["author"]["local"] == "Someone Else"
    assert fields["author"]["other"] == "John Smith"
    # Read-only: the file on disk is untouched.
    assert "Someone Else" in bib.read_text()


def test_ref_compare_with_and_online_conflict(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A,\n  title = {T}\n}\n@article{B,\n  title = {U}\n}\n")

    result = runner.invoke(
        app, ["ref", "compare", "A", "--with", "B", "--online", str(bib), "--json"]
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"


def test_ref_compare_cli_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n  author = {Someone Else},\n  title = {A Correct Title},\n"
        "  doi = {10.5555/example}\n}\n"
    )

    result = runner.invoke(app, ["ref", "compare", "A", str(bib), "--online", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["source"] == "doi"
    fields = {f["field"] for f in data["fields"]}
    assert "author" in fields
    assert "journal" in fields
    # Read-only: the file on disk is untouched.
    assert "doi = {10.5555/example}" in bib.read_text()
    assert "journal" not in bib.read_text()


def test_verify_cli_strict_exits_one_with_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
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
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
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


def test_enrich_published_cli_uses_arxiv_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(arxiv, "fetch_atom", lambda identifier: ARXIV_XML)
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
        ["enrich", str(bib), "--published", "--online", "--dry-run", "--diff", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["status"] == "success"
    assert data["action"] == "enrich"
    assert data["modified"] is True
    assert data["preprints"]["published"] == 1
    assert "+  doi = {10.5555/published}" in data["diff"]
    assert "+  journal = {Journal of Published Tests 12, 34}" in data["diff"]
    assert "-@misc{Preprint," in data["diff"]
    assert "+@article{Preprint," in data["diff"]
    assert bib.read_text() == original


def test_check_published_promotes_preprint_with_existing_published_metadata() -> None:
    lib = parse_bib(
        "@misc{Preprint,\n"
        "  title = {A Published Preprint},\n"
        "  eprint = {2301.00001},\n"
        "  archivePrefix = {arXiv},\n"
        "  doi = {10.5555/published},\n"
        "  journal = {Journal of Published Tests}\n"
        "}\n"
    )

    report = integrity.check_published(lib, apply=True)
    entry = lib.entries["Preprint"]

    assert report.published == 1
    assert [(update.field, update.value) for update in report.updates] == [("type", "article")]
    assert entry.type == "article"
    assert entry.fields["eprint"] == "2301.00001"
    assert entry.fields["archiveprefix"] == "arXiv"


def test_check_published_backfills_arxiv_for_bibtex_doi_entry() -> None:
    lib = parse_bib(
        "@article{PublishedFirst,\n"
        "  author = {Ada Lovelace},\n"
        "  title = {A Published First Test},\n"
        "  doi = {10.5555/published-first},\n"
        "  year = {2024}\n"
        "}\n"
    )

    report = integrity.check_published(
        lib,
        online=True,
        apply=True,
        openalex_fetcher=lambda doi: OPENALEX_WORK,
        semantic_scholar_fetcher=lambda doi: None,
    )

    entry = lib.entries["PublishedFirst"]
    assert report.changed_entries == 1
    assert [update.field for update in report.updates] == ["eprint", "archiveprefix"]
    assert entry.fields["eprint"] == "2401.00001"
    assert entry.fields["archiveprefix"] == "arXiv"
    assert entry_arxiv_id(entry) == "2401.00001"


def test_check_published_backfills_arxiv_for_biblatex_doi_entry() -> None:
    lib = parse_bib(
        "@comment{jabref-meta: databaseType:biblatex;}\n"
        "@article{PublishedFirst,\n"
        "  author = {Ada Lovelace},\n"
        "  title = {A Published First Test},\n"
        "  doi = {10.5555/published-first},\n"
        "  date = {2024}\n"
        "}\n"
    )

    report = integrity.check_published(
        lib,
        online=True,
        apply=True,
        openalex_fetcher=lambda doi: OPENALEX_WORK,
        semantic_scholar_fetcher=lambda doi: None,
    )

    entry = lib.entries["PublishedFirst"]
    assert report.changed_entries == 1
    assert [update.field for update in report.updates] == ["eprint", "eprinttype"]
    assert entry.fields["eprint"] == "2401.00001"
    assert entry.fields["eprinttype"] == "arxiv"


def test_enrich_published_cli_backfills_arxiv_from_openalex(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    monkeypatch.setattr(openalex, "fetch_work_by_doi", lambda doi, cache_dir=None: OPENALEX_WORK)
    bib = tmp_path / "refs.bib"
    original = (
        "@article{PublishedFirst,\n"
        "  author = {Ada Lovelace},\n"
        "  title = {A Published First Test},\n"
        "  doi = {10.5555/published-first},\n"
        "  year = {2024}\n"
        "}\n"
    )
    bib.write_text(original)

    result = runner.invoke(
        app,
        ["enrich", str(bib), "--published", "--online", "--dry-run", "--diff", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["status"] == "success"
    assert data["action"] == "enrich"
    assert data["modified"] is True
    assert "+  eprint = {2401.00001}" in data["diff"]
    assert "+  archiveprefix = {arXiv}" in data["diff"]
    assert {"key": "PublishedFirst", "field": "eprint", "value": "2401.00001"} in data["updates"]
    assert bib.read_text() == original


def test_enrich_published_cli_backfills_arxiv_from_semantic_scholar(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    monkeypatch.setattr(
        openalex, "fetch_work_by_doi", lambda doi, cache_dir=None: OPENALEX_WORK_WITHOUT_ARXIV
    )
    monkeypatch.setattr(
        semantic_scholar,
        "fetch_paper_by_doi",
        lambda doi, cache_dir=None: SEMANTIC_SCHOLAR_PAPER,
    )
    bib = tmp_path / "refs.bib"
    original = (
        "@article{PublishedFirst,\n"
        "  author = {Ada Lovelace},\n"
        "  title = {A Published First Test},\n"
        "  doi = {10.5555/published-first},\n"
        "  year = {2024}\n"
        "}\n"
    )
    bib.write_text(original)

    result = runner.invoke(
        app,
        ["enrich", str(bib), "--published", "--online", "--dry-run", "--diff", "--json"],
    )
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["modified"] is True
    assert "+  eprint = {2402.00002}" in data["diff"]
    assert {"key": "PublishedFirst", "field": "eprint", "value": "2402.00002"} in data["updates"]
    assert bib.read_text() == original
