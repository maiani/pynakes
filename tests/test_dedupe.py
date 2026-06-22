"""Tests for duplicate-work detection and merge."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.dedupe import DedupeConflictError, find_duplicate_clusters, merge_duplicates
from pynakes.engine import Collection

runner = CliRunner()


def test_find_duplicate_clusters_by_stable_identifiers() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {https://doi.org/10.5555/ABC}\n"
        "}\n\n"
        "@article{B,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc}\n"
        "}\n\n"
        "@misc{C,\n"
        "  title = {Other},\n"
        "  eprint = {2301.00001v2},\n"
        "  archivePrefix = {arXiv}\n"
        "}\n\n"
        "@article{D,\n"
        "  title = {Other},\n"
        "  arxiv = {2301.00001}\n"
        "}\n"
    )

    clusters = find_duplicate_clusters(lib)

    identities = {(c.identity.kind, c.identity.value) for c in clusters}
    assert ("doi", "10.5555/abc") in identities
    assert ("arxiv", "2301.00001") in identities


def test_fuzzy_cluster_can_include_entry_without_stable_id() -> None:
    lib = parse_bib(
        "@article{WithDOI,\n"
        "  author = {John Smith and Jane Doe},\n"
        "  title = {A Practical Test of Bibliography Deduplication},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc}\n"
        "}\n\n"
        "@article{NoDOI,\n"
        "  author = {John Smith and Jane Doe},\n"
        "  title = {A practical test of bibliography deduplication},\n"
        "  year = {2020}\n"
        "}\n"
    )

    clusters = find_duplicate_clusters(lib)

    assert len(clusters) == 1
    assert clusters[0].identity.kind == "doi"
    assert [entry.key for entry in clusters[0].entries] == ["WithDOI", "NoDOI"]


def test_merge_duplicates_copies_missing_data_and_removes_duplicate() -> None:
    coll = Collection.from_text(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/ABC},\n"
        "  groups = {Read}\n"
        "}\n\n"
        "@article{B,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc},\n"
        "  url = {https://example.test/paper},\n"
        "  groups = {Important}\n"
        "}\n"
    )

    report = coll.dedupe_merge()
    preview = coll.preview()

    assert report.merged_clusters == 1
    assert report.removed_entry_count == 1
    assert len(coll.entries) == 1
    assert coll.entries["A"].fields["url"] == "https://example.test/paper"
    assert coll.entries["A"].fields["groups"] == "Read, Important"
    assert "@article{B," not in preview
    assert "url = {https://example.test/paper}" in preview


def test_merge_conflict_leaves_library_untouched() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc},\n"
        "  journal = {Journal A}\n"
        "}\n\n"
        "@article{B,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc},\n"
        "  journal = {Journal B}\n"
        "}\n"
    )

    with pytest.raises(DedupeConflictError) as exc:
        merge_duplicates(lib)

    assert exc.value.conflicts[0].field == "journal"
    assert len(lib.entries) == 2
    assert lib.entries["A"].fields["journal"] == "Journal A"


def test_dedupe_check_cli_json(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n  title = {T},\n  doi = {10.5555/abc}\n}\n"
        "@article{B,\n  title = {T},\n  doi = {10.5555/ABC}\n}\n"
    )

    result = runner.invoke(app, ["dedupe", "check", str(bib), "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0
    assert data["status"] == "success"
    assert data["action"] == "dedupe_check"
    assert data["cluster_count"] == 1
    assert data["clusters"][0]["keys"] == ["A", "B"]


def test_dedupe_merge_cli_dry_run_diff_json(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = (
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc}\n"
        "}\n\n"
        "@article{B,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc},\n"
        "  url = {https://example.test/paper}\n"
        "}\n"
    )
    bib.write_text(original)

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--dry-run", "--diff", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["status"] == "success"
    assert data["action"] == "dedupe_merge"
    assert data["dry_run"] is True
    assert data["modified"] is True
    assert data["modified_entries"] == 2
    assert data["removed_entries"] == 1
    assert "-@article{B," in data["diff"]
    assert bib.read_text() == original


def test_dedupe_merge_cli_conflict_exit_2(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc},\n"
        "  journal = {Journal A}\n"
        "}\n\n"
        "@article{B,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc},\n"
        "  journal = {Journal B}\n"
        "}\n"
    )

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 2
    assert data["status"] == "conflict"
    assert data["error"] == "DedupeConflict"
    assert data["conflicts"][0]["field"] == "journal"
