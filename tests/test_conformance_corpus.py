"""Versioned BibTeX/BibLaTeX parser conformance corpus."""

import hashlib
import json
from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib

CORPUS_ROOT = Path(__file__).parent / "fixtures" / "conformance"
MANIFEST = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _entry_records(text: str) -> list[tuple[str, str, dict[str, str]]]:
    lib = parse_bib(text)
    return [(entry.key, entry.type, entry.fields) for entry in lib.entries.values()]


def test_corpus_is_pinned_to_texlive_2025() -> None:
    assert MANIFEST["baseline"] == {
        "texlive": "2025",
        "bibtex": "0.99d",
        "biblatex": "3.20",
        "biblatex_date": "2024-03-21",
        "biber": "2.20",
    }


@pytest.mark.parametrize("fixture", MANIFEST["fixtures"], ids=lambda item: item["path"])
def test_conformance_fixture_semantic_round_trip(fixture: dict[str, object]) -> None:
    path = CORPUS_ROOT / str(fixture["path"])
    source = path.read_text(encoding="utf-8")

    parsed = parse_bib(source)
    rewritten = write_bib(parsed)

    assert _entry_records(rewritten) == _entry_records(source)


@pytest.mark.parametrize(
    "fixture",
    [item for item in MANIFEST["fixtures"] if "sha256" in item],
    ids=lambda item: item["path"],
)
def test_upstream_fixture_checksum_is_pinned(fixture: dict[str, object]) -> None:
    contents = (CORPUS_ROOT / str(fixture["path"])).read_bytes()

    assert hashlib.sha256(contents).hexdigest() == fixture["sha256"]


def test_bibtex_core_fixture_exercises_standard_macros_and_concatenation() -> None:
    lib = parse_bib((CORPUS_ROOT / "bibtex-0.99d-core.bib").read_text(encoding="utf-8"))

    assert lib.entries["ParenEntry"].fields["journal"] == "Journal of OpenAI"
    assert lib.entries["ParenEntry"].fields["month"] == "January"
    assert (
        lib.entries["ParenEntry"].fields["abstract"]
        == r"A \"quoted\" string with a \# literal hash"
    )
    assert lib.entries["ParenEntry"].fields["howpublished"] == "First second tail"
    assert lib.entries["BracedEntry"].fields["edition"] == "1st"
    assert lib.strings["ESCAPED"] == r"Escaped \"quote\" and \% percent"
    assert any(raw.startswith("@string{") for raw in lib.raw_strings)
    assert any(raw.startswith("@string(") for raw in lib.raw_strings)
    assert len(lib.preamble) == 2
    assert any(raw.startswith("@preamble{") for raw in lib.preamble)
    assert any(raw.startswith("@preamble(") for raw in lib.preamble)
    assert any(comment.startswith("@comment{") for comment in lib.raw_comments)


def test_biblatex_core_fixture_preserves_extensible_data_model_input() -> None:
    lib = parse_bib((CORPUS_ROOT / "biblatex-3.20-core.bib").read_text(encoding="utf-8"))

    assert lib.entries["UnicodeDataset"].fields["custom:field"] == "A project-defined value"
    assert lib.entries["DatasetSet"].type == "set"
    assert lib.entries["InheritedArticle"].fields["xref"] == "UnicodeDataset"
