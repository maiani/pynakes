"""Finding and repairing preprints stored as the published PDF (``asset check``/``repair``)."""

import json
import zlib
from pathlib import Path

from typer.testing import CliRunner

from pynakes._material_classes import arxiv_stamp
from pynakes.cli import app
from pynakes.engine import Bibliography

runner = CliRunner()

LIBRARY = """@article{Smith2021,
  title = {A Study of Invented Things},
  doi = {10.5555/invented.1},
}

@misc{Example2020,
  title = {An Invented Preprint},
  doi = {10.48550/arXiv.2001.00001},
}

@article{Jones2019,
  title = {A Publisher Copy},
  doi = {10.5555/invented.2},
}

@comment{pynakes-meta:
pinax-files-dir: refs.files
}
"""

STAMP = b"(arXiv:2001.00002v1  [quant-ph]  1 Jan 2020)Tj"


def _pdf(content: bytes) -> bytes:
    stream = zlib.compress(b"BT /F1 9 Tf " + content + b" ET")
    return (
        b"%PDF-1.5\n1 0 obj\n<< /Length "
        + str(len(stream)).encode()
        + b" /Filter /FlateDecode >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n%%EOF\n"
    )


def _library(tmp_path: Path) -> tuple[Path, Bibliography]:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    coll = Bibliography.open(bib)
    store = coll.files
    assert store is not None
    # Smith2021: recorded as downloaded from arXiv.
    store.write_published_pdf("Smith2021", _pdf(b"(A Study)Tj"))
    store.record_artifact(
        "Smith2021",
        "published_pdf",
        source="https://arxiv.org/pdf/2001.00003",
        refetchable=True,
        fetched_date="2020-01-01",
    )
    # Example2020: arXiv's own DOI, and the stamp in a compressed stream.
    store.write_published_pdf("Example2020", _pdf(STAMP))
    store.write_preprint_pdf("Example2020", _pdf(b"(the preprint)Tj"))
    # Jones2019: a publisher copy citing an arXiv id in its text is not a preprint.
    store.write_published_pdf("Jones2019", _pdf(b"(see arXiv:2001.00004 for details)Tj"))
    store.record_artifact(
        "Jones2019",
        "published_pdf",
        source="https://publisher.example/a.pdf",
        refetchable=True,
        fetched_date="2020-01-01",
    )
    return bib, coll


def test_the_arxiv_stamp_is_read_from_a_compressed_stream() -> None:
    assert arxiv_stamp(_pdf(STAMP)) == "arXiv:2001.00002v1"
    assert arxiv_stamp(_pdf(b"(cites arXiv:2001.00002v1 in passing)Tj")) is None


def test_asset_check_reports_misclassified_pdfs_with_their_evidence(tmp_path: Path) -> None:
    bib, _ = _library(tmp_path)

    result = runner.invoke(app, ["asset", "check", str(bib), "--json"])

    data = json.loads(result.output)
    found = {item["key"]: item for item in data["misclassified"]}
    assert set(found) == {"Smith2021", "Example2020"}
    assert [e["type"] for e in found["Smith2021"]["evidence"]] == ["source_host"]
    assert [e["type"] for e in found["Example2020"]["evidence"]] == [
        "arxiv_doi",
        "pdf_arxiv_stamp",
    ]
    assert found["Smith2021"]["action"] == "move"
    assert found["Example2020"]["action"] == "conflict"


def test_asset_check_separates_linked_files_from_material_coverage(tmp_path: Path) -> None:
    bib, _ = _library(tmp_path)

    data = json.loads(runner.invoke(app, ["asset", "check", str(bib), "--json"]).output)

    assert data["coverage"]["linked_files"]["checked"] == 0
    materials = data["coverage"]["materials"]
    assert materials["entries"] == 3
    assert materials["with_pdf"] == 3
    assert materials["without_pdf"] == []
    assert materials["misclassified"] == 2


def test_repair_reclassify_moves_the_file_and_its_record(tmp_path: Path) -> None:
    bib, coll = _library(tmp_path)
    store = coll.files
    assert store is not None
    before = store.paths_for("Smith2021").published_pdf.read_bytes()

    preview = runner.invoke(
        app, ["asset", "repair", str(bib), "--reclassify", "--dry-run", "--json"]
    )
    assert {item["key"]: item["action"] for item in json.loads(preview.output)["reclassified"]} == {
        "Smith2021": "would_move",
        "Example2020": "conflict",
    }
    assert store.presence_for("Smith2021").published_pdf

    result = runner.invoke(app, ["asset", "repair", str(bib), "--reclassify", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["modified"] is True
    actions = {item["key"]: item["action"] for item in data["reclassified"]}
    assert actions == {"Smith2021": "moved", "Example2020": "conflict"}
    presence = store.presence_for("Smith2021")
    assert presence.preprint_pdf and not presence.published_pdf
    assert store.paths_for("Smith2021").preprint_pdf.read_bytes() == before
    record = store.read_manifest()["files"]["Smith2021"]["preprint_pdf"]  # type: ignore[index]
    assert record["source"] == "https://arxiv.org/pdf/2001.00003"
    assert record["reclassified_from"] == "published_pdf"
    assert record["reclassification_evidence"][0]["type"] == "source_host"
    # The conflicting file and the genuine publisher copy are untouched.
    assert store.presence_for("Example2020").published_pdf
    assert store.presence_for("Jones2019").published_pdf
    assert bib.read_text(encoding="utf-8") == LIBRARY
