"""Tests for transactional batch operations."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.batch import BatchError, apply_operations, operation_catalog
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.engine import Collection

runner = CliRunner()

SRC = "@article{A,\n  title = {t},\n  journal = {Nature Machine Intelligence}\n}\n"


def test_apply_operations_runs_in_order() -> None:
    coll = Collection.from_text(SRC)
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
    coll = Collection.from_text(SRC)
    try:
        apply_operations(coll, [{"op": "nope"}])
        raise AssertionError("expected BatchError")
    except BatchError as exc:
        assert exc.index == 0


def test_bad_params_raise_batch_error() -> None:
    coll = Collection.from_text(SRC)
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


def test_cli_batch_atomic_commit(tmp_path: Path) -> None:
    bib = tmp_path / "r.bib"
    bib.write_text(SRC)
    ops = json.dumps(
        [
            {"op": "groups.add_entry", "key": "A", "group": "ML"},
            {"op": "normalize", "journal_style": "abbreviated"},
        ]
    )
    result = runner.invoke(app, ["batch", str(bib), "--ops", ops, "--json"])
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
    result = runner.invoke(app, ["batch", str(bib), "--ops", ops, "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"
    assert bib.read_text() == original  # all-or-nothing


def test_cli_batch_requires_exactly_one_source(tmp_path: Path) -> None:
    bib = tmp_path / "r.bib"
    bib.write_text(SRC)
    result = runner.invoke(app, ["batch", str(bib), "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "error"
