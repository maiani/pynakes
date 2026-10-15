"""Acting on cited entries: ``--where used`` replaces ``tex scan``'s write options."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.engine import Bibliography

runner = CliRunner()

LIBRARY = (
    "@comment{pynakes-meta:\ntex-sources: paper.tex\n}\n\n"
    "@book{Newton1687,\n  title = {Principia}\n}\n\n"
    "@book{Euler1748,\n  title = {Introductio}\n}\n"
)


def _library(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    (tmp_path / "paper.tex").write_text("\\cite{Euler1748}\n", encoding="utf-8")
    return bib


def _json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    assert "Traceback" not in result.output
    return result.exit_code, json.loads(result.output)


def test_a_plain_scan_reports_no_deprecation_and_no_change(tmp_path: Path) -> None:
    bib = _library(tmp_path)

    code, payload = _json("tex", "scan", str(bib))

    assert code == 0 and payload["warnings"] == []
    assert payload["report"]["used"] == ["Euler1748"]
    assert payload["plan"]["summary"]["modified"] == 0 and payload["plan"]["entries"] == []


def test_scan_write_options_still_work_and_say_they_are_deprecated(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    out = tmp_path / "cited.bib"

    code, payload = _json("tex", "scan", str(bib), "--keyword", "cited", "--out", str(out))

    assert code == 0 and out.exists()
    deprecated = {w["old"] for w in payload["warnings"] if w["type"] == "deprecated"}
    assert deprecated == {"tex scan --out", "tex scan --keyword"}
    assert "keywords = {cited}" in bib.read_text(encoding="utf-8")


def test_where_used_tags_what_scan_keyword_tagged(tmp_path: Path) -> None:
    tagged_by_scan = _library(tmp_path / "a")
    tagged_by_where = _library(tmp_path / "b")

    runner.invoke(app, ["tex", "scan", str(tagged_by_scan), "--keyword", "cited"])
    runner.invoke(
        app, ["fields", "append", str(tagged_by_where), "keywords", "cited", "--where", "used"]
    )

    assert tagged_by_scan.read_bytes() == tagged_by_where.read_bytes()


def test_combine_where_used_exports_the_cited_entries(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    out = tmp_path / "cited.bib"

    code, _payload = _json("corpus", "combine", str(bib), "--where", "used", "--out", str(out))

    assert code == 0
    assert list(Bibliography.open(out).lib.entries.keys()) == ["Euler1748"]


def test_split_reads_linked_sources_without_tex_or_aux(tmp_path: Path) -> None:
    bib = _library(tmp_path)
    cited, rest = tmp_path / "cited.bib", tmp_path / "rest.bib"

    code, payload = _json(
        "corpus", "split", str(bib), "--route", f"{cited}=used", "--route", f"{rest}=*"
    )

    assert code == 0, payload
    assert list(Bibliography.open(cited).lib.entries.keys()) == ["Euler1748"]
    assert list(Bibliography.open(rest).lib.entries.keys()) == ["Newton1687"]


def test_split_without_any_sources_is_no_sources(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY.replace("tex-sources: paper.tex", "dialect: biblatex"))

    code, payload = _json("corpus", "split", str(bib), "--route", f"{tmp_path / 'x.bib'}=used")

    assert code == 1 and payload["error"] == "NoSources"
