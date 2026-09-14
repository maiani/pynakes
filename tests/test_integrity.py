"""Tests for integrity verification and enrichment."""

import json
import threading
from pathlib import Path

from typer.testing import CliRunner

from pynakes import integrity, provider_cache
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.cli_commands.integrity import _RichIntegrityProgress
from pynakes.identity import entry_arxiv_id
from pynakes.integrity import (
    _map_concurrently,
    check_published,
    compare_entries,
    compare_entry_with_remote,
    enrich_library,
    verify_library,
)
from pynakes.progress import EntryProgressEvent
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import aps, crossref, doi, openalex, semantic_scholar
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

APS_BIBTEX = """@article{1bmy-6yp4,
  journal = {Phys. Rev. B},
  issue = {8},
  pages = {L080507},
  numpages = {7},
  month = {Aug},
  doi = {10.1103/1bmy-6yp4}
}
"""

ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v2</id>
    <title>A preprint</title>
    <arxiv:doi>10.5555/published</arxiv:doi>
    <arxiv:journal_ref>Journal of Published Tests 12, 34 (2024)</arxiv:journal_ref>
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


def test_verify_library_reports_malformed_doi() -> None:
    lib = parse_bib("@article{A,\n  title = {T},\n  doi = {not a doi}\n}\n")

    report = verify_library(lib, online=True)

    assert report.checked == 0
    assert report.issues[0].type == "malformed_doi"
    assert report.issues[0].key == "A"


def test_verify_library_reports_offline_dois_as_info() -> None:
    lib = parse_bib("@article{A,\n  title = {T},\n  doi = {10.5555/example}\n}\n")

    report = verify_library(lib, online=False)

    assert report.checked == 0
    assert report.issues[0].type == "doi_not_checked"
    assert report.issues[0].severity == "info"


def test_enrich_library_reports_malformed_doi(monkeypatch) -> None:
    def fail_fetch(d: str) -> str:
        raise AssertionError("should not fetch a malformed DOI")

    monkeypatch.setattr(doi, "fetch_bibtex", fail_fetch)
    lib = parse_bib("@article{A,\n  title = {T},\n  doi = {not a doi}\n}\n")

    report = enrich_library(lib, online=True)

    assert report.updates == []
    assert report.warnings == [
        {"type": "malformed_doi", "key": "A", "message": "Malformed DOI: 'not a doi'"}
    ]


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


def test_enrich_prefers_aps_metadata_and_adds_page_count(monkeypatch) -> None:
    monkeypatch.setattr(
        aps,
        "fetch_metadata",
        lambda _doi, _journal, **_kwargs: aps.ReferenceMetadata(
            provider="American Physical Society",
            entry_type="article",
            fields={"number": "8", "pages": "L080507", "numpages": "7", "month": "Aug"},
        ),
    )
    doi_calls: list[str] = []
    monkeypatch.setattr(
        doi, "fetch_bibtex", lambda value: doi_calls.append(value) or PROVIDER_BIBTEX
    )
    lib = parse_bib(
        "@article{Levitan_2026,\n  journal = {Physical Review B},\n  doi = {10.1103/1bmy-6yp4}\n}\n"
    )

    report = enrich_library(lib, online=True)

    assert doi_calls == []
    assert {(update.field, update.value) for update in report.updates} >= {
        ("pages", "L080507"),
        ("numpages", "7"),
        ("month", "Aug"),
    }
    entry = lib.entries["Levitan_2026"]
    assert entry.fields["number"] == "8"
    assert entry.fields["pages"] == "L080507"
    assert entry.fields["numpages"] == "7"


def test_enrich_supplements_missing_article_number_from_crossref(monkeypatch) -> None:
    provider_bibtex = PROVIDER_BIBTEX.replace(
        "  year = {2024},", "  year = {2024},\n  volume = {12},"
    )
    monkeypatch.setattr(doi, "fetch_bibtex", lambda _doi: provider_bibtex)
    monkeypatch.setattr(
        crossref,
        "fetch_work_by_doi",
        lambda _doi, cache_file=None: {
            "title": ["A Correct Title"],
            "container-title": ["Journal of Tests"],
            "volume": "12",
            "article-number": "345678",
            "DOI": "10.5555/example",
            "type": "journal-article",
            "published": {"date-parts": [[2024]]},
        },
    )
    lib = parse_bib("@article{A, volume = {12}, doi = {10.5555/example}}\n")

    enrich_library(lib, online=True)

    assert lib.entries["A"].fields["pages"] == "345678"


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


def test_compare_treats_full_and_abbreviated_journal_titles_as_equivalent() -> None:
    lib = parse_bib(
        "@article{A, journal = {Phys. Rev. B}}\n@article{B, journal = {Physical Review B}}\n"
    )

    report = compare_entries(lib.entries["A"], lib.entries["B"])

    assert report.fields == []


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
    assert by_field["journal"].other == "Journal of Published Tests"
    assert by_field["volume"].other == "12"
    assert by_field["pages"].other == "34"


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
    assert "+  journal = {Journal of Published Tests}" in data["diff"]
    assert "+  volume = {12}" in data["diff"]
    assert "+  pages = {34}" in data["diff"]
    assert "-  year = {2023}" in data["diff"]
    assert "+  year = {2024}" in data["diff"]
    assert "-@misc{Preprint," in data["diff"]
    assert "+@article{Preprint," in data["diff"]
    assert bib.read_text() == original


def test_published_promotion_replaces_arxiv_doi_but_keeps_eprint(monkeypatch) -> None:
    monkeypatch.setattr(arxiv, "fetch_atom", lambda identifier: ARXIV_XML)
    lib = parse_bib(
        "@misc{Preprint,\n"
        "  eprint = {2301.00001},\n"
        "  archiveprefix = {arXiv},\n"
        "  url = {https://arxiv.org/abs/2301.00001},\n"
        "  abstract = {Useful preprint abstract},\n"
        "  doi = {10.48550/ARXIV.2301.00001},\n"
        "  year = {2023}\n"
        "}\n"
    )

    check_published(lib, online=True, apply=True)

    entry = lib.entries["Preprint"]
    assert entry.type == "article"
    assert entry.fields["doi"] == "10.5555/published"
    assert entry.fields["journal"] == "Journal of Published Tests"
    assert entry.fields["volume"] == "12"
    assert entry.fields["pages"] == "34"
    assert entry.fields["year"] == "2024"
    assert entry.fields["eprint"] == "2301.00001"
    assert entry.fields["archiveprefix"] == "arXiv"
    assert entry.fields["url"] == "https://arxiv.org/abs/2301.00001"
    assert entry.fields["abstract"] == "Useful preprint abstract"


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
    monkeypatch.setattr(openalex, "fetch_work_by_doi", lambda doi, cache_file=None: OPENALEX_WORK)
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
        openalex, "fetch_work_by_doi", lambda doi, cache_file=None: OPENALEX_WORK_WITHOUT_ARXIV
    )
    monkeypatch.setattr(
        semantic_scholar,
        "fetch_paper_by_doi",
        lambda doi, cache_file=None: SEMANTIC_SCHOLAR_PAPER,
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


def test_a_run_asks_a_provider_about_one_doi_only_once(monkeypatch) -> None:
    # This is what opt-in caching rests on: with no --cache-dir the responses
    # are memoized for the process, so repeats inside a run cost nothing and
    # nothing is written to disk.
    calls: list[str] = []

    def counting_fetch(identifier: str) -> str:
        calls.append(identifier)
        return PROVIDER_BIBTEX

    monkeypatch.setattr(doi, "fetch_bibtex", counting_fetch)

    for _ in range(3):
        integrity.fetch_doi_entry("10.5555/example")

    assert calls == ["10.5555/example"]


def test_duplicate_dois_in_one_library_cost_a_single_lookup(monkeypatch) -> None:
    calls: list[str] = []

    def counting_fetch(identifier: str) -> str:
        calls.append(identifier)
        return PROVIDER_BIBTEX

    monkeypatch.setattr(doi, "fetch_bibtex", counting_fetch)
    lib = parse_bib(
        "@article{A, author = {John Smith}, title = {T}, year = {2024},\n"
        "  doi = {10.5555/example}}\n"
        "@article{B, author = {John Smith}, title = {T}, year = {2024},\n"
        "  doi = {10.5555/EXAMPLE}}\n"
    )

    verify_library(lib, online=True)

    assert calls == ["10.5555/example"]


def test_an_online_run_writes_nothing_without_a_cache_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{euclid1482elements, author = {Euclid}, title = {Elements},\n"
        "  year = {1482}, doi = {10.5555/elements}}\n"
    )

    result = runner.invoke(app, ["verify", str(bib), "--online", "--json"])

    assert result.exit_code == 0
    assert sorted(item.name for item in tmp_path.iterdir()) == ["refs.bib"]


def test_an_online_run_reuses_an_opted_in_cache_across_runs(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def counting_fetch(identifier: str) -> str:
        calls.append(identifier)
        return PROVIDER_BIBTEX

    monkeypatch.setattr(doi, "fetch_bibtex", counting_fetch)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{euclid1482elements, author = {Euclid}, title = {Elements},\n"
        "  year = {1482}, doi = {10.5555/elements}}\n"
    )
    cache_file = tmp_path / "responses"

    for _ in range(2):
        provider_cache.reset_instances()  # each CLI invocation is its own process
        result = runner.invoke(
            app, ["verify", str(bib), "--online", "--cache-file", str(cache_file), "--json"]
        )
        assert result.exit_code == 0

    assert calls == ["10.5555/elements"]
    assert cache_file.is_file()


def test_verify_library_reports_progress_for_every_entry(monkeypatch) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    lib = parse_bib("@article{A, doi = {10.5555/example}}\n@article{B, title = {No DOI here}}\n")
    events: list[EntryProgressEvent] = []

    verify_library(lib, online=True, progress=events.append)

    assert [(e.key, e.entry_index, e.entry_total) for e in events] == [
        ("A", 1, 2),
        ("B", 2, 2),
    ]


def test_enrich_library_reports_progress_for_every_entry(monkeypatch) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    lib = parse_bib("@article{A, doi = {10.5555/example}}\n@article{B, title = {No DOI here}}\n")
    events: list[EntryProgressEvent] = []

    enrich_library(lib, online=True, progress=events.append)

    assert [(e.key, e.entry_index, e.entry_total) for e in events] == [
        ("A", 1, 2),
        ("B", 2, 2),
    ]


def test_check_published_reports_progress_for_every_entry() -> None:
    lib = parse_bib(
        "@article{A, eprint = {2401.00001}, archiveprefix = {arXiv}}\n"
        "@article{B, title = {Not a preprint}}\n"
    )
    events: list[EntryProgressEvent] = []

    check_published(lib, progress=events.append)

    assert [(e.key, e.entry_index, e.entry_total) for e in events] == [
        ("A", 1, 2),
        ("B", 2, 2),
    ]


def test_rich_integrity_progress_tracks_entries() -> None:
    class FakeProgress:
        def __init__(self) -> None:
            self.next_id = 0
            self.tasks: list[tuple[str, int | None]] = []
            self.updated: list[tuple[object, dict[str, object]]] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def add_task(self, description: str, *, total: int | None):
            self.next_id += 1
            self.tasks.append((description, total))
            return self.next_id

        def update(self, task_id: object, **kwargs: object) -> None:
            self.updated.append((task_id, kwargs))

    progress = _RichIntegrityProgress("Verifying")
    fake = FakeProgress()
    progress._progress = fake  # type: ignore[assignment]

    assert progress.__enter__() is progress
    progress(EntryProgressEvent("Smith2020", 1, 2))
    progress(EntryProgressEvent("Doe2021", 2, 2))
    assert progress.__exit__(None, None, None) is False

    assert fake.tasks == [("Verifying: Smith2020", 2)]
    assert fake.updated == [
        (1, {"completed": 1, "description": "Verifying: Smith2020"}),
        (1, {"completed": 2, "description": "Verifying: Doe2021"}),
    ]


def test_verify_online_shows_progress_bar_not_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    seen: list[EntryProgressEvent] = []
    monkeypatch.setattr(_RichIntegrityProgress, "__call__", lambda self, event: seen.append(event))
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, doi = {10.5555/example}}\n")

    result = runner.invoke(app, ["verify", str(bib), "--online"])

    assert result.exit_code == 0, result.output
    assert [e.key for e in seen] == ["A"]


def test_verify_online_json_skips_progress_bar(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    constructed = []
    monkeypatch.setattr(
        _RichIntegrityProgress,
        "__init__",
        lambda self, description: constructed.append(description),
    )
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, doi = {10.5555/example}}\n")

    result = runner.invoke(app, ["verify", str(bib), "--online", "--json"])

    assert result.exit_code == 0, result.output
    assert constructed == []


def test_map_concurrently_runs_jobs_on_multiple_threads() -> None:
    # A barrier only releases once every job has arrived, so this can only
    # complete if all four jobs are genuinely running at once — a serial
    # fallback would deadlock the barrier and fail the test via timeout.
    barrier = threading.Barrier(4, timeout=5)
    seen_threads: set[int] = set()
    lock = threading.Lock()

    def job(item: int) -> int:
        with lock:
            seen_threads.add(threading.get_ident())
        barrier.wait()
        return item * 2

    results = _map_concurrently(list(range(4)), job, concurrency=4)

    assert results == [0, 2, 4, 6]
    assert len(seen_threads) == 4


def test_map_concurrently_serial_for_concurrency_one() -> None:
    calls: list[int] = []

    results = _map_concurrently([1, 2, 3], lambda item: calls.append(item) or item, concurrency=1)

    assert results == [1, 2, 3]
    assert calls == [1, 2, 3]


def test_verify_library_concurrency_preserves_result_order(monkeypatch) -> None:
    bibtex_by_doi = {
        "10.5555/aaa": "@article{r,\n  title = {Title A},\n  doi = {10.5555/aaa}\n}\n",
        "10.5555/bbb": "@article{r,\n  title = {Title B},\n  doi = {10.5555/bbb}\n}\n",
        "10.5555/ccc": "@article{r,\n  title = {Title C},\n  doi = {10.5555/ccc}\n}\n",
    }
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: bibtex_by_doi[d])
    lib = parse_bib(
        "@article{A, title = {Title A}, doi = {10.5555/aaa}}\n"
        "@article{B, title = {Wrong Title}, doi = {10.5555/bbb}}\n"
        "@article{C, title = {Title C}, doi = {10.5555/ccc}}\n"
    )

    report = verify_library(lib, online=True, concurrency=4)

    assert report.checked == 3
    assert [issue.key for issue in report.issues] == ["B"]


def test_enrich_library_concurrency_preserves_result_order(monkeypatch) -> None:
    bibtex_by_doi = {
        "10.5555/aaa": "@article{r,\n  author = {Author A},\n  doi = {10.5555/aaa}\n}\n",
        "10.5555/bbb": "@article{r,\n  author = {Author B},\n  doi = {10.5555/bbb}\n}\n",
        "10.5555/ccc": "@article{r,\n  author = {Author C},\n  doi = {10.5555/ccc}\n}\n",
    }
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: bibtex_by_doi[d])
    lib = parse_bib(
        "@article{A, doi = {10.5555/aaa}}\n"
        "@article{B, doi = {10.5555/bbb}}\n"
        "@article{C, doi = {10.5555/ccc}}\n"
    )

    enrich_library(lib, online=True, concurrency=4)

    assert lib.entries["A"].fields["author"] == "Author A"
    assert lib.entries["B"].fields["author"] == "Author B"
    assert lib.entries["C"].fields["author"] == "Author C"


def test_check_published_concurrency_preserves_result_order(monkeypatch) -> None:
    def fake_fetch_atom(identifier: str) -> str:
        return ARXIV_XML.replace("10.5555/published", f"10.5555/{identifier}")

    monkeypatch.setattr(arxiv, "fetch_atom", fake_fetch_atom)
    lib = parse_bib(
        "@misc{A, eprint = {2401.00001}, archiveprefix = {arXiv}}\n"
        "@misc{B, eprint = {2401.00002}, archiveprefix = {arXiv}}\n"
        "@misc{C, eprint = {2401.00003}, archiveprefix = {arXiv}}\n"
    )

    report = check_published(lib, online=True, concurrency=4)

    by_key = {c.key: c for c in report.candidates}
    assert by_key["A"].doi == "10.5555/2401.00001"
    assert by_key["B"].doi == "10.5555/2401.00002"
    assert by_key["C"].doi == "10.5555/2401.00003"


def test_verify_cli_accepts_concurrency_option(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, doi = {10.5555/example}}\n@article{B, doi = {10.5555/example}}\n")

    result = runner.invoke(app, ["verify", str(bib), "--online", "-j", "4", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["checked"] == 2


def test_verify_cli_rejects_zero_concurrency(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, doi = {10.5555/example}}\n")

    result = runner.invoke(app, ["verify", str(bib), "--concurrency", "0"])

    assert result.exit_code != 0


# --- container fields follow the entry type ---------------------------------

CHAPTER_REMOTE = """@misc{remote,
  author = {Gauss, Carl Friedrich},
  title = {On Congruences},
  journal = {Disquisitiones Arithmeticae},
  pages = {3--56},
  doi = {10.5555/chapter}
}
"""


def test_enrich_does_not_write_journal_into_an_inproceedings(monkeypatch) -> None:
    # DOI content negotiation renders a chapter's container into `journal`
    # regardless of the work's type. Copying it across put a book title into a
    # field only @article styles read.
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: CHAPTER_REMOTE)
    lib = parse_bib("@inproceedings{A,\n  title = {A talk},\n  doi = {10.5555/chapter}\n}\n")

    enrich_library(lib, online=True)

    entry = lib.entries["A"]
    assert "journal" not in entry.fields
    assert entry.fields["booktitle"] == "Disquisitiones Arithmeticae"


def test_enrich_leaves_a_deliberate_booktitle_alone(monkeypatch) -> None:
    # The reported regression: a user sets booktitle and clears journal, and
    # enrich puts journal straight back, now redundant with booktitle.
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: CHAPTER_REMOTE)
    lib = parse_bib(
        "@incollection{A,\n  title = {On Congruences},\n"
        "  booktitle = {Disquisitiones Arithmeticae},\n  doi = {10.5555/chapter}\n}\n"
    )

    enrich_library(lib, online=True)

    assert "journal" not in lib.entries["A"].fields


def test_enrich_writes_no_container_for_a_book(monkeypatch) -> None:
    # A monograph's own title is the container; there is nowhere for a remote
    # container title to go.
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: CHAPTER_REMOTE)
    lib = parse_bib("@book{A,\n  title = {Collected Works},\n  doi = {10.5555/chapter}\n}\n")

    enrich_library(lib, online=True)

    entry = lib.entries["A"]
    assert "journal" not in entry.fields
    assert "booktitle" not in entry.fields


def test_enrich_still_fills_journal_on_an_article(monkeypatch) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    lib = parse_bib("@article{A,\n  title = {T},\n  doi = {10.5555/example}\n}\n")

    enrich_library(lib, online=True)

    assert lib.entries["A"].fields["journal"] == "Journal of Tests"


def test_enrich_uses_journaltitle_for_a_biblatex_library(monkeypatch) -> None:
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    lib = parse_bib(
        "@comment{pynakes-meta: dialect:biblatex;}\n\n"
        "@article{A,\n  title = {T},\n  doi = {10.5555/example}\n}\n"
    )

    enrich_library(lib, online=True)

    assert lib.entries["A"].fields["journaltitle"] == "Journal of Tests"


# --- enrich's summary counts what enrich did --------------------------------


def test_enrich_summary_counts_include_preprint_work(monkeypatch, tmp_path: Path) -> None:
    # The dry run is the review gate, so under-reporting is the wrong direction
    # to be wrong in: the human summary must agree with the JSON envelope and
    # with the diff printed beneath it.
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    monkeypatch.setattr(openalex, "fetch_work_by_doi", lambda doi, cache_file=None: OPENALEX_WORK)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{PublishedFirst,\n"
        "  author = {Ada Lovelace},\n"
        "  title = {A Published First Test},\n"
        "  doi = {10.5555/published-first},\n"
        "  year = {2024}\n"
        "}\n"
    )

    human = runner.invoke(app, ["enrich", str(bib), "--published", "--online", "--dry-run"])
    payload = runner.invoke(
        app, ["enrich", str(bib), "--published", "--online", "--dry-run", "--json"]
    )
    data = json.loads(payload.output)

    assert human.exit_code == 0, human.output
    assert f"Would enrich {data['modified_entries']} " in human.output
    assert f"field_updates={len(data['updates'])}" in human.output


def test_enrich_describes_an_arxiv_backfill_as_a_link_not_a_promotion(
    monkeypatch, tmp_path: Path
) -> None:
    # The entry was already published; it gained eprint provenance pointing at
    # its preprint. Calling that a promotion described the reverse.
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: PROVIDER_BIBTEX)
    monkeypatch.setattr(openalex, "fetch_work_by_doi", lambda doi, cache_file=None: OPENALEX_WORK)
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{PublishedFirst,\n"
        "  author = {Ada Lovelace},\n"
        "  title = {A Published First Test},\n"
        "  doi = {10.5555/published-first},\n"
        "  year = {2024}\n"
        "}\n"
    )

    result = runner.invoke(app, ["enrich", str(bib), "--published", "--online", "--dry-run"])

    assert "added arXiv preprint provenance to 1 published entry" in result.output
    assert "promoted" not in result.output


def test_published_report_counts_promotions_and_links_apart() -> None:
    lib = parse_bib(
        "@misc{Preprint,\n  title = {A preprint},\n  eprint = {2301.00001},\n"
        "  archiveprefix = {arXiv},\n  doi = {10.5555/published},\n"
        "  journal = {Journal of Tests}\n}\n"
    )

    report = check_published(lib, apply=True)

    assert report.promoted == 1
    assert report.linked == 0
    assert report.to_dict()["promoted"] == 1
