"""``asset fetch`` diagnostics: candidate URLs, recorded attempts, summary, and ``--strict``.

Every request goes to an ``httpx.MockTransport`` or an injected fetcher; DNS is
stubbed by ``conftest``. Nothing here reaches the network.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import httpx
import pytest
from typer.testing import CliRunner

from pynakes._fetch_attempts import (
    aps_pdf_url,
    attempt_record,
    candidate_urls,
    describe_attempts,
    redact_url,
)
from pynakes.cli import app
from pynakes.fetch import (
    ArxivFetchError,
    PublishedPdfFetchError,
    download_arxiv_materials,
    download_published_material,
    download_supplement_material,
    fetch_arxiv_pdf,
)
from pynakes.filestore import FileStore
from pynakes.providers._http import fetch_bytes

runner = CliRunner()

EPR_DOI = "10.1103/PhysRev.47.777"
EPR_CANONICAL = "https://journals.aps.org/pr/pdf/10.1103/PhysRev.47.777"
EPR_LEGACY = "http://link.aps.org/pdf/10.1103/PhysRev.47.777"
PDF = b"%PDF-1.4 invented fixture"
HTML = b"<!DOCTYPE html><html><body>Just a moment</body></html>"


def _mock_http(monkeypatch: pytest.MonkeyPatch, handler) -> list[str]:
    """Route every pynakes HTTP request to *handler*; return the URLs requested."""
    requested: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return handler(request)

    transport = httpx.MockTransport(record)
    original = httpx.Client

    class MockClient(original):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("pynakes.providers._http.httpx.Client", MockClient)
    return requested


def _pdf(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})


def _store(tmp_path: Path) -> FileStore:
    return FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")


# --- candidate URLs ---------------------------------------------------------


@pytest.mark.parametrize(
    ("doi", "expected"),
    [
        (EPR_DOI, EPR_CANONICAL),
        (
            "10.1103/PhysRevLett.12.345",
            "https://journals.aps.org/prl/pdf/10.1103/PhysRevLett.12.345",
        ),
        # A lowercased DOI is the same DOI, but APS serves the PDF only under the
        # journal's own spelling of the prefix.
        ("10.1103/physrevx.3.21", "https://journals.aps.org/prx/pdf/10.1103/PhysRevX.3.21"),
        ("10.1103/PHYSREVB.46.1", "https://journals.aps.org/prb/pdf/10.1103/PhysRevB.46.1"),
        ("10.1103/RevModPhys.1.1", "https://journals.aps.org/rmp/pdf/10.1103/RevModPhys.1.1"),
        (
            "10.1103/PRXQuantum.2.10",
            "https://journals.aps.org/prxquantum/pdf/10.1103/PRXQuantum.2.10",
        ),
        ("10.1103/abcd-wxyz", None),  # APS's newer DOIs name no journal
        ("10.1103/UnknownJournal.1.2", None),
        ("10.1002/andp.19053221004", None),
    ],
)
def test_aps_pdf_url_maps_the_journal_prefix_to_its_code(doi: str, expected: str | None) -> None:
    assert aps_pdf_url(doi) == expected


def test_candidate_urls_prefer_the_canonical_aps_url_then_https() -> None:
    assert candidate_urls(EPR_LEGACY, EPR_DOI) == [
        EPR_CANONICAL,
        "https://link.aps.org/pdf/10.1103/PhysRev.47.777",
        EPR_LEGACY,
    ]
    # Already canonical: tried once.
    assert candidate_urls(EPR_CANONICAL, EPR_DOI) == [EPR_CANONICAL]


def test_candidate_urls_leave_other_publishers_alone() -> None:
    url = "https://publisher.example/article.pdf"
    assert candidate_urls(url, "10.5555/invented") == [url]
    # An APS DOI served by another host is not rewritten to APS.
    assert candidate_urls(url, EPR_DOI) == [url]
    # Plain HTTP is upgraded first, the original kept as the last resort.
    assert candidate_urls("http://publisher.example/a.pdf", "10.5555/invented") == [
        "https://publisher.example/a.pdf",
        "http://publisher.example/a.pdf",
    ]


def test_redact_url_drops_credentials_tokens_and_fragments() -> None:
    url = (
        "https://user:pass@publisher.example:8443/pdf?id=7&token=s3cr3t&API_KEY=k"
        "&Signature=x&blob=" + "A" * 40 + "#page=2"
    )
    assert redact_url(url) == "https://publisher.example:8443/pdf?id=7"
    assert redact_url(None) is None


def test_attempt_record_keeps_only_safe_fields() -> None:
    record = attempt_record(
        "https://publisher.example/a.pdf?token=s3cr3t",
        {
            "final_url": "https://cdn.example/a.pdf?sig=abc",
            "status": 200,
            "content_type": "Text/HTML; charset=utf-8",
        },
        "not_pdf",
    )
    assert record == {
        "url": "https://publisher.example/a.pdf",
        "final_url": "https://cdn.example/a.pdf",
        "status": 200,
        "content_type": "text/html",
        "outcome": "not_pdf",
        "stage": "download",
        "retryable": False,
    }
    assert describe_attempts([record]) == "cdn.example (HTTP 200, text/html)"
    assert describe_attempts([attempt_record("https://a.example/x", None, "network_error")]) == (
        "a.example (network error)"
    )


# --- the transport reports what the server answered --------------------------


def test_fetch_bytes_reports_the_response_through_redirects(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "old.example":
            return httpx.Response(301, headers={"location": "https://new.example/landing"})
        return httpx.Response(200, content=HTML, headers={"content-type": "text/html"})

    _mock_http(monkeypatch, handler)
    info: dict = {}
    assert fetch_bytes("https://old.example/a.pdf", response_info=info) == HTML
    assert info == {
        "final_url": "https://new.example/landing",
        "status": 200,
        "content_type": "text/html",
    }


def test_fetch_bytes_reports_an_injected_openers_http_error() -> None:
    def opener(request, timeout):
        raise HTTPError(request.full_url, 403, "Forbidden", {"Content-Type": "text/html"}, None)

    info: dict = {}
    with pytest.raises(Exception, match="HTTP 403"):
        fetch_bytes("https://publisher.example/a.pdf", opener=opener, response_info=info)
    assert info["status"] == 403
    assert info["content_type"] == "text/html"


# --- published PDFs: APS URLs, fallbacks, and attempts -----------------------


def test_aps_legacy_url_is_replaced_by_the_canonical_url(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == EPR_CANONICAL:
            return _pdf(request)
        return httpx.Response(403, content=HTML, headers={"content-type": "text/html"})

    requested = _mock_http(monkeypatch, handler)
    result = download_published_material(
        _store(tmp_path), "Einstein1935", EPR_DOI, url_resolver=lambda doi: EPR_LEGACY
    )

    assert result.pdf_path is not None
    assert result.pdf_path.read_bytes() == PDF
    assert requested == [EPR_CANONICAL]
    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    assert manifest["files"]["Einstein1935"]["published_pdf"]["source"] == EPR_CANONICAL


def test_a_failed_canonical_url_falls_back_to_the_resolved_url(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "journals.aps.org":
            return httpx.Response(200, content=HTML, headers={"content-type": "text/html"})
        if request.url.scheme == "https":
            return httpx.Response(403)
        return _pdf(request)

    requested = _mock_http(monkeypatch, handler)
    result = download_published_material(
        _store(tmp_path), "Einstein1935", EPR_DOI, url_resolver=lambda doi: EPR_LEGACY
    )

    assert result.pdf_path is not None
    assert requested == [
        EPR_CANONICAL,
        "https://link.aps.org/pdf/10.1103/PhysRev.47.777",
        EPR_LEGACY,
    ]


def test_other_publishers_get_exactly_the_resolved_url(tmp_path: Path, monkeypatch) -> None:
    requested = _mock_http(monkeypatch, _pdf)
    result = download_published_material(
        _store(tmp_path),
        "Noether1918",
        "10.5555/invented",
        url_resolver=lambda doi: "https://publisher.example/article.pdf",
    )
    assert result.pdf_path is not None
    assert requested == ["https://publisher.example/article.pdf"]


def test_every_url_refused_is_a_failure_listing_each_request(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=HTML, headers={"content-type": "text/html"})

    _mock_http(monkeypatch, handler)
    with pytest.raises(PublishedPdfFetchError) as caught:
        download_published_material(
            _store(tmp_path), "Einstein1935", EPR_DOI, url_resolver=lambda doi: EPR_LEGACY
        )

    error = caught.value
    assert error.artifact == "published_pdf"
    assert "HTTP 403" in str(error)
    assert "3 URLs tried" in str(error)
    assert [attempt["url"] for attempt in error.attempts] == [
        EPR_CANONICAL,
        "https://link.aps.org/pdf/10.1103/PhysRev.47.777",
        EPR_LEGACY,
    ]
    assert {attempt["status"] for attempt in error.attempts} == {403}
    assert {attempt["content_type"] for attempt in error.attempts} == {"text/html"}
    assert {attempt["outcome"] for attempt in error.attempts} == {"http_error"}


def test_a_page_that_is_not_a_pdf_is_a_skip_with_redacted_attempts(
    tmp_path: Path, monkeypatch
) -> None:
    resolved = "http://publisher.example/pdf?id=7&token=s3cr3t"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.scheme == "https":
            return httpx.Response(404)
        if request.url.path == "/pdf":
            return httpx.Response(302, headers={"location": "http://publisher.example/landing"})
        return httpx.Response(200, content=HTML, headers={"content-type": "text/html"})

    _mock_http(monkeypatch, handler)
    with pytest.raises(PublishedPdfFetchError) as caught:
        download_published_material(
            _store(tmp_path), "Noether1918", "10.5555/invented", url_resolver=lambda doi: resolved
        )
    # The HTTPS form answered 404: an error, so the run reports a failure.
    attempts = caught.value.attempts
    assert attempts[0] == {
        "url": "https://publisher.example/pdf?id=7",
        "final_url": "https://publisher.example/pdf?id=7",
        "status": 404,
        "content_type": None,
        "outcome": "http_error",
        "stage": "download",
        "retryable": False,
    }
    assert attempts[1] == {
        "url": "http://publisher.example/pdf?id=7",
        "final_url": "http://publisher.example/landing",
        "status": 200,
        "content_type": "text/html",
        "outcome": "not_pdf",
        "stage": "download",
        "retryable": False,
    }
    assert "s3cr3t" not in json.dumps(attempts) + str(caught.value)


def test_only_non_pdf_answers_are_a_skip_with_attempts(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=HTML, headers={"content-type": "text/html"})

    _mock_http(monkeypatch, handler)
    result = download_published_material(
        _store(tmp_path),
        "Noether1918",
        "10.5555/invented",
        url_resolver=lambda doi: "https://publisher.example/article.pdf",
    )
    assert result.pdf_path is None
    assert result.reason == f"publisher URL served an HTML page ({len(HTML)} bytes), not a PDF"
    item = result.to_dict()
    assert item["attempts"] == [
        {
            "url": "https://publisher.example/article.pdf",
            "final_url": "https://publisher.example/article.pdf",
            "status": 200,
            "content_type": "text/html",
            "outcome": "not_pdf",
            "stage": "download",
            "retryable": False,
        }
    ]


def test_supplement_failures_record_their_request(tmp_path: Path, monkeypatch) -> None:
    _mock_http(monkeypatch, lambda request: httpx.Response(410))
    with pytest.raises(Exception) as caught:
        download_supplement_material(
            _store(tmp_path),
            "Noether1918",
            "10.5555/invented",
            url_resolver=lambda doi: ("https://publisher.example/si.pdf",),
        )
    assert caught.value.attempts[0]["status"] == 410  # type: ignore[attr-defined]
    assert caught.value.artifact == "supplement_pdf"  # type: ignore[attr-defined]


def test_arxiv_failures_name_the_artifact_and_request(monkeypatch) -> None:
    _mock_http(monkeypatch, lambda request: httpx.Response(404))
    with pytest.raises(ArxivFetchError) as caught:
        fetch_arxiv_pdf("2345.6789")
    assert caught.value.artifact == "preprint_pdf"
    assert caught.value.attempts[0]["url"] == "https://arxiv.org/pdf/2345.6789"
    assert caught.value.attempts[0]["status"] == 404


# --- what lands is what is reported -----------------------------------------


def test_a_source_failure_after_the_preprint_pdf_carries_the_installed_pdf(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    def unavailable(arxiv_id: str) -> bytes:
        raise ArxivFetchError("Server returned HTTP 503 for arXiv source")

    with pytest.raises(ArxivFetchError) as caught:
        download_arxiv_materials(
            store,
            "Turing1936",
            "2345.6789",
            pdf_fetcher=lambda arxiv_id: PDF,
            source_fetcher=unavailable,
        )

    error = caught.value
    assert error.artifact == "preprint_source"
    assert error.attempts[0]["url"] == "https://arxiv.org/e-print/2345.6789"
    assert error.partial is not None
    assert error.partial.pdf_path == tmp_path / "refs.files" / "Turing1936.preprint.pdf"
    assert error.partial.pdf_path.read_bytes() == PDF
    row = store.read_manifest()["files"]["Turing1936"]
    assert row["preprint_pdf"]["source"] == "https://arxiv.org/pdf/2345.6789"
    assert "preprint_source" not in row


def test_a_corrupt_source_after_the_preprint_pdf_names_the_source(tmp_path: Path) -> None:
    with pytest.raises(ArxivFetchError) as caught:
        download_arxiv_materials(
            _store(tmp_path),
            "Turing1936",
            "2345.6789",
            pdf_fetcher=lambda arxiv_id: PDF,
            source_fetcher=lambda arxiv_id: b"not a tarball",
        )
    assert caught.value.artifact == "preprint_source"
    assert caught.value.partial is not None


def test_a_source_failure_alone_carries_nothing_installed(tmp_path: Path) -> None:
    def unavailable(arxiv_id: str) -> bytes:
        raise ArxivFetchError("Server returned HTTP 503 for arXiv source")

    with pytest.raises(ArxivFetchError) as caught:
        download_arxiv_materials(
            _store(tmp_path), "Turing1936", "2345.6789", pdf=False, source_fetcher=unavailable
        )
    assert caught.value.partial is None


def test_the_envelope_reports_a_preprint_pdf_fetched_before_its_source_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@misc{Turing1936,\n  title = {On Computable Numbers},\n"
        "  eprint = {2345.6789},\n  archiveprefix = {arXiv},\n}\n",
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/pdf/"):
            return _pdf(request)
        return httpx.Response(404)

    _mock_http(monkeypatch, handler)

    result = runner.invoke(
        app,
        ["asset", "fetch", str(bib), "--material", "preprint", "--material", "source", "--json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    [fetched] = data["fetched"]
    assert fetched["key"] == "Turing1936"
    assert fetched["pdf_path"].endswith("Turing1936.preprint.pdf")
    assert fetched["source_path"] is None
    [failure] = data["failed"]
    assert failure["artifact"] == "preprint_source"
    assert failure["attempts"][0]["status"] == 404
    assert data["summary"]["fetched"] == 1
    assert data["summary"]["failed"] == 1
    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    assert set(manifest["files"]["Turing1936"]) == {"preprint_pdf"}


def test_the_manifest_records_a_redacted_published_source(tmp_path: Path, monkeypatch) -> None:
    signed = "https://cdn.example/paper.pdf?Expires=1&Signature=abc&Key-Pair-Id=k&page=1"
    _mock_http(monkeypatch, _pdf)

    result = download_published_material(
        _store(tmp_path), "Noether1918", "10.5555/noether", url_resolver=lambda doi: signed
    )

    assert result.pdf_path is not None
    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    recorded = manifest["files"]["Noether1918"]["published_pdf"]["source"]
    assert recorded == "https://cdn.example/paper.pdf?page=1"


# --- the CLI envelope: summary, warnings, --strict ----------------------------

BATCH = """@article{Einstein1935,
  title = {Can Quantum-Mechanical Description of Physical Reality Be Considered Complete?},
  doi = {10.1103/PhysRev.47.777},
}

@misc{Turing1936,
  title = {On Computable Numbers},
  eprint = {2345.6789},
  archiveprefix = {arXiv},
}

@book{Newton1687,
  title = {Principia},
}

@article{Noether1918,
  title = {Invariante Variationsprobleme},
  doi = {10.5555/noether},
}

@misc{Kepler1609,
  title = {Astronomia Nova},
  eprint = {1609.0001},
  archiveprefix = {arXiv},
}

@comment{pynakes-meta:
pinax-files-dir: refs.files
}
"""


@pytest.fixture
def batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bib = tmp_path / "refs.bib"
    bib.write_text(BATCH, encoding="utf-8")
    (tmp_path / "refs.files").mkdir()
    (tmp_path / "refs.files" / "Kepler1609.preprint.pdf").write_bytes(PDF)
    oa = {EPR_DOI: EPR_LEGACY}
    monkeypatch.setattr(
        "pynakes.providers.metadata.openalex.oa_pdf_url_for_doi",
        lambda doi, **kwargs: oa.get(doi),
    )
    monkeypatch.setattr(
        "pynakes.providers.metadata.crossref.oa_pdf_url_for_doi", lambda doi, **kwargs: None
    )
    monkeypatch.setattr("pynakes.fetch.fetch_arxiv_pdf", lambda arxiv_id, **kwargs: PDF)
    _mock_http(
        monkeypatch,
        lambda request: httpx.Response(403, content=HTML, headers={"content-type": "text/html"}),
    )
    return bib


def _fetch(bib: Path, *extra: str):
    return runner.invoke(
        app, ["asset", "fetch", str(bib), "--material", "best-pdf", "--json", *extra]
    )


def test_a_partial_batch_reports_counts_and_a_warning_per_failure(batch: Path) -> None:
    result = _fetch(batch)

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["strict"] is False
    assert data["summary"] == {
        "requested": 5,
        "fetched": 1,
        "already_present": 1,
        "unavailable": 2,
        "failed": 1,
        "planned": 0,
    }
    [failure] = data["failed"]
    assert failure["key"] == "Einstein1935"
    assert failure["artifact"] == "published_pdf"
    assert failure["attempts"][0]["url"] == EPR_CANONICAL
    assert [attempt["status"] for attempt in failure["attempts"]] == [403, 403, 403]
    assert data["warnings"] == [
        {
            "type": "download_failed",
            "key": "Einstein1935",
            "artifact": "published_pdf",
            "message": failure["error"],
        }
    ]
    reasons = {item["key"]: item["reason"] for item in data["skipped"]}
    assert reasons["Newton1687"] == "no arXiv id and no DOI"
    assert reasons["Noether1918"] == (
        "no open-access copy found; no arXiv id for a preprint fallback "
        "(`pynakes enrich --published --online` can look one up by DOI)"
    )
    assert reasons["Kepler1609"].startswith("materials already present")
    noether = next(item for item in data["skipped"] if item["key"] == "Noether1918")
    assert noether["attempts"] == []


def test_strict_fails_an_incomplete_run_but_still_reports_it(batch: Path) -> None:
    result = _fetch(batch, "--strict")

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["strict"] is True
    assert data["summary"]["fetched"] == 1
    assert (batch.parent / "refs.files" / "Turing1936.preprint.pdf").read_bytes() == PDF


def test_strict_passes_when_everything_requested_is_present(batch: Path) -> None:
    result = _fetch(batch, "--strict", "--key", "Kepler1609,Turing1936")

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["summary"]["already_present"] == 1
    assert data["summary"]["fetched"] == 1


def test_human_output_names_hosts_statuses_and_counts(batch: Path) -> None:
    result = runner.invoke(app, ["asset", "fetch", str(batch), "--material", "best-pdf"])

    assert result.exit_code == 0, result.output
    assert "tried journals.aps.org (HTTP 403, text/html); link.aps.org (HTTP 403" in result.output
    assert "Summary: 5 requested; 1 fetched, 1 already present, 2 unavailable, 1 failed." in (
        " ".join(result.output.split())
    )


def test_best_pdf_falls_back_to_the_preprint_when_the_published_pdf_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{Einstein1935,\n  title = {Physical Reality},\n"
        "  doi = {10.1103/PhysRev.47.777},\n  eprint = {1935.0001},\n"
        "  archiveprefix = {arXiv},\n}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pynakes.providers.metadata.openalex.oa_pdf_url_for_doi", lambda doi, **kw: EPR_LEGACY
    )
    monkeypatch.setattr("pynakes.fetch.fetch_arxiv_pdf", lambda arxiv_id, **kwargs: PDF)
    _mock_http(monkeypatch, lambda request: httpx.Response(403))

    result = _fetch(bib, "--strict")

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["failed"] == []
    assert data["fetched"][0]["arxiv_id"] == "1935.0001"
    [warning] = data["warnings"]
    assert warning["type"] == "download_failed"
    assert warning["fallback"] == "preprint_pdf"
    assert warning["message"].endswith("fetched the preprint PDF instead")


def test_a_dry_run_counts_planned_work(batch: Path) -> None:
    result = _fetch(batch, "--dry-run", "--strict")

    data = json.loads(result.output)
    assert data["summary"]["planned"] == 3
    assert data["summary"]["unavailable"] == 1
    assert data["summary"]["already_present"] == 1
    # One entry has no identifier to fetch by, so even the plan is incomplete.
    assert result.exit_code == 1


# --- skips name the missing arXiv id, and how to find one --------------------


def _skips(tmp_path: Path, bib_text: str, policy) -> dict:
    from pynakes.engine import Bibliography

    bib = tmp_path / "refs.bib"
    bib.write_text(bib_text + "@comment{pynakes-meta:\npinax-files-dir: refs.files\n}\n")
    (tmp_path / "refs.files").mkdir(exist_ok=True)
    return Bibliography.open(bib).fetch_materials(policy=policy, dry_run=True)


def test_a_missing_arxiv_id_is_hinted_only_when_a_doi_could_find_one(tmp_path: Path) -> None:
    from pynakes.metadata import FetchPolicy

    report = _skips(
        tmp_path,
        "@book{Newton1687, title = {Principia}}\n"
        "@article{Einstein1935, title = {Physical Reality}, doi = {10.1103/PhysRev.47.777}}\n",
        FetchPolicy(preprint=True, published=False, source=False, supplement=False, bestpdf=False),
    )
    reasons = {item["key"]: item["reason"] for item in report["skipped"]}
    assert reasons["Newton1687"] == "no arXiv id"
    assert reasons["Einstein1935"] == (
        "no arXiv id (`pynakes enrich --published --online` can look one up by DOI)"
    )
    assert report["summary"]["unavailable"] == 2


def test_an_explicitly_requested_preprint_is_unavailable_beside_a_present_pdf(
    tmp_path: Path,
) -> None:
    from pynakes.metadata import FetchPolicy

    (tmp_path / "refs.files").mkdir()
    (tmp_path / "refs.files" / "Einstein1935.published.pdf").write_bytes(PDF)
    entry = "@article{Einstein1935, title = {Physical Reality}, doi = {10.1103/PhysRev.47.777}}\n"

    both = _skips(
        tmp_path,
        entry,
        FetchPolicy(preprint=True, published=True, source=False, supplement=False, bestpdf=False),
    )
    assert both["skipped"][0]["reason"] == (
        "materials already present (no arXiv id for a preprint; "
        "`pynakes enrich --published --online` can look one up by DOI)"
    )
    assert both["summary"]["unavailable"] == 1

    best = _skips(tmp_path, entry, FetchPolicy(bestpdf=True))
    assert best["skipped"][0]["reason"] == "materials already present (no arXiv id for a preprint)"
    assert best["summary"]["already_present"] == 1
