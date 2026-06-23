"""Tests for whole-file set operations: merge_libraries, partition_library, CLI."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.setops import (
    PartitionRule,
    compile_predicate,
    merge_libraries,
    partition_library,
)

runner = CliRunner()

A = "@article{Smith2020,\n  title = {Alpha},\n  groups = {ML}\n}\n"
B = "@article{Jones2021,\n  title = {Beta},\n  groups = {Bio}\n}\n"


# --- merge_libraries -------------------------------------------------------


def test_merge_concatenates_and_reports_duplicate_keys() -> None:
    a = parse_bib(A + B)
    b = parse_bib("@article{Smith2020,\n  title = {Alpha},\n  groups = {ML}\n}\n")
    result = merge_libraries([("a.bib", a), ("b.bib", b)])

    assert len(result.lib.entries) == 3  # nothing dropped without --dedupe
    assert result.duplicate_keys == ["Smith2020"]
    assert result.conflicts == []


def test_merge_dedupe_collapses_identical_keys() -> None:
    a = parse_bib(A)
    b = parse_bib(A)  # byte-identical entry, same key
    result = merge_libraries([("a.bib", a), ("b.bib", b)], dedupe=True)

    assert len(result.lib.entries) == 1
    assert result.conflicts == []


def test_merge_dedupe_reports_conflict_on_differing_same_key() -> None:
    a = parse_bib("@article{Smith2020,\n  title = {Alpha}\n}\n")
    b = parse_bib("@article{Smith2020,\n  title = {DIFFERENT}\n}\n")
    result = merge_libraries([("a.bib", a), ("b.bib", b)], dedupe=True)

    assert [c["key"] for c in result.conflicts] == ["Smith2020"]
    # First occurrence is kept so the lib is still previewable.
    assert result.lib.entries["Smith2020"].fields["title"] == "Alpha"


def test_merged_entries_round_trip_byte_for_byte() -> None:
    a = parse_bib(A)
    b = parse_bib(B)
    result = merge_libraries([("a.bib", a), ("b.bib", b)])
    out = write_bib(result.lib)
    assert A.rstrip() in out
    assert B.rstrip() in out


# --- predicates & partition ------------------------------------------------


def test_compile_predicate_variants() -> None:
    e_ml = parse_bib(A).entries["Smith2020"]
    e_bio = parse_bib(B).entries["Jones2021"]

    assert compile_predicate("*")(e_ml) is True
    assert compile_predicate('group "ML"')(e_ml) is True
    assert compile_predicate('group "ML"')(e_bio) is False
    assert compile_predicate("title contains alpha")(e_ml) is True
    assert compile_predicate("used", {"Smith2020"})(e_ml) is True
    assert compile_predicate("unused", {"Smith2020"})(e_bio) is True


def test_partition_first_match_is_a_partition() -> None:
    lib = parse_bib(A + B)
    rules = [PartitionRule("ml.bib", 'group "ML"'), PartitionRule("rest.bib", "*")]
    result = partition_library(lib, rules)

    assert result.counts == {"ml.bib": 1, "rest.bib": 1}
    assert result.unrouted == 0
    assert list(result.buckets["ml.bib"].entries.keys()) == ["Smith2020"]
    assert list(result.buckets["rest.bib"].entries.keys()) == ["Jones2021"]


def test_partition_copy_sends_to_every_match() -> None:
    lib = parse_bib(A + B)
    rules = [PartitionRule("ml.bib", 'group "ML"'), PartitionRule("all.bib", "*")]
    result = partition_library(lib, rules, copy=True)

    # Smith2020 lands in both ml.bib and all.bib under --copy.
    assert result.counts == {"ml.bib": 1, "all.bib": 2}


def test_partition_reports_unrouted_when_no_catch_all() -> None:
    lib = parse_bib(A + B)
    result = partition_library(lib, [PartitionRule("ml.bib", 'group "ML"')])
    assert result.counts == {"ml.bib": 1}
    assert result.unrouted == 1


def test_partition_used_unused_split() -> None:
    lib = parse_bib(A + B)
    rules = [PartitionRule("used.bib", "used"), PartitionRule("unused.bib", "*")]
    result = partition_library(lib, rules, cited_keys={"Smith2020"})
    assert list(result.buckets["used.bib"].entries.keys()) == ["Smith2020"]
    assert list(result.buckets["unused.bib"].entries.keys()) == ["Jones2021"]


# --- CLI: merge ------------------------------------------------------------


def _write(dir_: Path, name: str, content: str) -> str:
    path = dir_ / name
    path.write_text(content)
    return str(path)


def test_cli_merge_writes_combined_file(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["merge", a, b, "--out", out, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["action"] == "merge"
    assert data["entries"] == 2
    assert data["written"] is True
    reparsed = parse_bib(Path(out).read_text())
    assert set(reparsed.entries.keys()) == {"Smith2020", "Jones2021"}


def test_cli_merge_dry_run_writes_nothing(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["merge", a, b, "--out", out, "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["written"] is False
    assert not Path(out).exists()


def test_cli_merge_dedupe_conflict_exits_2(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", "@article{Smith2020,\n  title = {Alpha}\n}\n")
    b = _write(tmp_path, "2.bib", "@article{Smith2020,\n  title = {Other}\n}\n")
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["merge", a, b, "--out", out, "--dedupe", "--json"])
    assert result.exit_code == 2, result.output
    data = json.loads(result.output)
    assert data["status"] == "conflict"
    assert data["error"] == "DuplicateMergeKey"
    assert not Path(out).exists()


# --- CLI: split ------------------------------------------------------------


def test_cli_split_by_group(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    ml = str(tmp_path / "ml.bib")
    rest = str(tmp_path / "rest.bib")
    result = runner.invoke(
        app, ["split", a, b, "--to", f'{ml}=group "ML"', "--to", f"{rest}=*", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["action"] == "split"
    assert {o["file"]: o["entries"] for o in data["outputs"]} == {ml: 1, rest: 1}
    assert list(parse_bib(Path(ml).read_text()).entries.keys()) == ["Smith2020"]
    assert list(parse_bib(Path(rest).read_text()).entries.keys()) == ["Jones2021"]


def test_cli_split_used_unused_with_tex(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    tex = _write(tmp_path, "paper.tex", r"\cite{Smith2020}")
    used = str(tmp_path / "used.bib")
    unused = str(tmp_path / "unused.bib")
    result = runner.invoke(
        app,
        ["split", a, b, "--tex", tex, "--to", f"{used}=used", "--to", f"{unused}=*", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert list(parse_bib(Path(used).read_text()).entries.keys()) == ["Smith2020"]
    assert list(parse_bib(Path(unused).read_text()).entries.keys()) == ["Jones2021"]


def test_cli_split_bad_rule_errors(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    result = runner.invoke(app, ["split", a, "--to", "no-equals-sign", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"


def test_cli_split_used_without_sources_errors(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    out = str(tmp_path / "u.bib")
    result = runner.invoke(app, ["split", a, "--to", f"{out}=used", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"


# --- CLI: human output and remaining branches ------------------------------


def test_cli_merge_human_output_with_diff(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["merge", a, b, "--out", out, "--diff"])
    assert result.exit_code == 0, result.output
    assert "Merged 2 file(s)" in result.output
    assert "Wrote" in result.output
    assert "Smith2020" in result.output  # diff body shown


def test_cli_merge_reports_duplicate_keys_human(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", A)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["merge", a, b, "--out", out])
    assert result.exit_code == 0, result.output
    assert "duplicate key(s): Smith2020" in result.output


def test_cli_split_human_output_with_diff_and_unrouted(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    ml = str(tmp_path / "ml.bib")
    result = runner.invoke(app, ["split", a, b, "--to", f'{ml}=group "ML"', "--diff"])
    assert result.exit_code == 0, result.output
    assert "Split 2 input(s) into 1 output(s)" in result.output
    assert "matched no output" in result.output  # Jones2021 is unrouted
    assert "Smith2020" in result.output  # diff body


def test_cli_split_dry_run_writes_nothing(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    ml = str(tmp_path / "ml.bib")
    result = runner.invoke(app, ["split", a, "--to", f"{ml}=*", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["outputs"][0]["written"] is False
    assert not Path(ml).exists()


def test_cli_split_copy_overlaps(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    ml = str(tmp_path / "ml.bib")
    allf = str(tmp_path / "all.bib")
    result = runner.invoke(
        app, ["split", a, "--copy", "--to", f'{ml}=group "ML"', "--to", f"{allf}=*", "--json"]
    )
    assert result.exit_code == 0, result.output
    counts = {o["file"]: o["entries"] for o in json.loads(result.output)["outputs"]}
    assert counts == {ml: 1, allf: 1}  # Smith2020 in both


def test_cli_split_duplicate_to_target_errors(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    dup = str(tmp_path / "x.bib")
    result = runner.invoke(app, ["split", a, "--to", f"{dup}=*", "--to", f"{dup}=used", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"
