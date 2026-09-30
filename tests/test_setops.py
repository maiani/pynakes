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
    strip_metadata_blocks,
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


def test_compile_predicate_composes_bucket_and_field_predicates() -> None:
    # A bucket accepts anything --where accepts, so a routing rule can be as
    # precise as a selection: cited, but only the ones still in a group.
    e_ml = parse_bib(A).entries["Smith2020"]
    e_bio = parse_bib(B).entries["Jones2021"]
    predicate = compile_predicate('used and not group "Bio"', {"Smith2020", "Jones2021"})

    assert predicate(e_ml) is True
    assert predicate(e_bio) is False


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


def test_strip_metadata_blocks_drops_jabref_and_pynakes_meta() -> None:
    lib = parse_bib(
        A
        + "@comment{pynakes-meta:\npinax-files-dir: refs.files\n}\n\n"
        + "@Comment{jabref-meta: databaseType:bibtex;}\n\n"
        + "% a plain top-level comment, not metadata\n"
    )
    assert lib.pynakes_metadata_blocks and lib.jabref_metadata_blocks

    stripped = strip_metadata_blocks(lib)

    assert stripped is lib
    assert lib.pynakes_metadata_blocks == []
    assert lib.jabref_metadata_blocks == []
    assert len(lib.raw_comments) == 1
    assert "a plain top-level comment" in lib.raw_comments[0]
    out = write_bib(lib)
    assert "pynakes-meta" not in out
    assert "jabref-meta" not in out
    assert "a plain top-level comment" in out
    assert "Smith2020" in out


# --- CLI: merge ------------------------------------------------------------


def _write(dir_: Path, name: str, content: str) -> str:
    path = dir_ / name
    path.write_text(content)
    return str(path)


def test_cli_combine_writes_combined_file(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["corpus", "combine", a, b, "--out", out, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["action"] == "combine"
    assert data["entries"] == 2
    assert data["written"] is True
    reparsed = parse_bib(Path(out).read_text())
    assert set(reparsed.entries.keys()) == {"Smith2020", "Jones2021"}


def test_cli_combine_where_keeps_only_matching_entries(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")

    result = runner.invoke(
        app,
        ["corpus", "combine", a, b, "--out", out, "--where", 'group "Bio"', "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["where"] == 'group "Bio"'
    assert data["entries"] == 1
    assert set(parse_bib(Path(out).read_text()).entries.keys()) == {"Jones2021"}


def test_cli_combine_where_error_is_structured(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    out = tmp_path / "all.bib"

    result = runner.invoke(
        app, ["corpus", "combine", a, a, "--out", str(out), "--where", "title contains", "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "InvalidInput"
    assert not out.exists()


def test_cli_split_routes_by_a_composed_predicate(tmp_path: Path) -> None:
    source = _write(tmp_path, "refs.bib", A + B)
    keep = tmp_path / "keep.bib"
    rest = tmp_path / "rest.bib"

    result = runner.invoke(
        app,
        [
            "corpus",
            "split",
            source,
            "--to",
            f'{keep}=group "ML" and title contains alpha',
            "--to",
            f"{rest}=*",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert set(parse_bib(keep.read_text()).entries.keys()) == {"Smith2020"}
    assert set(parse_bib(rest.read_text()).entries.keys()) == {"Jones2021"}


def test_cli_combine_copies_pinax_materials_and_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.bib"
    source.write_text(
        "@article{Smith2020,\n  title = {Alpha}\n}\n"
        "@comment{pynakes-meta:\npinax-files-dir: source.files\n}\n"
    )
    source_files = tmp_path / "source.files"
    source_files.mkdir()
    (source_files / "Smith2020.preprint.pdf").write_bytes(b"pdf")
    (source_files / ".pinax").mkdir()
    (source_files / ".pinax" / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "files": {
                    "Smith2020": {
                        "preprint_canonical": True,
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
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")

    result = runner.invoke(app, ["corpus", "combine", str(source), b, "--out", out, "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pinax_materials"][0]["kind"] == "preprint_pdf"
    assert (tmp_path / "all.files" / "Smith2020.preprint.pdf").read_bytes() == b"pdf"
    combined = parse_bib(Path(out).read_text())
    assert combined.pynakes_metadata["pinax-files-dir"] == "all.files"
    manifest = json.loads((tmp_path / "all.files" / ".pinax" / "manifest.json").read_text())
    assert manifest["files"]["Smith2020"]["preprint_canonical"] is True


def test_cli_combine_dry_run_writes_nothing(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["corpus", "combine", a, b, "--out", out, "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["written"] is False
    assert not Path(out).exists()


def test_cli_combine_dedupe_conflict_exits_2(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", "@article{Smith2020,\n  title = {Alpha}\n}\n")
    b = _write(tmp_path, "2.bib", "@article{Smith2020,\n  title = {Other}\n}\n")
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["corpus", "combine", a, b, "--out", out, "--dedupe", "--json"])
    assert result.exit_code == 2, result.output
    data = json.loads(result.output)
    assert data["status"] == "conflict"
    assert data["error"] == "DuplicateMergeKey"
    assert not Path(out).exists()


def test_cli_combine_self_output_does_not_crash_on_own_materials(tmp_path: Path) -> None:
    # Regression (F14): `corpus combine A.bib B.bib --out A.bib` aborted with a
    # SameFileError copying A's own pinax materials onto themselves.
    primary = tmp_path / "primary.bib"
    primary.write_text(
        "@article{Shockley1949,\n  title = {Junctions}\n}\n"
        "@comment{pynakes-meta:\npinax-files-dir: primary.files\n}\n"
    )
    primary_files = tmp_path / "primary.files"
    primary_files.mkdir()
    (primary_files / "Shockley1949.published.pdf").write_bytes(b"own")
    harvest = _write(tmp_path, "harvest.bib", "@article{Bardeen1948,\n  title = {Transistor}\n}\n")

    result = runner.invoke(
        app, ["corpus", "combine", str(primary), harvest, "--out", str(primary), "--json"]
    )

    assert result.exit_code == 0, result.output
    combined = parse_bib(primary.read_text())
    assert set(combined.entries.keys()) == {"Shockley1949", "Bardeen1948"}
    # The library's own material is left untouched (the self-copy was skipped).
    assert (primary_files / "Shockley1949.published.pdf").read_bytes() == b"own"


def test_cli_combine_self_output_preserves_custom_files_dir(tmp_path: Path) -> None:
    # Regression (F14b): a self-combine must keep the library's own pinax-files-dir
    # rather than silently renaming it to the --out basename ("primary.files").
    primary = tmp_path / "primary.bib"
    primary.write_text(
        "@article{Shockley1949,\n  title = {Junctions}\n}\n"
        "@comment{pynakes-meta:\npinax-files-dir: materials\n}\n"
    )
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "Shockley1949.published.pdf").write_bytes(b"own")
    harvest = _write(tmp_path, "harvest.bib", "@article{Bardeen1948,\n  title = {Transistor}\n}\n")

    result = runner.invoke(
        app, ["corpus", "combine", str(primary), harvest, "--out", str(primary), "--json"]
    )

    assert result.exit_code == 0, result.output
    combined = parse_bib(primary.read_text())
    assert combined.pynakes_metadata["pinax-files-dir"] == "materials"


# --- CLI: split ------------------------------------------------------------


def test_cli_split_by_group(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    ml = str(tmp_path / "ml.bib")
    rest = str(tmp_path / "rest.bib")
    result = runner.invoke(
        app, ["corpus", "split", a, b, "--to", f'{ml}=group "ML"', "--to", f"{rest}=*", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["action"] == "split"
    assert {o["file"]: o["entries"] for o in data["outputs"]} == {ml: 1, rest: 1}
    assert list(parse_bib(Path(ml).read_text()).entries.keys()) == ["Smith2020"]
    assert list(parse_bib(Path(rest).read_text()).entries.keys()) == ["Jones2021"]


def test_cli_split_copies_pinax_materials_to_matching_output(tmp_path: Path) -> None:
    source = tmp_path / "source.bib"
    source.write_text(
        "@article{Smith2020,\n  title = {Alpha},\n  groups = {ML}\n}\n"
        "@article{Jones2021,\n  title = {Beta},\n  groups = {Bio}\n}\n"
        "@comment{pynakes-meta:\npinax-files-dir: source.files\n}\n"
    )
    source_files = tmp_path / "source.files"
    source_files.mkdir()
    (source_files / "Smith2020.preprint.pdf").write_bytes(b"pdf")
    ml = str(tmp_path / "ml.bib")
    rest = str(tmp_path / "rest.bib")

    result = runner.invoke(
        app,
        ["corpus", "split", str(source), "--to", f'{ml}=group "ML"', "--to", f"{rest}=*", "--json"],
    )

    assert result.exit_code == 0, result.output
    outputs = {item["file"]: item for item in json.loads(result.output)["outputs"]}
    assert outputs[ml]["pinax_materials"][0]["kind"] == "preprint_pdf"
    assert (tmp_path / "ml.files" / "Smith2020.preprint.pdf").read_bytes() == b"pdf"
    assert not (tmp_path / "rest.files" / "Smith2020.preprint.pdf").exists()
    assert parse_bib(Path(ml).read_text()).pynakes_metadata["pinax-files-dir"] == "ml.files"


def test_cli_split_catch_all_bucket_with_no_materials_does_not_crash(tmp_path: Path) -> None:
    # Regression: routing entries that have no actual linked files to a
    # discard-style destination (e.g. one that can't hold a companion
    # ``.files`` directory) must not fail just because the *source* library
    # has Pinax materials configured for other entries.
    source = tmp_path / "source.bib"
    source.write_text(
        "@article{Smith2020,\n  title = {Alpha},\n  groups = {ML}\n}\n"
        "@article{Jones2021,\n  title = {Beta},\n  groups = {Bio}\n}\n"
        "@comment{pynakes-meta:\npinax-files-dir: source.files\n}\n"
    )
    (tmp_path / "source.files").mkdir()  # no material files inside
    ml = str(tmp_path / "ml.bib")
    unwritable_catch_all = str(tmp_path / "no-such-dir" / "discard.bib")

    result = runner.invoke(
        app,
        [
            "corpus",
            "split",
            str(source),
            "--to",
            f'{ml}=group "ML"',
            "--to",
            f"{unwritable_catch_all}=*",
            "--json",
        ],
    )

    # The unwritable bucket is reported honestly (it used to claim success
    # with ``written: false``), as a clean error rather than a crash.
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["error"] == "IOError"
    assert [output["file"] for output in data["outputs"]] == [ml]
    assert not (tmp_path / "no-such-dir").exists()


def test_cli_split_minimal_drops_metadata_and_skips_materials(tmp_path: Path) -> None:
    source = tmp_path / "source.bib"
    source.write_text(
        "@comment{pynakes-meta:\npinax-files-dir: source.files\n}\n\n"
        "@Comment{jabref-meta: databaseType:bibtex;}\n\n"
        "@article{Smith2020,\n  title = {Alpha},\n  groups = {ML}\n}\n"
        "@article{Jones2021,\n  title = {Beta},\n  groups = {Bio}\n}\n"
    )
    source_files = tmp_path / "source.files"
    source_files.mkdir()
    (source_files / "Smith2020.preprint.pdf").write_bytes(b"pdf")
    ml = str(tmp_path / "ml.bib")
    rest = str(tmp_path / "rest.bib")

    result = runner.invoke(
        app,
        [
            "corpus",
            "split",
            str(source),
            "--to",
            f'{ml}=group "ML"',
            "--to",
            f"{rest}=*",
            "--minimal",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["minimal"] is True
    outputs = {item["file"]: item for item in data["outputs"]}
    assert outputs[ml]["pinax_materials"] == []
    assert not (tmp_path / "ml.files").exists()
    content = Path(ml).read_text()
    assert "pynakes-meta" not in content
    assert "jabref-meta" not in content
    assert "Smith2020" in content


def test_cli_split_without_minimal_keeps_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.bib"
    source.write_text(
        "@Comment{jabref-meta: databaseType:bibtex;}\n\n"
        "@article{Smith2020,\n  title = {Alpha},\n  groups = {ML}\n}\n"
    )
    ml = str(tmp_path / "ml.bib")

    result = runner.invoke(
        app, ["corpus", "split", str(source), "--to", f'{ml}=group "ML"', "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["minimal"] is False
    assert "jabref-meta" in Path(ml).read_text()


def test_cli_split_used_unused_with_tex(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    tex = _write(tmp_path, "paper.tex", r"\cite{Smith2020}")
    used = str(tmp_path / "used.bib")
    unused = str(tmp_path / "unused.bib")
    result = runner.invoke(
        app,
        [
            "corpus",
            "split",
            a,
            b,
            "--tex",
            tex,
            "--to",
            f"{used}=used",
            "--to",
            f"{unused}=*",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert list(parse_bib(Path(used).read_text()).entries.keys()) == ["Smith2020"]
    assert list(parse_bib(Path(unused).read_text()).entries.keys()) == ["Jones2021"]


def test_cli_split_bad_rule_errors(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    result = runner.invoke(app, ["corpus", "split", a, "--to", "no-equals-sign", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"


def test_cli_split_used_without_sources_errors(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    out = str(tmp_path / "u.bib")
    result = runner.invoke(app, ["corpus", "split", a, "--to", f"{out}=used", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"


# --- CLI: human output and remaining branches ------------------------------


def test_cli_combine_human_output_with_diff(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["corpus", "combine", a, b, "--out", out, "--diff"])
    assert result.exit_code == 0, result.output
    assert "Combined 2 file(s)" in result.output
    assert "Wrote" in result.output
    assert "Smith2020" in result.output  # diff body shown


def test_cli_combine_reports_duplicate_keys_human(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", A)
    out = str(tmp_path / "all.bib")
    result = runner.invoke(app, ["corpus", "combine", a, b, "--out", out])
    assert result.exit_code == 0, result.output
    assert "duplicate key(s): Smith2020" in result.output


def test_cli_split_human_output_with_diff_and_unrouted(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    b = _write(tmp_path, "2.bib", B)
    ml = str(tmp_path / "ml.bib")
    result = runner.invoke(app, ["corpus", "split", a, b, "--to", f'{ml}=group "ML"', "--diff"])
    assert result.exit_code == 0, result.output
    assert "Split 2 input(s) into 1 output(s)" in result.output
    assert "matched no output" in result.output  # Jones2021 is unrouted
    assert "Smith2020" in result.output  # diff body


def test_cli_split_dry_run_writes_nothing(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    ml = str(tmp_path / "ml.bib")
    result = runner.invoke(app, ["corpus", "split", a, "--to", f"{ml}=*", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["outputs"][0]["written"] is False
    assert not Path(ml).exists()


def test_cli_split_copy_overlaps(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    ml = str(tmp_path / "ml.bib")
    allf = str(tmp_path / "all.bib")
    result = runner.invoke(
        app,
        ["corpus", "split", a, "--copy", "--to", f'{ml}=group "ML"', "--to", f"{allf}=*", "--json"],
    )
    assert result.exit_code == 0, result.output
    counts = {o["file"]: o["entries"] for o in json.loads(result.output)["outputs"]}
    assert counts == {ml: 1, allf: 1}  # Smith2020 in both


def test_cli_split_duplicate_to_target_errors(tmp_path: Path) -> None:
    a = _write(tmp_path, "1.bib", A)
    dup = str(tmp_path / "x.bib")
    result = runner.invoke(
        app, ["corpus", "split", a, "--to", f"{dup}=*", "--to", f"{dup}=used", "--json"]
    )
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"


def test_merge_dedupe_detects_conflict_on_equivalent_but_not_identical_entries() -> None:
    a = parse_bib("@article{Smith2020,\n  title = {Alpha}\n}\n")
    b = parse_bib("@article{Smith2020,\n  title = {Alpha}\n}\n")
    c = parse_bib("@article{Smith2020,\n  title = Alpha\n}\n")
    result = merge_libraries([("a.bib", a), ("b.bib", b), ("c.bib", c)], dedupe=True)
    assert len(result.lib.entries) == 1
    assert len(result.conflicts) == 1, (
        "entries with same key, same fields, but different raw formatting "
        "should raise a formatting conflict rather than silently dropping one"
    )
