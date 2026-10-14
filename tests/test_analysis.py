"""``analyze``: descriptive counts that reconcile with the reports they compose."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.analysis import SECTIONS, analyze
from pynakes.cli import app
from pynakes.cli_choices import AnalysisSection
from pynakes.engine import Bibliography
from pynakes.filestore import FileStore

runner = CliRunner()

LIBRARY = (
    "@comment{pynakes-meta:\n"
    "group-tree: Mechanics||2||1||StaticGroup|||0|||\n"
    "  Optics||2||1||StaticGroup|||0|||\n"
    "}\n"
    "\n"
    "@book{Newton1687,\n"
    "  author = {Isaac Newton},\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  year = {1687},\n"
    "  groups = {Mechanics}\n"
    "}\n"
    "\n"
    "@book{Newton1704,\n"
    "  author = {Newton, Isaac},\n"
    "  title = {Opticks},\n"
    "  year = {1704},\n"
    "  groups = {Optics; Colour}\n"
    "}\n"
    "\n"
    "@article{Euler1744,\n"
    "  author = {Leonhard Euler and others},\n"
    "  title = {Methodus inveniendi},\n"
    "  journal = {{Commentarii Academiae}},\n"
    "  date = {1744-03},\n"
    "  doi = {10.1000/methodus}\n"
    "}\n"
    "\n"
    "@article{Euler1748,\n"
    "  author = {Leonhard Euler},\n"
    "  title = {Introductio},\n"
    "  journal = {Commentarii  Academiae},\n"
    "  url = {https://example.org/introductio},\n"
    "  file = {:missing.pdf:PDF}\n"
    "}\n"
)


def _library(tmp_path: Path, text: str = LIBRARY) -> Path:
    bib = tmp_path / "lib.bib"
    bib.write_text(text, encoding="utf-8")
    return bib


def _json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    assert "Traceback" not in result.output
    return result.exit_code, json.loads(result.output)


def test_every_section_is_reported_in_order(tmp_path: Path) -> None:
    report = analyze(Bibliography.open(_library(tmp_path)))

    assert list(report.sections) == list(SECTIONS)
    assert [member.value for member in AnalysisSection] == list(SECTIONS)


def test_per_entry_sections_reconcile_with_the_entry_count(tmp_path: Path) -> None:
    sections = analyze(Bibliography.open(_library(tmp_path))).sections
    total = sections["entries"]["total"]

    assert total == 4
    assert sum(item["entries"] for item in sections["types"]["counts"]) == total
    assert sections["years"]["dated"] + sections["years"]["undated"] == total
    authors = sections["authors"]
    assert authors["entries_with_authors"] + authors["entries_without_authors"] == total
    venues = sections["venues"]
    assert venues["entries_with_venue"] + venues["entries_without_venue"] == total
    groups = sections["groups"]
    assert groups["entries_with_groups"] + groups["entries_without_groups"] == total
    for coverage in sections["identifiers"]["fields"].values():
        assert coverage["present"] + coverage["missing"] == total


def test_counts_describe_the_records(tmp_path: Path) -> None:
    sections = analyze(Bibliography.open(_library(tmp_path)), top=2).sections

    assert sections["years"] == {
        "dated": 3,
        "undated": 1,
        "earliest": "1687",
        "latest": "1744",
        "counts": [
            {"year": "1687", "entries": 1},
            {"year": "1704", "entries": 1},
            {"year": "1744", "entries": 1},
        ],
    }
    # Both spellings of Newton count as one person; the list is capped by top.
    assert sections["authors"]["top"] == [
        {"name": "Euler, Leonhard", "entries": 2},
        {"name": "Newton, Isaac", "entries": 2},
    ]
    assert sections["authors"]["distinct"] == 2
    assert sections["authors"]["entries_with_others"] == 1
    # Braces and spacing do not split a venue.
    assert sections["venues"]["top"] == [
        {"venue": "{Commentarii Academiae}", "field": "journal", "entries": 2}
    ]
    identifiers = sections["identifiers"]
    assert identifiers["fields"]["doi"] == {"present": 1, "missing": 3, "coverage": 0.25}
    assert identifiers["any"]["present"] == 2
    assert sections["types"]["counts"] == [
        {"type": "article", "entries": 2},
        {"type": "book", "entries": 2},
    ]


def test_groups_compare_memberships_with_the_tree(tmp_path: Path) -> None:
    groups = analyze(Bibliography.open(_library(tmp_path))).sections["groups"]

    assert groups["tree_defined"] and groups["declared"] == 2
    assert groups["undeclared"] == ["Colour"]
    assert groups["unused_declared"] == []
    assert {item["group"] for item in groups["memberships"]} == {"Mechanics", "Optics", "Colour"}


def test_lint_section_equals_the_lint_summary(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, linted = _json("lint", str(bib))
    _code, analyzed = _json("analyze", str(bib), "--section", "lint")

    section = analyzed["sections"]["lint"]
    summary = linted["summary"]
    for name in ("issues", "errors", "warnings", "info", "suppressed", "by_category"):
        assert section[name] == summary[name], name
    by_type: dict[str, int] = {}
    for issue in linted["issues"]:
        by_type[issue["type"]] = by_type.get(issue["type"], 0) + 1
    assert section["by_type"] == by_type


def test_materials_compose_linked_files_and_pinax(tmp_path: Path) -> None:
    text = LIBRARY.replace(
        "@comment{pynakes-meta:\n", "@comment{pynakes-meta:\npinax-files-dir: lib.files\n"
    )
    bib = _library(tmp_path, text)
    store = FileStore.from_metadata(Bibliography.open(bib).lib, bib)
    assert store is not None
    store.write_preprint_pdf("Euler1748", b"%PDF-1.4\n")
    store.write_preprint_pdf("Leibniz1684", b"%PDF-1.4\n")

    materials = analyze(Bibliography.open(bib)).sections["materials"]

    assert materials["linked_files"] == {
        "entries_with_files": 1,
        "checked": 1,
        "ok": 0,
        "missing": 1,
        "wrong_type": 0,
        "unresolved": 0,
    }
    pinax = materials["pinax"]
    assert pinax["keys_with_materials"] == 1 and pinax["keys"] == 4
    assert pinax["by_kind"]["preprint_pdf"] == 1
    assert pinax["orphans"] == 1


def test_an_empty_library(tmp_path: Path) -> None:
    sections = analyze(Bibliography.open(_library(tmp_path, ""))).sections

    assert sections["entries"] == {
        "total": 0,
        "unique_keys": 0,
        "duplicate_keys": [],
        "entries_with_duplicate_keys": 0,
    }
    assert sections["years"]["earliest"] is None
    assert sections["identifiers"]["any"] == {"present": 0, "missing": 0, "coverage": None}
    # lint warns that the file holds no entries, and the section says so too.
    assert sections["lint"]["warnings"] == sections["lint"]["issues"] == 1
    assert sections["materials"]["pinax"] == {"configured": False}


def test_a_duplicate_key_library_counts_every_entry(fixtures_dir: Path) -> None:
    coll = Bibliography.open(fixtures_dir / "duplicate_entries.bib")
    sections = analyze(coll).sections

    entries = sections["entries"]
    assert entries["total"] == len(coll.lib.entries.values()) == 7
    assert entries["unique_keys"] == 3
    assert sum(item["entries"] for item in entries["duplicate_keys"]) == 7
    assert sum(item["entries"] for item in sections["types"]["counts"]) == 7
    assert sections["lint"]["by_type"]["duplicate_key"] == 3


def test_duplicate_keys_in_a_pinax_library_count_per_key(
    tmp_path: Path, fixtures_dir: Path
) -> None:
    text = "@comment{pynakes-meta:\npinax-files-dir: lib.files\n}\n\n" + (
        fixtures_dir / "duplicate_entries.bib"
    ).read_text(encoding="utf-8")
    pinax = analyze(Bibliography.open(_library(tmp_path, text))).sections["materials"]["pinax"]

    assert pinax["keys"] == 3


def test_section_selection_and_validation(tmp_path: Path) -> None:
    coll = Bibliography.open(_library(tmp_path))

    assert list(analyze(coll, sections=["years", "types", "years"]).sections) == ["types", "years"]
    with pytest.raises(ValueError, match="Unknown analysis section"):
        analyze(coll, sections=["quality"])
    with pytest.raises(ValueError):
        analyze(coll, top=-1)


def test_in_memory_bibliographies_are_analyzed(tmp_path: Path) -> None:
    report = analyze(Bibliography.from_text(LIBRARY))

    assert report.file is None
    assert report.sections["materials"]["linked_files"] == {"entries_with_files": 1}


def test_cli_envelope_and_human_output(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, payload = _json("analyze", str(bib), "--top", "1", "--section", "authors")
    human = runner.invoke(app, ["analyze", str(bib)]).output
    invalid = _json("analyze", str(bib), "--top", "-1")

    assert code == 0 and payload["action"] == "analyze" and payload["top"] == 1
    assert list(payload["sections"]) == ["authors"]
    assert len(payload["sections"]["authors"]["top"]) == 1
    assert "entries: 4 entries, 4 distinct keys" in human
    assert "years: 1687-1744, 3 dated, 1 undated" in human
    assert "lint:" in human and "materials: 1 entries link files (1 missing)" in human
    assert invalid[0] == 1 and invalid[1]["error"] == "InvalidInput"
