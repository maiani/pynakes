"""Bounded reads: ``ref show --key --select/--include``, paging, and ``search``."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.entry_reader import EntryReader
from pynakes.filestore import FileStore

runner = CliRunner()

ABSTRACT = "Three laws of motion and universal gravitation, " * 10

LIBRARY = (
    "@comment{pynakes-meta:\n"
    "pinax-files-dir: lib.files\n"
    "}\n"
    "\n"
    "% pynakes: ignore missing_doi -- printed before DOIs existed\n"
    "@book{Newton1687,\n"
    "  author = {Isaac Newton},\n"
    "  title = {Philosophiae Naturalis Principia Mathematica},\n"
    "  year = {1687},\n"
    f"  abstract = {{{ABSTRACT}}},\n"
    "  file = {Scan:scans/principia.pdf:PDF}\n"
    "}\n"
    "\n"
    "@book{Euler1748,\n"
    "  author = {Leonhard Euler},\n"
    "  title = {Introductio in analysin infinitorum},\n"
    "  year = {1748}\n"
    "}\n"
    "\n"
    "@book{Hooke1665,\n"
    "  author = {Robert Hooke},\n"
    "  title = {Micrographia},\n"
    "  year = {1665}\n"
    "}\n"
)


def _library(tmp_path: Path) -> Path:
    bib = tmp_path / "lib.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "principia.pdf").write_bytes(b"%PDF-1.4\n")
    store = FileStore.from_metadata(Bibliography.open(bib).lib, bib)
    assert store is not None
    store.write_published_pdf("Newton1687", b"%PDF-1.4\n")
    store.record_artifact(
        "Newton1687",
        "published_pdf",
        source="https://example.org/principia.pdf",
        refetchable=True,
        fetched_date="2026-01-02",
    )
    return bib


def _json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    assert "Traceback" not in result.output
    return result.exit_code, json.loads(result.output)


def test_include_reports_materials_and_provenance(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, payload = _json(
        "ref", "show", str(bib), "--key", "Newton1687",
        "--select", "abstract", "--include", "materials,provenance",
    )  # fmt: skip

    assert code == 0
    (entry,) = payload["entries"]
    assert entry["fields"] == {"abstract": ABSTRACT}
    pinax = entry["materials"]["pinax"]
    assert pinax["configured"] and pinax["available"] == ["published_pdf"]
    assert pinax["canonical_pdf"].endswith("Newton1687.published.pdf")
    assert entry["materials"]["linked_files"] == [
        {"path": "scans/principia.pdf", "description": "Scan", "kind": "PDF", "status": "ok"}
    ]
    recorded = entry["provenance"]["materials"]["published_pdf"]
    assert recorded["source"] == "https://example.org/principia.pdf"
    assert recorded["fetched_date"] == "2026-01-02"
    assert entry["provenance"]["directives"] == [
        {"verb": "ignore", "args": ["missing_doi"], "reason": "printed before DOIs existed"}
    ]
    assert entry["missing"] == []
    assert entry["truncated"] == {}


def test_what_the_library_lacks_is_listed_as_missing(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json(
        "ref", "show", str(bib), "--key", "Euler1748",
        "--select", "abstract", "--include", "provenance", "--include", "materials",
    )  # fmt: skip

    (entry,) = payload["entries"]
    assert entry["fields"] == {"abstract": None}
    assert entry["missing_fields"] == ["abstract"]
    assert entry["materials"]["pinax"]["available"] == []
    assert entry["missing"] == ["materials", "provenance"]


def test_only_the_named_parts_are_included(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json(
        "ref", "show", str(bib), "--key", "Newton1687", "--include", "provenance"
    )

    (entry,) = payload["entries"]
    assert "provenance" in entry and "materials" not in entry
    assert entry["missing"] == []
    assert payload["bounds"]["include"] == ["provenance"]


def test_unknown_parts_are_refused_and_abstract_points_at_select(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, payload = _json("ref", "show", str(bib), "--key", "Newton1687", "--include", "abstract")

    assert code == 1 and payload["error"] == "InvalidInput"
    assert "--select abstract" in payload["message"]


def test_without_pinax_the_store_is_reported_unconfigured(fixtures_dir: Path) -> None:
    _code, payload = _json(
        "ref",
        "show",
        str(fixtures_dir / "simple.bib"),
        "--key",
        "Smith2020",
        "--include",
        "materials",
    )

    assert payload["entries"][0]["materials"]["pinax"] == {"configured": False}


def test_truncation_is_reported_with_a_retrieval_hint(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json(
        "ref", "show", str(bib), "--key", "Newton1687,Hooke1665", "--abstract",
        "--max-chars", "20",
    )  # fmt: skip

    newton, hooke = payload["entries"]
    assert newton["summary"]["abstract"] == ABSTRACT[:20]
    assert newton["truncated"]["summary.abstract"] == {"length": len(ABSTRACT), "returned": 20}
    assert newton["truncated"]["summary.title"]["returned"] == 20
    assert hooke["truncated"] == {}
    assert payload["retrieve_full"]["keys"] == ["Newton1687"]
    assert payload["bounds"] == {"select": None, "include": [], "max_chars": 20, "limit": None}


def test_select_replaces_the_summary_with_the_named_fields(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json("ref", "show", str(bib), "--key", "Euler1748", "--select", "title,doi")

    (entry,) = payload["entries"]
    assert "summary" not in entry
    assert entry["fields"] == {"title": "Introductio in analysin infinitorum", "doi": None}
    assert entry["missing_fields"] == ["doi"]
    assert entry["omitted_fields"] == ["author", "year"]
    assert payload["retrieve_full"] is None


def test_paging_a_key_selection_under_a_stable_snapshot(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    keys = "Hooke1665,Newton1687,Euler1748"
    seen: list[str] = []
    cursor: list[str] = []
    while True:
        code, payload = _json("ref", "show", str(bib), "--key", keys, "--limit", "2", *cursor)
        assert code == 0
        seen += [entry["key"] for entry in payload["entries"]]
        if payload["page"]["complete"]:
            break
        cursor = ["--cursor", payload["page"]["next_cursor"]]

    assert seen == ["Hooke1665", "Newton1687", "Euler1748"]
    assert payload["page"]["total"] == 3


def test_a_cursor_is_refused_once_the_library_changes(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _code, first = _json("ref", "show", str(bib), "--key", "Hooke1665,Euler1748", "--limit", "1")
    runner.invoke(app, ["ref", "edit", str(bib), "Euler1748", "--field", "note=second issue"])

    code, payload = _json(
        "ref", "show", str(bib), "--key", "Hooke1665,Euler1748", "--limit", "1",
        "--cursor", first["page"]["next_cursor"],
    )  # fmt: skip

    assert code == 2
    assert payload["error"] == "StaleCursor"
    assert payload["options"][0]["id"] == "restart"


def test_a_cursor_from_another_selection_is_invalid_input(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    _code, first = _json("ref", "show", str(bib), "--key", "Hooke1665,Euler1748", "--limit", "1")

    code, payload = _json(
        "ref", "show", str(bib), "--key", "Newton1687,Euler1748",
        "--cursor", first["page"]["next_cursor"],
    )  # fmt: skip

    assert code == 1 and payload["error"] == "InvalidInput"


def test_paging_options_need_a_key_selection(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, payload = _json("ref", "show", str(bib), "Euler1748", "--limit", "1")

    assert code == 1 and payload["error"] == "InvalidInput"


def test_single_key_bounded_form(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json(
        "ref", "show", str(bib), "Newton1687", "--select", "abstract,doi", "--max-chars", "5"
    )

    assert payload["key"] == "Newton1687"
    assert payload["fields"] == {"abstract": ABSTRACT[:5], "doi": None}
    assert payload["missing_fields"] == ["doi"]
    assert payload["truncated"] == {"fields.abstract": {"length": len(ABSTRACT), "returned": 5}}


def test_single_key_without_bounds_is_unchanged(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json("ref", "show", str(bib), "Euler1748")

    assert set(payload) == {
        "status", "action", "file", "source_sha256", "warnings",
        "key", "entry_type", "fields", "resolved",
    }  # fmt: skip


def test_human_context_output(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    result = runner.invoke(
        app, ["ref", "show", str(bib), "--key", "Newton1687,Euler1748", "--include", "materials,provenance",
              "--max-chars", "30", "--limit", "1"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert "pinax: published_pdf; linked files: 1/1 found" in result.output
    assert "directive: ignore missing_doi -- printed before DOIs existed" in result.output
    assert "Showing 1-1 of 2; continue with --cursor c1." in result.output


def test_duplicate_keys_are_flagged_not_merged(fixtures_dir: Path) -> None:
    coll = Bibliography.open(fixtures_dir / "duplicate_entries.bib")
    reader = EntryReader(coll)

    records = [
        reader.record(entry, include=("materials", "provenance"))
        for entry in coll.lib.entries.values()
    ]

    assert len(records) == len(coll.lib.entries.values())
    assert all(record["duplicate_key"] for record in records if record["key"] == "Smith2020")


def test_an_unreadable_manifest_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    (tmp_path / "lib.files" / ".pinax" / "manifest.json").write_text("[]", encoding="utf-8")

    code, payload = _json("ref", "show", str(bib), "--key", "Newton1687", "--include", "provenance")

    assert code == 0
    assert payload["warnings"][0]["type"] == "pinax_manifest_unreadable"
    assert payload["entries"][0]["provenance"]["materials"] == {}


# --- search pages like every bounded read ---------------------------------------


def test_search_pages_and_truncates(fixtures_dir: Path) -> None:
    bib = str(fixtures_dir / "simple.bib")
    _code, first = _json("search", bib, "", "--where", "year > 2000", "--limit", "3")
    _code, rest = _json(
        "search", bib, "", "--where", "year > 2000", "--limit", "3",
        "--cursor", first["page"]["next_cursor"], "--max-chars", "8",
    )  # fmt: skip

    keys = [match["key"] for match in first["matches"] + rest["matches"]]
    assert keys == ["Smith2020", "Jones2021", "Brown2022", "Green2023", "White2024"]
    assert rest["page"]["complete"] and rest["page"]["total"] == 5
    assert rest["matches"][0]["fields"]["title"] == "Quantum "
    assert rest["matches"][0]["truncated"]["title"]["returned"] == 8


def test_search_limit_zero_counts(fixtures_dir: Path) -> None:
    _code, payload = _json("search", str(fixtures_dir / "simple.bib"), "learning", "--limit", "0")

    assert payload["count"] == 0 and payload["page"]["total"] == 2


def test_single_key_bounded_human_output(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    result = runner.invoke(
        app,
        ["ref", "show", str(bib), "Newton1687", "--include", "materials,provenance", "--select", "title,doi",
         "--max-chars", "12"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert "  title = Philosophiae…" in result.output
    assert "  doi = (none)" in result.output
    assert "  materials: pinax: published_pdf; linked files: 1/1 found" in result.output
    assert "  provenance: published_pdf from https://example.org/principia.pdf (2026-01-02)" in (
        result.output
    )


def test_single_key_with_include_keeps_every_field(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json("ref", "show", str(bib), "Euler1748", "--include", "materials")

    assert list(payload["fields"]) == ["author", "title", "year"]
    assert "missing_fields" not in payload and "omitted_fields" not in payload
    assert payload["missing"] == ["materials"]


def test_search_in_scopes_matching_and_select_scopes_output(fixtures_dir: Path) -> None:
    bib = str(fixtures_dir / "simple.bib")

    _code, payload = _json("search", bib, "learning", "--in", "title", "--select", "doi")

    assert [match["key"] for match in payload["matches"]] == ["Smith2020", "Brown2022"]
    assert payload["matches"][0]["matched_fields"] == ["title"]
    assert payload["matches"][0]["fields"] == {"doi": "10.1234/nature.ml.2020"}
    assert payload["matches"][1]["missing_fields"] == ["doi"]
    assert "title" in payload["matches"][1]["omitted_fields"]
    assert payload["in_fields"] == ["title"]
    assert payload["warnings"] == []


def test_search_in_alone_returns_every_field(fixtures_dir: Path) -> None:
    _code, payload = _json("search", str(fixtures_dir / "simple.bib"), "learning", "--in", "title")

    assert "journal" in payload["matches"][0]["fields"]
    assert "missing_fields" not in payload["matches"][0]


def test_search_abstract_joins_a_selection(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    _code, payload = _json("search", str(bib), "Principia", "--select", "year", "--abstract")

    assert payload["matches"][0]["fields"] == {"year": "1687", "abstract": ABSTRACT}
