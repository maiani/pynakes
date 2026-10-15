"""Collecting PDFs for a bibliography: what each file is, what is still missing, and why.

Every provider is injected, so these tests make no network request.
"""

import json
from pathlib import Path

import pytest

from pynakes._fetch_discovery import discover_arxiv_id
from pynakes.cli_commands.fetch import _JsonLinesProgress
from pynakes.engine import Bibliography
from pynakes.fetch import PublishedPdfFetchError
from pynakes.fetch_progress import FetchProgressEvent
from pynakes.metadata import FetchPolicy
from pynakes.providers._http import RETRY_LISTENER, ProviderRateLimitedError
from pynakes.providers.repositories.arxiv import ArxivRecord

PDF = b"%PDF-1.4\n%%EOF\n"
BEST = FetchPolicy(bestpdf=True)

LIBRARY = """@article{Einstein1935,
  title = {Can Quantum-Mechanical Description of Physical Reality Be Considered Complete?},
  doi = {10.1103/physrev.47.777},
}

@misc{Example2020,
  title = {An Invented Preprint},
  doi = {10.48550/arXiv.2001.00001},
}

@article{Smith2021,
  title = {A Study of Invented Things},
  doi = {10.5555/invented.1},
}

@comment{pynakes-meta:
pinax-files-dir: refs.files
}
"""


@pytest.fixture
def library(tmp_path: Path) -> Path:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY, encoding="utf-8")
    return bib


def _no_lookup(_doi: str) -> str | None:
    return None


def _fetch(bib: Path, key: str, **kwargs: object) -> tuple[Bibliography, dict]:
    coll = Bibliography.open(bib)
    kwargs.setdefault("policy", BEST)
    kwargs.setdefault("published_url_fetcher", _no_lookup)
    report = coll.fetch_materials(key, **kwargs)  # type: ignore[arg-type]
    return coll, report


# --- PYN-01: a preprint is never stored as the published copy -----------------


def test_an_arxiv_doi_fetches_the_preprint_without_a_published_lookup(library: Path) -> None:
    def must_not_resolve(doi: str) -> str | None:
        raise AssertionError(f"arXiv's own DOI was looked up as published: {doi}")

    asked: list[str] = []
    coll, report = _fetch(
        library,
        "Example2020",
        published_url_fetcher=must_not_resolve,
        pdf_fetcher=lambda arxiv_id: asked.append(arxiv_id) or PDF,
    )

    assert asked == ["2001.00001"]
    assert [item["arxiv_id"] for item in report["fetched"]] == ["2001.00001"]
    presence = coll.files.presence_for("Example2020")  # type: ignore[union-attr]
    assert presence.preprint_pdf and not presence.published_pdf


def test_an_arxiv_doi_explains_why_no_published_pdf_is_fetched(library: Path) -> None:
    _, report = _fetch(library, "Example2020", policy=FetchPolicy(published=True))

    [skip] = report["skipped"]
    assert "no published DOI" in skip["reason"]
    assert "arXiv's own" in skip["reason"]


def test_a_pdf_served_by_arxiv_is_stored_as_the_preprint(library: Path) -> None:
    coll, report = _fetch(
        library,
        "Smith2021",
        policy=FetchPolicy(published=True),
        published_url_fetcher=lambda doi: "https://arxiv.org/pdf/2001.00002",
        published_pdf_fetcher=lambda url: PDF,
    )

    [item] = report["fetched"]
    assert item["artifact"] == "preprint_pdf"
    assert item["classified_by"] == "source_host"
    assert item["source"] == "https://arxiv.org/pdf/2001.00002"
    assert item["pdf_path"].endswith("Smith2021.preprint.pdf")
    store = coll.files
    assert store is not None
    assert not store.presence_for("Smith2021").published_pdf
    row = store.read_manifest()["files"]["Smith2021"]  # type: ignore[index]
    assert row["preprint_pdf"]["source"] == "https://arxiv.org/pdf/2001.00002"
    # The published version is still missing, and the report says so.
    [skip] = report["skipped"]
    assert skip["artifact"] == "published_pdf"
    assert report["coverage"]["missing"][0]["materials"] == ["published_pdf"]


def test_a_publisher_copy_is_tried_before_a_repository_copy(library: Path) -> None:
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        return PDF

    coll, report = _fetch(
        library,
        "Smith2021",
        access="institutional",
        published_url_fetcher=lambda doi: "https://arxiv.org/pdf/2001.00002",
        institutional_url_fetcher=lambda doi: "https://publisher.example/article.pdf",
        published_pdf_fetcher=fetch,
    )

    assert asked == ["https://publisher.example/article.pdf"]
    assert report["fetched"][0]["artifact"] == "published_pdf"
    assert coll.files.presence_for("Smith2021").published_pdf  # type: ignore[union-attr]


def test_a_repository_copy_does_not_replace_a_preprint_already_present(library: Path) -> None:
    coll = Bibliography.open(library)
    assert coll.files is not None
    coll.files.write_preprint_pdf("Smith2021", b"%PDF existing")

    _, report = _fetch(
        library,
        "Smith2021",
        policy=FetchPolicy(published=True),
        published_url_fetcher=lambda doi: "https://arxiv.org/pdf/2001.00002",
        published_pdf_fetcher=lambda url: PDF,
    )

    assert report["fetched"] == []
    assert "already present" in report["skipped"][0]["reason"]
    assert coll.files.paths_for("Smith2021").preprint_pdf.read_bytes() == b"%PDF existing"


# --- PYN-05 and PYN-06: every request is recorded; APS paths keep their casing --


def test_a_refused_landing_page_is_recorded_and_the_canonical_aps_url_still_tried(
    library: Path,
) -> None:
    def landing(doi: str) -> str | None:
        raise PublishedPdfFetchError(f"Server returned HTTP 403 for DOI {doi}")

    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        raise PublishedPdfFetchError(f"Failed to download published PDF from {url}: HTTP 403")

    _, report = _fetch(
        library,
        "Einstein1935",
        policy=FetchPolicy(published=True),
        access="institutional",
        institutional_url_fetcher=landing,
        published_pdf_fetcher=fetch,
    )

    # The entry's DOI is lowercase; the route uses APS's own spelling.
    assert asked == ["https://journals.aps.org/pr/pdf/10.1103/PhysRev.47.777"]
    [skip] = report["skipped"]
    resolve, download = skip["attempts"]
    assert resolve["stage"] == "resolve"
    assert resolve["lookup"] == "doi_landing_page"
    assert resolve["url"] == "https://doi.org/10.1103/physrev.47.777"
    assert resolve["status"] == 403
    assert resolve["retryable"] is False
    assert download["stage"] == "download"
    assert download["status"] == 403


def test_a_failed_lookup_with_nothing_to_try_still_names_the_request(library: Path) -> None:
    def throttled(doi: str) -> str | None:
        raise PublishedPdfFetchError("OpenAlex lookup failed for '10.5555/invented.1': HTTP 429")

    _, report = _fetch(
        library, "Smith2021", policy=FetchPolicy(published=True), published_url_fetcher=throttled
    )

    [failed] = report["failed"]
    [attempt] = failed["attempts"]
    assert attempt["stage"] == "resolve"
    assert attempt["lookup"] == "open_access_index"
    assert attempt["status"] == 429
    assert attempt["retryable"] is True
    assert "HTTP 429" in attempt["error"]


# --- PYN-03: coverage answers "is the collection complete?" --------------------


def test_coverage_names_each_entry_still_missing_its_pdf_and_why(library: Path) -> None:
    coll = Bibliography.open(library)

    report = coll.fetch_materials(
        policy=BEST,
        published_url_fetcher=_no_lookup,
        pdf_fetcher=lambda arxiv_id: PDF,
    )

    coverage = report["coverage"]
    assert coverage["entries"] == 3
    assert coverage["with_pdf"] == 1
    assert coverage["without_pdf"] == 2
    assert coverage["complete"] is False
    missing = {item["key"]: item for item in coverage["missing"]}
    assert set(missing) == {"Einstein1935", "Smith2021"}
    assert missing["Smith2021"]["materials"] == ["pdf"]
    assert "no open-access copy found" in missing["Smith2021"]["reason"]


def test_a_complete_collection_says_so(library: Path) -> None:
    _, report = _fetch(library, "Example2020", pdf_fetcher=lambda arxiv_id: PDF)

    assert report["coverage"]["complete"] is True
    assert report["coverage"]["missing"] == []


# --- PYN-02: discovering a missing arXiv id ------------------------------------


def _record(title: str, doi: str = "") -> ArxivRecord:
    return ArxivRecord(arxiv_id="2001.00002", title=title, doi=doi)


def test_discovery_uses_and_records_a_confirmed_arxiv_id(library: Path) -> None:
    coll, report = _fetch(
        library,
        "Smith2021",
        discover=True,
        arxiv_lookup=lambda doi: "2001.00002",
        arxiv_record_fetcher=lambda arxiv_id: _record("A study of invented things"),
        pdf_fetcher=lambda arxiv_id: PDF,
    )

    [found] = report["discovered"]
    assert found["status"] == "linked"
    assert found["verified_by"] == "title"
    assert found["written"] == ["eprint", "archiveprefix"]
    assert report["fetched"][0]["arxiv_id"] == "2001.00002"
    assert report["coverage"]["complete"] is True
    entry = coll.lib.entries.get("Smith2021")
    assert entry.fields["eprint"] == "2001.00002"
    assert entry.fields["archiveprefix"] == "arXiv"


def test_discovery_does_not_use_an_unconfirmed_id(library: Path) -> None:
    coll, report = _fetch(
        library,
        "Smith2021",
        discover=True,
        arxiv_lookup=lambda doi: "2001.00002",
        arxiv_record_fetcher=lambda arxiv_id: _record("Something Else Entirely"),
        pdf_fetcher=lambda arxiv_id: pytest.fail("an unconfirmed id was downloaded"),
    )

    [found] = report["discovered"]
    assert found["status"] == "ambiguous"
    assert found["arxiv_id"] == "2001.00002"
    assert found["written"] == []
    assert "eprint" not in coll.lib.entries.get("Smith2021").fields
    assert "ambiguous" in report["coverage"]["missing"][0]["reason"]


def test_discovery_keeps_not_checked_apart_from_not_found(library: Path) -> None:
    def throttled(doi: str) -> str | None:
        raise ProviderRateLimitedError("Semantic Scholar lookup failed: HTTP 429")

    _, report = _fetch(library, "Smith2021", discover=True, arxiv_lookup=throttled)

    [found] = report["discovered"]
    assert found["status"] == "not_checked"
    assert found["retryable"] is True
    assert "not checked" in report["coverage"]["missing"][0]["reason"].replace("_", " ")


def test_discovery_confirms_by_the_doi_arxiv_records() -> None:
    entry = Bibliography.from_text(LIBRARY).lib.entries.get("Smith2021")

    found = discover_arxiv_id(
        entry,
        "10.5555/invented.1",
        lookup=lambda doi: "2001.00002",
        record_fetcher=lambda arxiv_id: _record("A Different Title", doi="10.5555/INVENTED.1"),
    )

    assert (found.status, found.verified_by) == ("linked", "arxiv_doi")


def test_a_dry_run_discovers_nothing(library: Path) -> None:
    _, report = _fetch(
        library,
        "Smith2021",
        dry_run=True,
        discover=True,
        arxiv_lookup=lambda doi: pytest.fail("a dry run reached the network"),
    )

    assert report["discovered"] == []


# --- PYN-04: progress a reader can follow ---------------------------------------


def test_retry_waits_are_reported_as_progress_events(library: Path) -> None:
    events: list[FetchProgressEvent] = []

    def slow_pdf(arxiv_id: str) -> bytes:
        listener = RETRY_LISTENER.get()
        assert listener is not None
        listener("Server returned HTTP 503", 4.0, 2)
        return PDF

    _fetch(library, "Example2020", pdf_fetcher=slow_pdf, progress=events.append)

    [retry] = [event for event in events if event.kind == "retry"]
    assert retry.to_dict() == {
        "event": "retry",
        "key": "Example2020",
        "retry_in": 4.0,
        "attempt": 2,
        "message": "Server returned HTTP 503",
    }
    assert RETRY_LISTENER.get() is None


def test_json_lines_progress_writes_one_event_per_line(capsys) -> None:
    progress = _JsonLinesProgress()
    progress(FetchProgressEvent(kind="entry", key="A", entry_index=1, entry_total=2))
    progress(FetchProgressEvent(kind="artifact_progress", key="A", advance=10))
    progress(FetchProgressEvent(kind="artifact_done", key="A", artifact="preprint_pdf"))

    captured = capsys.readouterr()
    assert captured.out == ""
    lines = [json.loads(line) for line in captured.err.splitlines()]
    assert lines == [
        {"event": "entry", "key": "A", "entry_index": 1, "entry_total": 2},
        {"event": "artifact_done", "key": "A", "artifact": "preprint_pdf"},
    ]
