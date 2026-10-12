"""What an ``asset fetch`` dry run plans: each artifact, its store path, its identifier.

A dry run makes no network request, so the plan is the only thing a consumer
(an approval dialog, a script deciding whether to proceed) can show before the
downloads happen. These tests pin that every planned artifact names the path the
store would write, so no consumer has to rebuild the Pinax addressing scheme.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes.cli import app
from pynakes.engine import Bibliography
from pynakes.fetch import ArxivFetchError
from pynakes.metadata import FetchPolicy

runner = CliRunner()

LIBRARY = """@article{Einstein1905,
  title = {Zur Elektrodynamik bewegter K{\\"o}rper},
  doi = {10.1002/andp.19053221004},
  eprint = {1234.5678},
  archiveprefix = {arXiv},
}

@misc{Turing1936,
  title = {On Computable Numbers},
  eprint = {2345.6789},
  archiveprefix = {arXiv},
}

@book{Newton1687,
  title = {Principia},
}

@comment{pynakes-meta:
pinax-files-dir: refs.files
}
"""


def _no_network(*_args: object, **_kwargs: object) -> bytes:
    raise AssertionError("a dry run must not reach the network")


@pytest.fixture
def library(tmp_path: Path) -> Path:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    return bib


def _plan(bib: Path, policy: FetchPolicy | None = None) -> dict:
    coll = Bibliography.open(bib)
    return coll.fetch_materials(
        policy=policy,
        dry_run=True,
        pdf_fetcher=_no_network,
        source_fetcher=_no_network,
        published_url_fetcher=_no_network,
        institutional_url_fetcher=_no_network,
        published_pdf_fetcher=_no_network,
        supplement_url_fetcher=_no_network,
        supplement_pdf_fetcher=_no_network,
    )


def test_best_pdf_plans_published_with_a_preprint_fallback(library: Path) -> None:
    files = library.parent / "refs.files"

    report = _plan(library)

    planned = {item["key"]: item.get("planned") for item in report["skipped"]}
    assert planned["Einstein1905"] == [
        {
            "artifact": "published_pdf",
            "path": str(files / "Einstein1905.published.pdf"),
            "doi": "10.1002/andp.19053221004",
            "fallback": False,
        },
        {
            "artifact": "preprint_pdf",
            "path": str(files / "Einstein1905.preprint.pdf"),
            "arxiv_id": "1234.5678",
            "fallback": True,
        },
    ]
    assert planned["Turing1936"] == [
        {
            "artifact": "preprint_pdf",
            "path": str(files / "Turing1936.preprint.pdf"),
            "arxiv_id": "2345.6789",
            "fallback": False,
        }
    ]
    # An entry with nothing to fetch keeps its reason and carries no plan.
    assert planned["Newton1687"] is None
    assert report["fetched"] == []
    assert report["failed"] == []


def test_explicit_materials_plan_each_artifact(library: Path) -> None:
    policy = FetchPolicy(
        preprint=False, published=False, source=True, supplement=True, bestpdf=False
    )

    report = _plan(library, policy)

    einstein = next(item for item in report["skipped"] if item["key"] == "Einstein1905")
    assert [item["artifact"] for item in einstein["planned"]] == [
        "preprint_source",
        "supplement_pdf",
    ]
    assert einstein["planned"][0]["path"].endswith("Einstein1905.source")


def test_a_present_material_is_not_planned_again(library: Path) -> None:
    files = library.parent / "refs.files"
    files.mkdir()
    (files / "Turing1936.preprint.pdf").write_bytes(b"%PDF-1.4\n")

    report = _plan(library)

    turing = next(item for item in report["skipped"] if item["key"] == "Turing1936")
    assert turing["reason"] == "materials already present (no DOI for a published version)"
    assert "planned" not in turing


def test_dry_run_creates_no_files_directory(library: Path) -> None:
    result = runner.invoke(
        app, ["asset", "fetch", str(library), "Turing1936", "--dry-run", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert [item["artifact"] for item in data["skipped"][0]["planned"]] == ["preprint_pdf"]
    assert not (library.parent / "refs.files").exists()


def test_dry_run_of_an_unconfigured_library_writes_nothing(tmp_path: Path) -> None:
    bib = tmp_path / "plain.bib"
    bib.write_text(LIBRARY.split("@comment")[0], encoding="utf-8")
    before = bib.read_bytes()

    result = runner.invoke(app, ["asset", "fetch", str(bib), "--dry-run", "--diff", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    # The plan names the default directory the real run would record and fill.
    assert data["files_dir"] == str(tmp_path / "plain.files")
    assert "pinax-files-dir: plain.files" in data["diff"]
    assert bib.read_bytes() == before
    assert not (tmp_path / "plain.files").exists()


NOTHING_TO_FETCH = "@book{Newton1687,\n  title = {Principia},\n}\n"


@pytest.mark.parametrize("dry_run", [True, False])
def test_a_fetch_with_nothing_to_fetch_leaves_an_unconfigured_library_alone(
    tmp_path: Path, dry_run: bool
) -> None:
    bib = tmp_path / "plain.bib"
    bib.write_text(NOTHING_TO_FETCH, encoding="utf-8")
    before = bib.read_bytes()
    flags = ["--dry-run"] if dry_run else []

    result = runner.invoke(app, ["asset", "fetch", str(bib), *flags, "--diff", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["modified"] is False
    assert data["files_dir"] is None
    assert "pinax-files-dir" not in (data.get("diff") or "")
    assert bib.read_bytes() == before
    assert not (tmp_path / "plain.files").exists()


def test_a_fetch_that_lands_a_material_records_the_store(tmp_path: Path) -> None:
    bib = tmp_path / "plain.bib"
    bib.write_text(LIBRARY.split("@comment")[0], encoding="utf-8")
    coll = Bibliography.open(bib)

    report = coll.fetch_materials(
        "Turing1936",
        policy=FetchPolicy(preprint=True),
        pdf_fetcher=lambda _arxiv_id: b"%PDF-1.4\n%%EOF\n",
    )

    assert [item["key"] for item in report["fetched"]] == ["Turing1936"]
    assert coll.files is not None
    assert coll.files.root == tmp_path / "plain.files"


def test_a_fetch_that_fails_everywhere_leaves_no_store_behind(tmp_path: Path) -> None:
    bib = tmp_path / "plain.bib"
    bib.write_text(LIBRARY.split("@comment")[0], encoding="utf-8")
    coll = Bibliography.open(bib)

    def unavailable(_arxiv_id: str) -> bytes:
        raise ArxivFetchError("offline")

    report = coll.fetch_materials(
        "Turing1936", policy=FetchPolicy(preprint=True), pdf_fetcher=unavailable
    )

    assert report["fetched"] == []
    assert coll.files is None
    assert not (tmp_path / "plain.files").exists()
