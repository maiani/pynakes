"""Versioned BibTeX/BibLaTeX parser conformance corpus."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib

CORPUS_ROOT = Path(__file__).parent / "fixtures" / "conformance"
MANIFEST = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))


def _entry_records(text: str) -> list[tuple[str, str, dict[str, str]]]:
    lib = parse_bib(text)
    return [(entry.key, entry.type, entry.fields) for entry in lib.entries.values()]


def test_corpus_is_pinned_to_texlive_2026() -> None:
    assert MANIFEST["baseline"] == {
        "texlive": "2026",
        "bibtex": "0.99d",
        "biblatex": "3.21",
        "biblatex_date": "2025-05-01",
        "biber": "2.21",
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
    lib = parse_bib((CORPUS_ROOT / "biblatex-3.21-core.bib").read_text(encoding="utf-8"))

    # Arbitrary entry types (online, set) and custom data-model fields.
    assert lib.entries["UnicodeDataset"].type == "online"
    assert lib.entries["UnicodeDataset"].fields["custom:field"] == "A project-defined value"
    assert lib.entries["DatasetSet"].type == "set"
    assert lib.entries["InheritedArticle"].fields["xref"] == "UnicodeDataset"

    # @xdata entry: structural data container, arbitrary fields, no required ones.
    assert lib.entries["SharedMetadata"].type == "xdata"
    assert lib.entries["SharedMetadata"].fields["publisher"] == "Example Press"
    assert lib.entries["SharedMetadata"].fields["location"] == "Stockholm"

    # Unicode: non-ASCII author name and multi-script title survive round-trip.
    assert "Ångström" in lib.entries["UnicodeDataset"].fields["author"]
    assert "数据" in lib.entries["UnicodeDataset"].fields["title"]

    # Inheritance: resolved fields include xdata-injected values without mutation.
    resolved = lib.resolved_fields("UnicodeDataset")
    assert resolved["publisher"] == "Example Press"
    assert lib.entries["UnicodeDataset"].fields.get("publisher") is None


def _run_bibtex_on(bib_path: Path, tmp: Path) -> subprocess.CompletedProcess[str]:
    """Invoke bibtex 0.99d against a .bib file via a synthetic .aux file."""
    stem = bib_path.stem
    aux = tmp / f"{stem}.aux"
    aux.write_text(
        f"\\relax\n\\citation{{*}}\n\\bibstyle{{plain}}\n\\bibdata{{{stem}}}\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bibtex", stem],
        cwd=tmp,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "fixture",
    [f for f in MANIFEST["fixtures"] if f.get("kind") == "bibtex"],
    ids=lambda item: item["path"],
)
@pytest.mark.skipif(shutil.which("bibtex") is None, reason="bibtex oracle not installed")
def test_pynakes_output_accepted_by_bibtex(fixture: dict[str, object], tmp_path: Path) -> None:
    """pynakes parse → write output must be accepted by BibTeX 0.99d.

    This is the differential guarantee: the reference tool must not report
    errors on pynakes-written output. Unmodified entries use raw_content
    verbatim, so this also validates that unmodified entries survive intact.
    """
    source = (CORPUS_ROOT / str(fixture["path"])).read_text(encoding="utf-8")
    lib = parse_bib(source)
    out_bib = tmp_path / (Path(fixture["path"]).stem + ".bib")
    out_bib.write_text(write_bib(lib), encoding="utf-8")

    result = _run_bibtex_on(out_bib, tmp_path)
    errors = [ln for ln in result.stdout.splitlines() if ln.startswith("I couldn't")]
    assert not errors, f"bibtex reported errors on pynakes output:\n{result.stdout}"


@pytest.mark.parametrize(
    "fixture",
    [f for f in MANIFEST["fixtures"] if f.get("kind") == "biblatex"],
    ids=lambda item: item["path"],
)
@pytest.mark.skipif(shutil.which("biber") is None, reason="biber oracle not installed")
def test_pynakes_output_accepted_by_biber(fixture: dict[str, object], tmp_path: Path) -> None:
    """pynakes parse → write output must be accepted by Biber (--tool mode).

    Biber exits non-zero when the file contains fatal syntax errors.
    """
    source = (CORPUS_ROOT / str(fixture["path"])).read_text(encoding="utf-8")
    lib = parse_bib(source)
    out_bib = tmp_path / "out.bib"
    out_bib.write_text(write_bib(lib), encoding="utf-8")

    result = subprocess.run(
        ["biber", "--tool", "--quiet", "--nolog", str(out_bib)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"biber --tool rejected pynakes output (exit {result.returncode}):\n"
        f"{result.stderr or result.stdout}"
    )
