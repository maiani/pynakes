"""Hints `ref import` gives about what to do next with an imported entry."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes import importer as importer_ops
from pynakes.cli import app

runner = CliRunner()

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/{arxiv_id}v1</id>
    <published>1905-06-30T10:00:00Z</published>
    <updated>1905-06-30T10:00:00Z</updated>
    <title>{title}</title>
    <summary>An invented abstract.</summary>
    <author><name>Albert Einstein</name></author>
    <arxiv:primary_category term="physics.gen-ph"/>
    {doi}
  </entry>
</feed>
"""


def _atom(arxiv_id: str, title: str, doi: str | None) -> str:
    doi_element = f"<arxiv:doi>{doi}</arxiv:doi>" if doi else ""
    return ATOM.format(arxiv_id=arxiv_id, title=title, doi=doi_element)


@pytest.fixture
def bib(tmp_path: Path, monkeypatch) -> Path:
    records = {
        "2301.00001": _atom("2301.00001", "On the Electrodynamics of Moving Bodies", "10.5555/ann"),
        "2301.00002": _atom("2301.00002", "On a Heuristic Point of View", "10.5555/heur"),
        "2301.00003": _atom("2301.00003", "An Unpublished Note", None),
    }
    monkeypatch.setattr(importer_ops, "fetch_arxiv_atom", lambda identifier: records[identifier])
    path = tmp_path / "refs.bib"
    path.write_text("", encoding="utf-8")
    return path


def test_a_preprint_naming_a_published_doi_gets_the_promote_command(bib: Path) -> None:
    result = runner.invoke(
        app, ["ref", "import", str(bib), "arXiv:2301.00001=Einstein1905Electrodynamics", "--json"]
    )

    assert result.exit_code == 0, result.output
    warning = json.loads(result.output)["warnings"][0]
    assert warning["type"] == "published_version_available"
    assert warning["keys"] == ["Einstein1905Electrodynamics"]
    assert (
        f"pynakes enrich {bib} --published --online --key Einstein1905Electrodynamics"
        in warning["message"]
    )


def test_a_batch_gets_one_hint_for_every_such_preprint(bib: Path) -> None:
    result = runner.invoke(
        app,
        [
            "ref",
            "import",
            str(bib),
            "arXiv:2301.00001=Einstein1905a",
            "arXiv:2301.00002=Einstein1905b",
            "arXiv:2301.00003=Einstein1905c",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    hints = [
        w
        for w in json.loads(result.output)["warnings"]
        if w["type"] == "published_version_available"
    ]
    assert len(hints) == 1
    assert hints[0]["keys"] == ["Einstein1905a", "Einstein1905b"]
    assert "--key Einstein1905a,Einstein1905b" in hints[0]["message"]


def test_a_preprint_without_a_published_doi_gets_no_hint(bib: Path) -> None:
    result = runner.invoke(app, ["ref", "import", str(bib), "arXiv:2301.00003", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["warnings"] == []
