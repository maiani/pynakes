"""An imported entry follows the style its library declares, and nothing else changes."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes._library_style import declared_steps
from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app

runner = CliRunner()

PROVIDER_BIBTEX = (
    "@article{Planck1900,\n"
    "  author = {Max Planck},\n"
    "  title = {Zur Theorie des Gesetzes der Energieverteilung im Normalspectrum},\n"
    "  journal = {Annalen der Physik},\n"
    "  year = {1900},\n"
    "  doi = {10.5555/normalspectrum}\n"
    "}\n"
)

EXISTING = (
    "@article{Einstein1905,\n"
    "  author  = {Einstein, Albert},\n"
    '  title   = {Zur Elektrodynamik bewegter K{\\"o}rper},\n'
    "  journal = {Ann. Phys.},\n"
    "  year    = {1905},\n"
    "}\n"
)


@pytest.fixture(autouse=True)
def _provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pynakes.importer.fetch_bibtex_for_doi", lambda doi: PROVIDER_BIBTEX)
    monkeypatch.setattr("pynakes.importer.fetch_crossref_work", lambda doi: {})


def _import(tmp_path: Path, metadata: str) -> tuple[str, str]:
    bib = tmp_path / "refs.bib"
    original = metadata + "\n" + EXISTING
    bib.write_text(original)
    result = runner.invoke(app, ["ref", "import", str(bib), "10.5555/normalspectrum"])
    assert result.exit_code == 0, result.output
    return original, bib.read_text()


def test_an_import_takes_the_declared_journal_style_and_layout(tmp_path: Path) -> None:
    original, written = _import(
        tmp_path,
        "@comment{pynakes-meta:\n"
        "normalize-journal-style: abbreviated\n"
        "normalize-author-style: biblatex\n"
        "format-alignment: equals\n"
        "}\n",
    )
    assert written.startswith(original.rstrip("\n"))
    added = written[len(original.rstrip("\n")) :]
    assert "  journal = {Ann. Phys.}," in added
    assert "  author  = {Planck, Max}," in added
    assert "  doi     = {10.5555/normalspectrum}," in added


def test_a_library_that_declares_nothing_gets_the_entry_as_provided(tmp_path: Path) -> None:
    _, written = _import(tmp_path, "")
    added = written[len(EXISTING) :]
    assert "journal = {Annalen der Physik}" in added
    assert "author = {Max Planck}" in added


def test_only_the_steps_a_library_configures_are_declared() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta:\nnormalize-journal-style: abbreviated\nformat-indent: 4\n}\n"
    )
    assert declared_steps(lib) == ["journals"]
    assert declared_steps(parse_bib("")) == []
