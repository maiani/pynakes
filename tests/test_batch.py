"""Tests for transactional batch operations."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import batch as batch_ops
from pynakes.batch import BatchError, OperationSpec, apply_operations, operation_catalog
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.engine import Bibliography

runner = CliRunner()

SRC = "@article{A,\n  title = {t},\n  journal = {Nature Machine Intelligence}\n}\n"


def test_apply_operations_runs_in_order() -> None:
    coll = Bibliography.from_text(SRC)
    results = apply_operations(
        coll,
        [
            {"op": "groups.add_entry", "key": "A", "group": "ML"},
            {"op": "fields.append", "field": "keywords", "value": "ml"},
        ],
    )
    assert [r["op"] for r in results] == ["groups.add_entry", "fields.append"]
    assert "ML" in coll.lib.entries["A"].fields["groups"]
    assert coll.lib.entries["A"].fields["keywords"] == "ml"


def test_unknown_op_raises_batch_error_with_index() -> None:
    coll = Bibliography.from_text(SRC)
    try:
        apply_operations(coll, [{"op": "nope"}])
        raise AssertionError("expected BatchError")
    except BatchError as exc:
        assert exc.index == 0


def test_bad_params_raise_batch_error() -> None:
    coll = Bibliography.from_text(SRC)
    for bad in (
        {"op": "fields.rename", "old": "a"},
        {"op": "groups.add_entry", "key": "A", "x": 1},
    ):
        try:
            apply_operations(coll, [bad])
            raise AssertionError("expected BatchError")
        except BatchError:
            pass


def test_operation_catalog_lists_specs() -> None:
    cat = operation_catalog()
    assert "fields.rename" in cat
    assert cat["fields.rename"]["required"] == ["old", "new"]


def test_every_declared_operation_has_a_dispatch_branch() -> None:
    operations = {
        "fields.rename": {"old": "journal", "new": "journaltitle"},
        "fields.move": {"old": "journal", "new": "journaltitle"},
        "fields.append": {"field": "keywords", "value": "ml"},
        "fields.clear": {"field": "journal"},
        "fields.protect_title": {},
        "groups.add_entry": {"key": "A", "group": "ML"},
        "groups.remove_entry": {"key": "A", "group": "ML"},
        "keys.generate": {},
        "keys.repair": {},
        "keys.rename": {"old": "A", "new": "Renamed"},
        "normalize": {},
        "convert": {"to": "biblatex"},
        "metadata.set": {"key": "lint-required-fields", "value": "url"},
        "fields.set": {"field": "note", "value": "checked"},
        "ref.add": {"key": "B", "entry_type": "article"},
        "ref.edit": {"key": "A", "fields": {"year": "2020"}},
        "ref.remove": {"key": "A"},
        "dedupe.merge": {},
    }

    assert set(operations) == set(batch_ops.OPERATION_SPECS)
    for op, params in operations.items():
        coll = Bibliography.from_text(SRC)
        apply_operations(coll, [{"op": op, **params}])


DUPLICATE_PAIR = (
    "@article{Alpha1,\n  author = {Ada Lovelace},\n  title = {On Engines},\n"
    "  journal = {Notes},\n  year = {1843},\n  doi = {10.5555/engines}\n}\n\n"
    "@article{Alpha2,\n  author = {Ada Lovelace},\n  title = {On Engines},\n"
    "  journal = {Notes},\n  year = {1843},\n  doi = {10.5555/engines},\n"
    "  note = {Offprint}\n}\n"
)


def test_fields_set_participates_in_a_batch() -> None:
    """Every other `fields` subcommand was batchable; `set` was the one left out."""
    coll = Bibliography.from_text(SRC)

    results = apply_operations(coll, [{"op": "fields.set", "field": "year", "value": "1687"}])

    assert results[0]["result"] == {"changed": 1}
    assert coll.lib.entries["A"].fields["year"] == "1687"


def test_entry_level_operations_compose_in_one_batch() -> None:
    """The shape an agent proposes: add one, drop another, retag what is left."""
    coll = Bibliography.from_text(SRC + "@article{B,\n  title = {other}\n}\n")

    apply_operations(
        coll,
        [
            {"op": "ref.add", "key": "C", "entry_type": "book", "fields": {"title": "New"}},
            {"op": "ref.remove", "key": "B"},
            {"op": "fields.set", "field": "keywords", "value": "to-read"},
        ],
    )

    assert sorted(coll.lib.entries.keys()) == ["A", "C"]
    assert coll.lib.entries["C"].type == "book"
    assert coll.lib.entries["A"].fields["keywords"] == "to-read"
    assert coll.lib.entries["C"].fields["keywords"] == "to-read"


def test_ref_remove_of_an_unknown_key_aborts_the_batch() -> None:
    """Silently removing nothing would let a wrong key pass for a successful batch."""
    coll = Bibliography.from_text(SRC)

    with pytest.raises(ValueError, match="Nobody1999"):
        apply_operations(
            coll,
            [
                {"op": "fields.set", "field": "note", "value": "x"},
                {"op": "ref.remove", "key": "Nobody1999"},
            ],
        )


def test_ref_add_on_a_taken_key_aborts_rather_than_appending() -> None:
    coll = Bibliography.from_text(SRC)

    with pytest.raises(ValueError):
        apply_operations(coll, [{"op": "ref.add", "key": "A", "entry_type": "article"}])


def test_dedupe_merge_in_a_batch_can_target_one_cluster() -> None:
    coll = Bibliography.from_text(DUPLICATE_PAIR)

    results = apply_operations(coll, [{"op": "dedupe.merge", "keys": ["Alpha2"]}])

    assert results[0]["result"]["merged_clusters"] == 1
    assert sorted(coll.lib.entries.keys()) == ["Alpha1"]


def test_ref_import_stays_out_of_the_batch_vocabulary() -> None:
    """A batch is approved once as one diff; replaying it must not depend on a
    provider's answer at the time it ran."""
    assert "ref.import" not in batch_ops.OPERATION_SPECS


def test_declared_but_undispatched_operation_raises_not_implemented(monkeypatch) -> None:
    monkeypatch.setitem(batch_ops.OPERATION_SPECS, "debug.unhandled", OperationSpec())
    coll = Bibliography.from_text(SRC)

    with pytest.raises(NotImplementedError, match="debug.unhandled"):
        apply_operations(coll, [{"op": "debug.unhandled"}])


def test_protect_title_warns_when_matching_entries_lack_field() -> None:
    coll = Bibliography.from_text("@article{A,\n  year = {2024}\n}\n")

    result = apply_operations(coll, [{"op": "fields.protect_title"}])

    assert result[0]["result"] == {
        "changed": 0,
        "warnings": ["No matching entries had field 'title'"],
    }


def test_cli_batch_atomic_commit(tmp_path: Path) -> None:
    bib = tmp_path / "r.bib"
    bib.write_text(SRC)
    ops = json.dumps(
        [
            {"op": "groups.add_entry", "key": "A", "group": "ML"},
            {"op": "normalize", "journal_style": "abbreviated"},
        ]
    )
    result = runner.invoke(app, ["corpus", "batch", str(bib), "--ops", ops, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["action"] == "batch"
    assert len(data["operations"]) == 2
    assert data["plan"]["summary"]["modified"] == 1
    reparsed = parse_bib(bib.read_text())
    assert "ML" in reparsed.entries["A"].fields["groups"]
    assert reparsed.entries["A"].fields["journal"] == "Nat. Mach. Intell."


def test_cli_batch_failure_writes_nothing(tmp_path: Path) -> None:
    bib = tmp_path / "r.bib"
    original = SRC
    bib.write_text(original)
    ops = json.dumps(
        [
            {"op": "groups.add_entry", "key": "A", "group": "ML"},
            {"op": "bogus.op"},
        ]
    )
    result = runner.invoke(app, ["corpus", "batch", str(bib), "--ops", ops, "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"
    assert bib.read_text() == original  # all-or-nothing


def test_cli_batch_requires_exactly_one_source(tmp_path: Path) -> None:
    bib = tmp_path / "r.bib"
    bib.write_text(SRC)
    result = runner.invoke(app, ["corpus", "batch", str(bib), "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"


def test_cli_batch_reads_ops_file_and_reports_human_result(tmp_path: Path) -> None:
    bib = tmp_path / "r.bib"
    bib.write_text(SRC)
    ops_file = tmp_path / "ops.json"
    ops_file.write_text(json.dumps([{"op": "fields.append", "field": "keywords", "value": "ml"}]))

    result = runner.invoke(app, ["corpus", "batch", str(bib), "--ops-file", str(ops_file)])

    assert result.exit_code == 0, result.output
    assert "Applied 1 operation" in result.output
    assert "keywords = {ml}" in bib.read_text()


def test_cli_batch_rejects_two_sources_and_bad_json(tmp_path: Path) -> None:
    bib = tmp_path / "r.bib"
    bib.write_text(SRC)
    ops_file = tmp_path / "ops.json"
    ops_file.write_text("[]")

    both = runner.invoke(
        app,
        ["corpus", "batch", str(bib), "--ops", "[]", "--ops-file", str(ops_file), "--json"],
    )
    assert both.exit_code == 1, both.output
    assert json.loads(both.output)["error"] == "InvalidInput"

    malformed = runner.invoke(app, ["corpus", "batch", str(bib), "--ops", "not-json", "--json"])
    assert malformed.exit_code == 1, malformed.output
    assert "not valid JSON" in json.loads(malformed.output)["message"]
