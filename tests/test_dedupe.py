"""Tests for duplicate-work detection and merge."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.dedupe import (
    DedupeConflictError,
    clusters_for_keys,
    find_duplicate_clusters,
    merge_duplicates,
)
from pynakes.engine import Bibliography

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


def test_conflicting_stable_identifiers_block_fuzzy_clustering() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test of Bibliography Deduplication},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/first}\n"
        "}\n\n"
        "@article{B,\n"
        "  author = {John Smith},\n"
        "  title = {A practical test of bibliography deduplication},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/second}\n"
        "}\n"
    )

    assert find_duplicate_clusters(lib) == []


def test_merge_duplicates_copies_missing_data_and_removes_duplicate() -> None:
    coll = Bibliography.from_text(
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


TWO_CLUSTERS = (
    "@article{Alpha1,\n  author = {Ada Lovelace},\n  title = {On Engines},\n"
    "  journal = {Notes},\n  year = {1843},\n  doi = {10.5555/engines}\n}\n\n"
    "@article{Alpha2,\n  author = {Ada Lovelace},\n  title = {On Engines},\n"
    "  journal = {Notes},\n  year = {1843},\n  doi = {10.5555/engines},\n"
    "  note = {Offprint}\n}\n\n"
    "@article{Beta1,\n  author = {Carl Gauss},\n  title = {On Residues},\n"
    "  journal = {Werke},\n  year = {1801},\n  doi = {10.5555/residues}\n}\n\n"
    "@article{Beta2,\n  author = {Carl Gauss},\n  title = {On Residues},\n"
    "  journal = {Werke},\n  year = {1801},\n  doi = {10.5555/residues},\n"
    "  note = {Reprint}\n}\n"
)


def test_clusters_for_keys_selects_only_the_named_pair() -> None:
    clusters = find_duplicate_clusters(parse_bib(TWO_CLUSTERS))
    assert len(clusters) == 2

    selected = clusters_for_keys(clusters, ["Alpha2"])

    assert [[entry.key for entry in cluster.entries] for cluster in selected] == [
        ["Alpha1", "Alpha2"]
    ]


def test_clusters_for_keys_rejects_a_key_in_no_cluster() -> None:
    """Merging nothing while reporting success would hide the caller's mistake."""
    clusters = find_duplicate_clusters(parse_bib(TWO_CLUSTERS))

    with pytest.raises(ValueError, match="Nobody1999"):
        clusters_for_keys(clusters, ["Alpha2", "Nobody1999"])


def test_clusters_for_keys_rejects_an_empty_selection() -> None:
    clusters = find_duplicate_clusters(parse_bib(TWO_CLUSTERS))

    with pytest.raises(ValueError, match="No citation key"):
        clusters_for_keys(clusters, ["  "])


def test_dedupe_merge_by_key_leaves_every_other_cluster_alone(tmp_path: Path) -> None:
    """The "I looked at this pair and decided" case a whole-file merge cannot express."""
    bib = tmp_path / "refs.bib"
    bib.write_text(TWO_CLUSTERS)

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--key", "Alpha2", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["merged_clusters"] == 1
    assert data["removed_entries"] == 1
    assert data["keys"] == ["Alpha2"]
    written = bib.read_text()
    assert "@article{Alpha2," not in written
    # The other duplicate pair is untouched: it was never approved.
    assert "@article{Beta1," in written
    assert "@article{Beta2," in written


def test_dedupe_merge_without_key_still_merges_every_cluster(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(TWO_CLUSTERS)

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["merged_clusters"] == 2
    assert data["keys"] == []


def test_dedupe_merge_by_key_reports_a_key_that_names_no_duplicate(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(TWO_CLUSTERS)

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--key", "Nobody1999", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 1
    assert data["error"] == "NoSuchDuplicate"
    assert bib.read_text() == TWO_CLUSTERS


def test_dedupe_merge_moves_pinax_materials_to_surviving_key(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Survivor,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc}\n"
        "}\n\n"
        "@article{Duplicate,\n"
        "  author = {John Smith},\n"
        "  title = {A Practical Test},\n"
        "  year = {2020},\n"
        "  doi = {10.5555/abc}\n"
        "}\n"
        "@comment{pynakes-meta:\npinax-files-dir:\n}\n"
    )
    files = tmp_path / "refs.files"
    files.mkdir()
    (files / "Duplicate.preprint.pdf").write_bytes(b"pdf")
    (files / ".pinax").mkdir()
    (files / ".pinax" / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "files": {
                    "Duplicate": {
                        "preprint_pdf": {
                            "source": "https://arxiv.org/pdf/2101.00001",
                            "fetched_date": "2026-06-27",
                            "sha256": "0" * 64,
                            "refetchable": True,
                        },
                    }
                },
            }
        )
    )

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["pinax_materials"][0]["source_key"] == "Duplicate"
    assert data["pinax_materials"][0]["target_key"] == "Survivor"
    assert not (files / "Duplicate.preprint.pdf").exists()
    assert (files / "Survivor.preprint.pdf").read_bytes() == b"pdf"
    manifest = json.loads((files / ".pinax" / "manifest.json").read_text())
    assert "Duplicate" not in manifest["files"]
    assert manifest["files"]["Survivor"]["preprint_pdf"]["refetchable"] is True


def test_dedupe_merge_pinax_materials_respects_dry_run(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Survivor,\n  title = {A Practical Test},\n  doi = {10.5555/abc}\n}\n"
        "@article{Duplicate,\n  title = {A Practical Test},\n  doi = {10.5555/abc}\n}\n"
        "@comment{pynakes-meta:\npinax-files-dir:\n}\n"
    )
    files = tmp_path / "refs.files"
    files.mkdir()
    (files / "Duplicate.preprint.pdf").write_bytes(b"pdf")

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--dry-run", "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 0, result.output
    assert data["dry_run"] is True
    assert data["pinax_materials"][0]["kind"] == "preprint_pdf"
    assert (files / "Duplicate.preprint.pdf").read_bytes() == b"pdf"
    assert not (files / "Survivor.preprint.pdf").exists()


def test_dedupe_merge_pinax_material_conflict_exit_2(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Survivor,\n  title = {A Practical Test},\n  doi = {10.5555/abc}\n}\n"
        "@article{Duplicate,\n  title = {A Practical Test},\n  doi = {10.5555/abc}\n}\n"
        "@comment{pynakes-meta:\npinax-files-dir:\n}\n"
    )
    files = tmp_path / "refs.files"
    files.mkdir()
    (files / "Survivor.preprint.pdf").write_bytes(b"target")
    (files / "Duplicate.preprint.pdf").write_bytes(b"source")

    result = runner.invoke(app, ["dedupe", "merge", str(bib), "--json"])
    data = json.loads(result.output)

    assert result.exit_code == 2, result.output
    assert data["status"] == "conflict"
    assert data["error"] == "DedupeConflict"
    assert data["conflicts"][0]["field"] == "pinax_materials"
    assert "@article{Duplicate," in bib.read_text()
    assert (files / "Duplicate.preprint.pdf").read_bytes() == b"source"


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
