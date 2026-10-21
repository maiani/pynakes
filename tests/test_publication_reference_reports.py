"""Publication references and report scopes, using invented offline records."""

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from pynakes import _integrity_published as published
from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.cli import app


@pytest.mark.parametrize("label", ["", "pages ", "page ", "pp. ", "p. "])
def test_publication_reference_promotes_structured_fields(monkeypatch, label):
    monkeypatch.setattr(
        published,
        "_fetch_arxiv_record",
        lambda *a, **kw: SimpleNamespace(
            doi="10.5555/example", journal=f"Journal of Examples 12, {label}31–47 (1902)"
        ),
    )
    source = "@misc{Example, eprint={1901.00001}, archivePrefix={arXiv}, year={1901}}\n"
    lib = parse_bib(source)
    report = published.check_published(lib, online=True, apply=False)
    assert report.newly_found == 1
    assert write_bib(lib) == source
    published.check_published(lib, online=True, apply=True)
    entry = lib.entries["Example"]
    assert entry.type == "article"
    assert entry.fields["journal"] == "Journal of Examples"
    assert entry.fields["volume"] == "12"
    assert entry.fields["pages"] == "31--47"
    assert entry.fields["year"] == "1902"
    assert entry.fields["eprint"] == "1901.00001"


def test_unparsed_reference_is_evidence_not_a_journal(monkeypatch):
    reference = "Journal of Examples, accepted 1902, special issue forthcoming"
    monkeypatch.setattr(
        published,
        "_fetch_arxiv_record",
        lambda *a, **kw: SimpleNamespace(doi="", journal=reference),
    )
    source = "@misc{Example, eprint={1901.00001}, archivePrefix={arXiv}, year={1901}}\n"
    lib = parse_bib(source)
    report = published.check_published(lib, online=True, apply=True)
    assert write_bib(lib) == source
    assert report.candidates[0].status == "unparsed_reference"
    assert report.warnings[0]["journal_reference"] == reference
    assert report.candidates[0].metadata["journal_reference"] == reference


def test_verify_publication_counts_match_human_and_json(monkeypatch, tmp_path):
    monkeypatch.setattr(
        published,
        "_fetch_arxiv_record",
        lambda *a, **kw: SimpleNamespace(
            doi="10.5555/new", journal="Journal of Examples 12, 31 (1902)"
        ),
    )
    # Keep DOI verification offline in the stub; this test exercises only the
    # distinction between the two reports and newly found versus existing data.
    from pynakes import integrity

    monkeypatch.setattr(
        integrity,
        "fetch_doi_entry",
        lambda *a, **kw: parse_bib(
            "@article{Remote, doi={10.5555/existing}, journal={Journal of Examples}}"
        ).entries["Remote"],
    )
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@misc{New, eprint={1901.00001}, archivePrefix={arXiv}}\n"
        "@article{Existing, eprint={1901.00002}, archivePrefix={arXiv}, doi={10.5555/existing}, journal={Journal of Examples}}\n"
    )
    runner = CliRunner()
    args = ["verify", str(bib), "--published", "--online"]
    output = runner.invoke(app, [*args, "--json"])
    assert output.exit_code == 0, output.output
    result = json.loads(output.output)
    assert result["summary"]["checked"] == 1
    summary = result["preprints"]
    assert summary["checked"] == 2
    assert summary["published"] == 2  # Stable legacy total.
    assert summary["newly_found"] == summary["already_present"] == 1
    assert sum(summary["by_status"].values()) == summary["checked"]
    human = runner.invoke(app, args)
    assert human.exit_code == 0, human.output
    assert "2 candidate results; 1 newly found, 1 already recorded" in human.output
