"""Interpretation and curation workflows for co-authorship reports."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from typer.testing import CliRunner

from pynakes.analysis import analyze, coauthor_network
from pynakes.cli import app
from pynakes.engine import Bibliography

runner = CliRunner()


def network(text: str, **kwargs):
    return coauthor_network(Bibliography.from_text(text).lib.entries.values(), **kwargs)


def test_focus_distinguishes_selection_and_visible_graph() -> None:
    report = network(
        """@article{AB, author={Alpha, Ann and Beta, Bob}}
@article{BC, author={Beta, Bob and Gamma, Gail}}
@article{D, author={Delta, Dan}}""",
        focus=["Alpha, Ann"],
    )
    doc = report.to_dict()
    assert doc["entries"]["total"] == 3
    assert doc["summary"]["authors"] == 2
    beta = next(a for a in doc["authors"] if a["name"] == "Beta, Bob")
    assert beta["collaborators"] == 2
    assert beta["visible_collaborators"] == 1
    assert doc["scope"]["components_and_isolates"] == "excluding_focus"
    assert doc["scope"]["author_counts_and_years"] == "selection"
    assert "Isolated authors (excluding focus)" in report.to_markdown()
    root = ET.fromstring(report.to_graphml())
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    nodes = root.findall("g:graph/g:node", ns)
    beta_node = next(n for n in nodes if n.find("g:data[@key='label']", ns).text == "Beta, Bob")
    assert beta_node.find("g:data[@key='visible_collaborators']", ns).text == "1"


def test_conflicting_identity_warns_with_duplicate_key_evidence() -> None:
    text = """@article{Same, author={Smith, John and Alpha, Ann},
 author+an:orcid={1="0000-0002-1825-0097"}}
@article{Same, author={Smith, John and Beta, Bob},
 author+an:orcid={1="0000-0001-5109-3700"}}"""
    report = network(text)
    (warning,) = report.warnings
    assert warning["type"] == "conflicting_author_orcids"
    assert warning["name"] == "Smith, John"
    assert [e["selection_index"] for e in warning["evidence"]] == [0, 1]
    assert [e["key"] for e in warning["evidence"]] == ["Same", "Same"]
    assert len(report.authors) == 3  # report ambiguity; do not invent an identity split
    assert report.to_dict()["warnings"] == report.warnings
    assert analyze(Bibliography.from_text(text), sections=["coauthors"]).warnings == report.warnings
    assert not network(text.replace("0000-0001-5109-3700", "0000-0002-1825-0097")).warnings


def test_saved_documents_keep_warnings_and_provenance(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("""@article{Big, author={Alpha, Ann and Beta, Bob and Gamma, Gail}}
@article{Small, author={Alpha, A. and Delta, Dan}}""")
    for fmt in ("json", "markdown", "graphml"):
        out = tmp_path / f"report.{fmt}"
        result = runner.invoke(
            app,
            [
                "coauthors",
                str(bib),
                "--focus",
                "Alpha, Ann",
                "--max-authors",
                "2",
                "--to",
                fmt,
                "--out",
                str(out),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        text = out.read_text()
        assert envelope["source_sha256"] in text
        assert "large_author_lists" in text and "focus_variants" in text
        if fmt == "graphml":
            root = ET.fromstring(text)
            context = root.find("{*}graph/{*}data[@key='context']")
            doc = json.loads(context.text)
        elif fmt == "json":
            doc = json.loads(text)
        else:
            assert "Excluded entry keys: Big" in text
            assert "Alpha, A.: Small" in text
            continue
        assert doc["unlinked_keys"] == ["Big"]
        assert doc["max_authors"] == 2
        assert doc["scope"]["components_and_isolates"] == "excluding_focus"
        assert doc["warnings"] == envelope["warnings"]
        assert doc["source"]["file"] == str(bib)


def test_review_preview_correct_and_rerun(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    original = """@article{Example1900,
  author = {Example, A. and Colleague, Beatrice},
  title = {An invented example},
  year = {1900}
}
@article{Example1901,
  author = {Example, Alice and Colleague, Beatrice},
  year = {1901}
}
"""
    bib.write_text(original)
    report = network(original)
    assert len(report.variants) == 1
    result = runner.invoke(
        app, ["ref", "show", str(bib), "Example1900", "--select", "author,title,year", "--json"]
    )
    assert result.exit_code == 0, result.output
    command = [
        "fields",
        "set",
        str(bib),
        "author",
        "Example, Alice and Colleague, Beatrice",
        "--key",
        "Example1900",
    ]
    preview = runner.invoke(app, [*command, "--dry-run", "--diff"])
    assert preview.exit_code == 0, preview.output
    assert bib.read_text() == original
    applied = runner.invoke(app, command)
    assert applied.exit_code == 0, applied.output
    assert bib.read_text() == original.replace("Example, A.", "Example, Alice")
    assert not network(bib.read_text()).variants
    assert network(bib.read_text()).pairs[0]["entries"] == 2
