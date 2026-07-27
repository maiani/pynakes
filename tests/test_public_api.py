"""Contract tests for the curated package-level Python API."""

from pathlib import Path

import pynakes
from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.canonical import CanonicalLayout, FormatLintError
from pynakes.engine import (
    Bibliography,
    CommitResult,
    ExternalModificationError,
    FileFingerprint,
)
from pynakes.io import SaveResult, load_bib, save_bib
from pynakes.model import BibEntry, BibFile, EntryStore, QueryFilter


def test_top_level_api_exports_curated_symbols() -> None:
    expected = {
        "BibEntry": BibEntry,
        "BibFile": BibFile,
        "Bibliography": Bibliography,
        "CanonicalLayout": CanonicalLayout,
        "CommitResult": CommitResult,
        "EntryStore": EntryStore,
        "ExternalModificationError": ExternalModificationError,
        "FileFingerprint": FileFingerprint,
        "FormatLintError": FormatLintError,
        "ParseError": ParseError,
        "QueryFilter": QueryFilter,
        "SaveResult": SaveResult,
        "load_bib": load_bib,
        "parse_bib": parse_bib,
        "save_bib": save_bib,
        "write_bib": write_bib,
    }

    assert set(pynakes.__all__) == {*expected, "__version__"}
    for name, value in expected.items():
        assert getattr(pynakes, name) is value


def test_top_level_api_supports_transactional_workflow(tmp_path: Path) -> None:
    path = tmp_path / "refs.bib"
    path.write_text("@misc{Example,\n  title = {Example},\n}\n")

    bibliography = pynakes.Bibliography.open(path)
    assert bibliography.lint() == []
    assert bibliography.set_field("year", "2020", "key = Example") == 1
    assert bibliography.change_plan()["summary"]["modified"] == 1
    assert bibliography.is_dirty

    result = bibliography.commit()

    assert isinstance(result, pynakes.CommitResult)
    assert result.modified
    assert "year = {2020}" in path.read_text()


def test_top_level_api_supports_in_memory_round_trip() -> None:
    library = pynakes.parse_bib("@misc{Example, title={Example}}\n")

    assert isinstance(library, pynakes.BibFile)
    assert pynakes.write_bib(library) == "@misc{Example, title={Example}}\n"
