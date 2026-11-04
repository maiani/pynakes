"""New references follow declared ordering without rewriting existing blocks."""

import pytest
from typer.testing import CliRunner

from pynakes.batch import apply_operations
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.engine import Bibliography


@pytest.mark.parametrize("le", ["\n", "\r\n"])
@pytest.mark.parametrize(
    "order,expected",
    [("key", ["A", "B", "C"]), ("key:desc", ["C", "B", "A"]), ("original", ["A", "C", "B"])],
)
def test_insert_preserves_existing_bytes_and_comments(le, order, expected):
    keys = ["C", "A"] if order.endswith("desc") else ["A", "C"]
    blocks = [f'% note for {key}{le}@book{{{key}, title = "Original {key}"}}' for key in keys]
    text = f"@comment{{pynakes-meta: sort-order:{order};}}{le}{le}" + (le * 2).join(blocks) + le
    coll = Bibliography.from_text(text)
    coll.add_entry("book", "B", {"title": "New"})
    preview = coll.preview()
    assert list(coll.entries.keys()) == expected
    assert list(parse_bib(preview).entries.keys()) == expected
    for block in blocks:
        assert block in preview
    assert preview == coll.preview()


def test_unsorted_insertion_and_stable_ties():
    coll = Bibliography.from_text(
        "@comment{pynakes-meta: sort-order:year:desc,key; }\n\n"
        "@book{Z, year={1800}}\n\n@book{A, year={1900}}\n"
    )
    coll.add_entry("book", "B", {"year": "1850"})
    coll.add_entry("book", "C", {"year": "1850"})
    assert list(parse_bib(coll.preview()).entries.keys()) == ["Z", "A", "B", "C"]
    coll = Bibliography.from_text(
        "@comment{pynakes-meta: sort-order:year;}\n@book{A, year={1800}}\n"
    )
    coll.add_entry("book", "B", {"year": "1800"})
    assert list(parse_bib(coll.preview()).entries.keys()) == ["A", "B"]


def test_batch_multiple_insertions_and_edit_keep_model_order():
    coll = Bibliography.from_text(
        "@comment{pynakes-meta: sort-order:key;}\n\n@book{C, title={Old}}\n"
    )
    apply_operations(
        coll,
        [
            {"op": "ref.add", "entry_type": "book", "key": "B", "fields": {"title": "B"}},
            {"op": "ref.add", "entry_type": "book", "key": "A", "fields": {"title": "A"}},
            {"op": "fields.set", "field": "title", "value": "Changed", "where": "key = C"},
        ],
    )
    assert list(parse_bib(coll.preview()).entries.keys()) == ["A", "B", "C"]
    assert parse_bib(coll.preview()).entries["C"].fields["title"] == "Changed"


@pytest.mark.parametrize("command", ["add", "import"])
def test_cli_insertion(tmp_path, monkeypatch, command):
    path = tmp_path / "refs.bib"
    old = "@book{C, title={Original}}\n"
    path.write_text("@comment{pynakes-meta: sort-order:key;}\n\n" + old, encoding="utf-8")
    monkeypatch.setattr(
        "pynakes.importer.fetch_bibtex_for_doi", lambda doi: "@book{Provider, title={New}}"
    )
    monkeypatch.setattr("pynakes.importer.fetch_crossref_work", lambda doi: {})
    args = (
        ["10.5555/example", "--key", "B"]
        if command == "import"
        else ["B", "--type", "misc", "--field", "title=New"]
    )
    result = CliRunner().invoke(app, ["ref", command, str(path), *args, "--json"])
    assert result.exit_code == 0, result.output
    text = path.read_text(encoding="utf-8")
    assert old in text
    assert list(parse_bib(text).entries.keys()) == ["B", "C"]


def test_append_without_setting_preserves_no_final_newline():
    coll = Bibliography.from_text("@book{C, title={Original}}")
    coll.add_entry("book", "A", {})
    assert list(parse_bib(coll.preview()).entries.keys()) == ["C", "A"]
    assert not coll.preview().endswith("\n")
