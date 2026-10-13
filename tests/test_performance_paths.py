"""Equivalence checks for indexed detection and shared read snapshots."""

import json
from itertools import product

from typer.testing import CliRunner

from pynakes import dedupe
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.model import resolve_field_value


def test_indexed_duplicates_match_exhaustive_pairs(monkeypatch):
    # Include missing/conflicting identifiers, short titles, authors, years,
    # duplicate keys, and links through multiple identifiers.
    entries = []
    for i, (doi, arxiv, year, author, title) in enumerate(
        product(
            ("", "10.5555/alpha", "10.5555/beta"),
            ("", "1901.00001"),
            ("", "1900", "1901"),
            ("Ashby, Ada", "Brandt, Bruno"),
            ("Short", "A theory of invented lattice waves", "A theory of invented lattice wave"),
        )
    ):
        fields = {
            "doi": doi,
            "eprint": arxiv,
            "eprinttype": "arxiv",
            "year": year,
            "author": author,
            "title": title,
        }
        entries.append(
            "@article{K%d,%s}"
            % (i % 19, ",".join(f"{name}={{{value}}}" for name, value in fields.items() if value))
        )
    lib = parse_bib("\n".join(entries))
    indexed = [cluster.to_dict() for cluster in dedupe.find_duplicate_clusters(lib)]
    monkeypatch.setattr(
        dedupe,
        "_candidate_indices",
        lambda items: (list(range(i + 1, len(items))) for i in range(len(items))),
    )
    exhaustive = [cluster.to_dict() for cluster in dedupe.find_duplicate_clusters(lib)]
    assert indexed == exhaustive


def test_distinct_identifiers_skip_comparisons(monkeypatch):
    lib = parse_bib(
        "\n".join(
            "@article{K%d,doi={10.5555/example.%d},year={1900},author={Ashby, Ada},"
            "title={A theory of invented lattice waves}}" % (i, i)
            for i in range(200)
        )
    )

    def unexpected(*args):
        raise AssertionError("incompatible identifiers cannot match")

    monkeypatch.setattr(dedupe, "compare_work_evidence", unexpected)
    assert dedupe.find_duplicate_clusters(lib) == []


def test_shared_resolver_preserves_independent_expansions():
    text = """@string{a = b # " a"}
@string{b = a # " b"}
@string{journal = "Invented Journal"}
@article{K, title={Literal # and escaped \\% text}, journal=journal, note=a}
@article{L, note=b, month=jan, title="Quoted title"}
% A trailing comment
"""
    lib = parse_bib(text)
    for entry in lib.entries.values():
        assert entry.fields == {
            key: resolve_field_value(value, lib.strings)
            for key, value in entry.field_expressions.items()
        }
    assert write_bib(lib) == text


def test_insights_match_individual_reads_and_open_once(tmp_path, monkeypatch):
    path = tmp_path / "library.bib"
    path.write_text("@book{Newton1687,title={Principia},year={1687},groups={Classics}}")
    runner = CliRunner()
    expected = {}
    for name, command in (
        ("groups_tree", ["groups", "tree"]),
        ("groups_list", ["groups", "list"]),
        ("lint", ["lint"]),
    ):
        result = runner.invoke(app, [*command, str(path), "--json"])
        assert result.exit_code == 0, result.output
        expected[name] = json.loads(result.output)
    opened = []
    original = Bibliography.open

    def counted(file):
        opened.append(file)
        return original(file)

    monkeypatch.setattr(Bibliography, "open", counted)
    result = runner.invoke(app, ["inspect", str(path), "--display", "--insights", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["insights"] == expected
    assert opened == [str(path)]


def test_insights_failure_keeps_inspection(tmp_path, monkeypatch):
    from pynakes.cli_commands import _inspect_insights

    path = tmp_path / "library.bib"
    path.write_text("@book{Newton1687,title={Principia}}")

    def fail(*args):
        raise ValueError("Invalid supplementary data")

    monkeypatch.setattr(_inspect_insights, "_lint_collection", fail)
    result = CliRunner().invoke(app, ["inspect", str(path), "--insights", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["entries"][0]["key"] == "Newton1687"
    assert data["insights"]["lint"]["error"] == "InvalidInput"
    assert data["insights"]["groups_tree"]["status"] == "success"
