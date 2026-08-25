"""Tests for integrity verification and enrichment."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes import integrity, provider_cache
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.cli_commands.integrity import _RichIntegrityProgress
from pynakes.identity import entry_arxiv_id
from pynakes.integrity import (
    check_published,
    compare_entries,
    compare_entry_with_remote,
    enrich_library,
    verify_library,
)
from pynakes.progress import EntryProgressEvent
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import aps, doi, openalex, semantic_scholar
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
