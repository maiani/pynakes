"""arXiv material download core tests."""

from __future__ import annotations

import json
import tarfile
import zlib
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from pynakes.cli_commands.fetch import _RichFetchProgress
from pynakes.fetch import (
    ArxivFetchError,
    ArxivSourceUnavailableError,
    PublishedPdfFetchError,
    crossref_oa_pdf_url,
    download_arxiv_materials,
    download_published_material,
    download_supplement_material,
    extract_arxiv_source,
    fetch_arxiv_pdf,
    fetch_published_pdf,
    openalex_oa_pdf_url,
)
from pynakes.fetch_progress import FetchProgressEvent
from pynakes.filestore import FileStore


def _mock_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("pynakes.providers._http.httpx.Client", MockClient)


def test_rich_fetch_progress_tracks_artifact_lifecycle() -> None:
    class FakeProgress:
        def __init__(self) -> None:
            self.next_id = 0
            self.updated: list[tuple[object, dict[str, object]]] = []
            self.removed: list[object] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def add_task(self, description: str, *, total: int | None):
            self.next_id += 1
            return self.next_id

        def update(self, task_id: object, **kwargs: object) -> None:
            self.updated.append((task_id, kwargs))

        def remove_task(self, task_id: object) -> None:
            self.removed.append(task_id)

    progress = _RichFetchProgress()
    fake = FakeProgress()
    progress._progress = fake  # type: ignore[assignment]

    assert progress.__enter__() is progress
    progress(
        FetchProgressEvent(
            kind="artifact_start", key="Noether1918", artifact="preprint_pdf", total_bytes=12
        )
    )
    progress(
        FetchProgressEvent(
            kind="artifact_progress",
            key="Noether1918",
            artifact="preprint_pdf",
            advance=5,
            total_bytes=12,
        )
    )
    progress(
        FetchProgressEvent(
            kind="artifact_progress", key="Missing", artifact="preprint_pdf", advance=1
        )
    )
    progress(
        FetchProgressEvent(
            kind="artifact_done", key="Noether1918", artifact="preprint_pdf", total_bytes=12
        )
    )
    progress(
        FetchProgressEvent(kind="artifact_start", key="Noether1918", artifact="preprint_source")
    )
    progress(FetchProgressEvent(kind="fail", key="Noether1918"))
    progress(FetchProgressEvent(kind="start", key="Noether1918"))
    assert progress.__exit__(None, None, None) is False

    assert fake.updated[0][1] == {"advance": 5, "total": 12}
    assert fake.removed == [1, 2]


def test_fetch_arxiv_pdf_reads_bytes_with_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    progress: list[tuple[int, int | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"%PDF fixture", headers={"content-length": "12"})

    _mock_httpx_client(monkeypatch, handler)
    data = fetch_arxiv_pdf(
        "2101.00001v2",
        progress=lambda event: progress.append((event.advance, event.total_bytes)),
        key="Noether1918",
    )

    assert data == b"%PDF fixture"
    assert str(seen[0].url) == "https://arxiv.org/pdf/2101.00001"
    assert seen[0].headers["user-agent"].startswith("pynakes/")
    assert progress == [(12, 12)]


def test_fetch_arxiv_pdf_wraps_url_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    _mock_httpx_client(monkeypatch, handler)

    with pytest.raises(ArxivFetchError, match="2101.00001"):
        fetch_arxiv_pdf("2101.00001")


def test_download_arxiv_materials_writes_pdf_and_source(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    calls: list[tuple[str, str]] = []

    def pdf_fetcher(arxiv_id: str) -> bytes:
        calls.append(("pdf", arxiv_id))
        return b"%PDF preprint"

    def source_fetcher(arxiv_id: str) -> bytes:
        calls.append(("source", arxiv_id))
        return _tar_bytes({"paper.tex": b"\\title{Fixture}\n", "src/notes.txt": b"notes\n"})

    result = download_arxiv_materials(
        store,
        "Noether1918",
        "https://arxiv.org/abs/2101.00001v2",
        pdf_fetcher=pdf_fetcher,
        source_fetcher=source_fetcher,
        fetched_date="2026-06-27",
    )

    assert calls == [("pdf", "2101.00001"), ("source", "2101.00001")]
    assert result.to_dict() == {
        "key": "Noether1918",
        "arxiv_id": "2101.00001",
        "pdf_path": str(tmp_path / "refs.files" / "Noether1918.preprint.pdf"),
        "source_path": str(tmp_path / "refs.files" / "Noether1918.source"),
    }
    assert (tmp_path / "refs.files" / "Noether1918.preprint.pdf").read_bytes() == (b"%PDF preprint")
    assert (tmp_path / "refs.files" / "Noether1918.source" / "paper.tex").read_bytes() == (
        b"\\title{Fixture}\n"
    )
    assert (tmp_path / "refs.files" / "Noether1918.source" / "src" / "notes.txt").read_bytes() == (
        b"notes\n"
    )
    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    row = manifest["files"]["Noether1918"]
    assert row["preprint_canonical"] is False
    assert row["preprint_pdf"]["source"] == "https://arxiv.org/pdf/2101.00001"
    assert row["preprint_pdf"]["fetched_date"] == "2026-06-27"
    assert row["preprint_pdf"]["refetchable"] is True
    assert len(row["preprint_pdf"]["sha256"]) == 64
    assert row["preprint_source"]["source"] == "https://arxiv.org/e-print/2101.00001"


def test_source_extraction_rejects_path_traversal(tmp_path: Path) -> None:
    target = tmp_path / "source"

    with pytest.raises(ArxivFetchError, match="Unsafe arXiv source archive path"):
        extract_arxiv_source(_tar_bytes({"../escape.tex": b"bad"}), target)

    assert not (tmp_path / "escape.tex").exists()


def test_source_extraction_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "source"

    with pytest.raises(ArxivFetchError, match="Unsafe arXiv source archive link"):
        extract_arxiv_source(_tar_bytes({}, symlinks={"paper.tex": "../escape.tex"}), target)


def test_source_extraction_reports_pdf_only_deposit(tmp_path: Path) -> None:
    target = tmp_path / "source"

    with pytest.raises(ArxivSourceUnavailableError, match="PDF-only submission"):
        extract_arxiv_source(b"%PDF-1.5\n...binary...", target)


def test_source_extraction_writes_single_gzipped_file_under_recorded_name(tmp_path: Path) -> None:
    # Old single-file submissions are served as one gzipped .tex, not a tar.
    target = tmp_path / "source"
    tex = b"\\input harvmac\n\\title{Invariante Variationsprobleme}\n" * 20

    extract_arxiv_source(_gzip_bytes(tex, name=b"noether.tex"), target)

    assert [p.name for p in target.iterdir()] == ["noether.tex"]
    assert (target / "noether.tex").read_bytes() == tex


@pytest.mark.parametrize(
    ("recorded", "written"),
    [
        (None, "main.tex"),
        (b"../../escape.tex", "escape.tex"),
        (b"C:\\papers\\noether.tex", "noether.tex"),
        (b"..", "main.tex"),
        (b".hidden.tex", "main.tex"),
        (b"two words.tex", "main.tex"),
    ],
)
def test_single_file_source_keeps_only_a_plain_recorded_name(
    tmp_path: Path, recorded: bytes | None, written: str
) -> None:
    target = tmp_path / "work" / "source"

    extract_arxiv_source(_gzip_bytes(b"\\bye\n", name=recorded, extra=b"xx"), target)

    assert [p.name for p in target.iterdir()] == [written]
    assert not (tmp_path / "escape.tex").exists()
    assert not (tmp_path / "work" / "escape.tex").exists()


def test_download_arxiv_materials_installs_single_file_source(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    result = download_arxiv_materials(
        store,
        "Noether1918",
        "2101.00001",
        pdf=False,
        source_fetcher=lambda arxiv_id: _gzip_bytes(b"\\bye\n", name=b"noether.tex"),
    )

    assert result.source_path == tmp_path / "refs.files" / "Noether1918.source"
    assert result.source_unavailable is False
    assert (result.source_path / "noether.tex").read_bytes() == b"\\bye\n"
    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    assert manifest["files"]["Noether1918"]["preprint_source"]["source"] == (
        "https://arxiv.org/e-print/2101.00001"
    )


def test_source_extraction_reports_truncated_archive(tmp_path: Path) -> None:
    # tarfile lets EOFError escape a cut-off gzip stream; it must surface as a
    # per-entry ArxivFetchError rather than abort the whole fetch run.
    archive = _tar_bytes({"paper.tex": bytes(range(256)) * 400})

    with pytest.raises(ArxivFetchError, match="truncated or corrupt"):
        extract_arxiv_source(archive[: len(archive) // 2], tmp_path / "source")


def test_source_extraction_reports_corrupt_single_file(tmp_path: Path) -> None:
    data = bytearray(_gzip_bytes(b"\\bye\n" * 200, name=b"noether.tex"))
    data[-8] ^= 0xFF  # break the CRC in the gzip trailer

    with pytest.raises(ArxivFetchError, match="not a readable gzip file"):
        extract_arxiv_source(bytes(data), tmp_path / "source")


def test_source_extraction_rejects_bytes_that_are_neither_tar_nor_gzip(tmp_path: Path) -> None:
    with pytest.raises(ArxivFetchError, match="not a readable tar archive"):
        extract_arxiv_source(b"<html>Service unavailable</html>", tmp_path / "source")


def test_download_arxiv_materials_pdf_only_source_keeps_pdf(tmp_path: Path) -> None:
    """A PDF-only deposit must not discard the successfully fetched PDF."""
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    result = download_arxiv_materials(
        store,
        "Noether1918",
        "2101.00001",
        pdf_fetcher=lambda arxiv_id: b"%PDF preprint",
        source_fetcher=lambda arxiv_id: b"%PDF-1.5 not a tar",
        fetched_date="2026-06-27",
    )

    assert result.pdf_path == tmp_path / "refs.files" / "Noether1918.preprint.pdf"
    assert result.source_path is None
    assert result.source_unavailable is True
    assert (tmp_path / "refs.files" / "Noether1918.preprint.pdf").read_bytes() == b"%PDF preprint"
    assert not (tmp_path / "refs.files" / "Noether1918.source").exists()

    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    row = manifest["files"]["Noether1918"]
    assert "preprint_pdf" in row
    assert "preprint_source" not in row


def test_failed_source_download_leaves_existing_source_tree(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    existing = root / "Noether1918.source"
    existing.mkdir(parents=True)
    (existing / "old.tex").write_text("old\n")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    with pytest.raises(ArxivFetchError):
        download_arxiv_materials(
            store,
            "Noether1918",
            "2101.00001",
            pdf=False,
            source_fetcher=lambda arxiv_id: _tar_bytes({"../escape.tex": b"bad"}),
        )

    assert (existing / "old.tex").read_text() == "old\n"
    assert not (tmp_path / "escape.tex").exists()


# ---------------------------------------------------------------------------
# Open-access published PDF helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal file-like response for injected ``urlopen``."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


_OPENALEX_WITH_OA = json.dumps(
    {
        "best_oa_location": {
            "host_type": "publisher",
            "pdf_url": "https://example.com/paper.pdf",
        }
    }
).encode("utf-8")

_OPENALEX_WITHOUT_OA = json.dumps(
    {
        "best_oa_location": None,
    }
).encode("utf-8")


def test_openalex_oa_pdf_url_resolves_url(tmp_path: Path) -> None:
    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        target = request.full_url if hasattr(request, "full_url") else str(request)
        assert "api.openalex.org/works/doi:" in str(target)
        return _FakeResponse(_OPENALEX_WITH_OA)

    url = openalex_oa_pdf_url("10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen)
    assert url == "https://example.com/paper.pdf"


def test_openalex_oa_pdf_url_returns_none_when_no_oa(tmp_path: Path) -> None:
    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        return _FakeResponse(_OPENALEX_WITHOUT_OA)

    url = openalex_oa_pdf_url("10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen)
    assert url is None


def test_openalex_oa_pdf_url_uses_cache(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache"
    calls: list[int] = []

    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        calls.append(1)
        return _FakeResponse(_OPENALEX_WITH_OA)

    url1 = openalex_oa_pdf_url(
        "10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen, cache_file=cache_file
    )
    assert url1 == "https://example.com/paper.pdf"
    assert len(calls) == 1

    url2 = openalex_oa_pdf_url(
        "10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen, cache_file=cache_file
    )
    assert url2 == "https://example.com/paper.pdf"
    assert len(calls) == 1  # served from cache, no second call


def test_openalex_oa_pdf_url_does_not_cache_invalid_json(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache"

    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        return _FakeResponse(b"<html>not json</html>")

    with pytest.raises(PublishedPdfFetchError, match="invalid JSON"):
        openalex_oa_pdf_url(
            "10.1103/PhysRevLett.100.123456",
            urlopen=fake_urlopen,
            cache_file=cache_file,
        )

    assert not list(cache_file.rglob("*.json"))


_CROSSREF_WITH_PDF = json.dumps(
    {
        "status": "ok",
        "message": {
            "link": [
                {
                    "URL": "https://www.nature.com/articles/s41586-023-06747-5.pdf",
                    "content-type": "application/pdf",
                    "content-version": "vor",
                    "intended-application": "text-mining",
                }
            ]
        },
    }
).encode("utf-8")

_CROSSREF_WITH_SIMILARITY = json.dumps(
    {
        "status": "ok",
        "message": {
            "link": [
                {
                    "URL": "http://harvest.aps.org/v2/journals/articles/10.1103/f6nc-vsnx/fulltext",
                    "content-type": "unspecified",
                    "content-version": "vor",
                    "intended-application": "similarity-checking",
                }
            ]
        },
    }
).encode("utf-8")

_CROSSREF_WITHOUT_PDF = json.dumps(
    {
        "status": "ok",
        "message": {
            "link": [],
        },
    }
).encode("utf-8")


def test_crossref_oa_pdf_url_resolves_pdf_link(tmp_path: Path) -> None:
    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        target = request.full_url if hasattr(request, "full_url") else str(request)
        assert "api.crossref.org/works/" in str(target)
        return _FakeResponse(_CROSSREF_WITH_PDF)

    url = crossref_oa_pdf_url("10.1038/s41586-023-06747-5", urlopen=fake_urlopen)
    assert url == "https://www.nature.com/articles/s41586-023-06747-5.pdf"


def test_crossref_oa_pdf_url_falls_back_to_similarity_checking(tmp_path: Path) -> None:
    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        return _FakeResponse(_CROSSREF_WITH_SIMILARITY)

    url = crossref_oa_pdf_url("10.1103/f6nc-vsnx", urlopen=fake_urlopen)
    assert url == "http://harvest.aps.org/v2/journals/articles/10.1103/f6nc-vsnx/fulltext"


def test_crossref_oa_pdf_url_returns_none_when_no_links(tmp_path: Path) -> None:
    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        return _FakeResponse(_CROSSREF_WITHOUT_PDF)

    url = crossref_oa_pdf_url("10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen)
    assert url is None


def test_crossref_oa_pdf_url_returns_none_when_no_work(tmp_path: Path) -> None:
    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        return _FakeResponse(b"{}")

    url = crossref_oa_pdf_url("10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen)
    assert url is None


def test_fetch_published_pdf_reads_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "example.com/paper.pdf" in str(request.url)
        return httpx.Response(200, content=b"%PDF published")

    _mock_httpx_client(monkeypatch, handler)
    data = fetch_published_pdf("https://example.com/paper.pdf")
    assert data == b"%PDF published"


def test_fetch_published_pdf_wraps_errors(tmp_path: Path) -> None:
    def fake_urlopen(request: object, timeout: float = 30.0) -> None:
        raise OSError("offline")

    with pytest.raises(PublishedPdfFetchError, match="Failed to download"):
        fetch_published_pdf("https://example.com/paper.pdf", urlopen=fake_urlopen)


def test_download_published_material_writes_pdf_and_manifest(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    def url_resolver(doi: str) -> str | None:
        return "https://example.com/paper.pdf"

    def pdf_fetcher(url: str) -> bytes:
        return b"%PDF published"

    result = download_published_material(
        store,
        "Noether1918",
        "10.1103/PhysRevLett.100.123456",
        url_resolver=url_resolver,
        pdf_fetcher=pdf_fetcher,
        fetched_date="2026-06-27",
    )

    assert result.pdf_path == tmp_path / "refs.files" / "Noether1918.published.pdf"
    assert result.doi == "10.1103/PhysRevLett.100.123456"
    assert (tmp_path / "refs.files" / "Noether1918.published.pdf").read_bytes() == b"%PDF published"

    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    row = manifest["files"]["Noether1918"]
    assert row["preprint_canonical"] is False
    assert row["published_pdf"]["source"] == "https://example.com/paper.pdf"
    assert row["published_pdf"]["fetched_date"] == "2026-06-27"
    assert row["published_pdf"]["refetchable"] is True
    assert len(row["published_pdf"]["sha256"]) == 64


def test_download_published_material_returns_none_when_no_oa(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    def url_resolver(doi: str) -> str | None:
        return None

    result = download_published_material(
        store,
        "Noether1918",
        "10.1103/PhysRevLett.100.123456",
        url_resolver=url_resolver,
    )

    assert result.pdf_path is None
    assert not (tmp_path / "refs.files" / "Noether1918.published.pdf").exists()


def test_download_published_material_gracefully_skips_html_content(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    def url_resolver(doi: str) -> str | None:
        return "https://example.com/paper.pdf"

    def pdf_fetcher(url: str) -> bytes:
        return b"<!DOCTYPE html><html><body>Not a PDF</body></html>"

    result = download_published_material(
        store,
        "Kane1998",
        "10.1038/30156",
        url_resolver=url_resolver,
        pdf_fetcher=pdf_fetcher,
    )

    assert result.pdf_path is None
    assert result.doi == "10.1038/30156"
    assert not (tmp_path / "refs.files" / "Kane1998.published.pdf").exists()


def test_download_published_material_wraps_malformed_doi(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    with pytest.raises(PublishedPdfFetchError, match="Malformed DOI"):
        download_published_material(store, "Noether1918", "not-a-doi")


def test_download_published_material_uses_institutional_fallback(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    result = download_published_material(
        store,
        "Noether1918",
        "10.5555/entitled",
        url_resolver=lambda doi: None,
        institutional_url_resolver=lambda doi: "https://publisher.example/article.pdf",
        pdf_fetcher=lambda url: b"%PDF institutionally entitled",
        access="institutional",
        fetched_date="2026-07-13",
    )

    assert result.access == "institutional"
    assert result.pdf_path == tmp_path / "refs.files" / "Noether1918.published.pdf"
    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    record = manifest["files"]["Noether1918"]["published_pdf"]
    assert record["access"] == "institutional"
    assert "cookie" not in record


def test_download_published_material_reports_authentication_html(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    result = download_published_material(
        store,
        "Noether1918",
        "10.5555/entitled",
        url_resolver=lambda doi: None,
        institutional_url_resolver=lambda doi: "https://publisher.example/article.pdf",
        pdf_fetcher=lambda url: b"<!doctype html><html>Sign in</html>",
        access="institutional",
    )

    assert result.pdf_path is None
    assert result.reason is not None
    assert "authentication required" in result.reason


def test_download_published_material_reports_rejected_institutional_access(
    tmp_path: Path,
) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    def rejected(url: str) -> bytes:
        raise PublishedPdfFetchError("Server returned HTTP 403 for publisher PDF")

    result = download_published_material(
        store,
        "Noether1918",
        "10.5555/entitled",
        url_resolver=lambda doi: None,
        institutional_url_resolver=lambda doi: "https://publisher.example/article.pdf",
        pdf_fetcher=rejected,
        access="institutional",
    )

    assert result.pdf_path is None
    assert result.reason == "institutional access was not accepted by the publisher"


def test_download_supplement_material_writes_one_pdf(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    result = download_supplement_material(
        store,
        "Noether1918",
        "10.5555/entitled",
        url_resolver=lambda doi: ("https://publisher.example/supplement.pdf",),
        pdf_fetcher=lambda url: b"%PDF supplement",
        access="institutional",
        fetched_date="2026-07-13",
    )

    assert result.pdf_path == tmp_path / "refs.files" / "Noether1918.supplement.pdf"
    assert result.access == "institutional"
    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    assert manifest["files"]["Noether1918"]["supplement_pdf"]["access"] == "institutional"


def test_download_supplement_material_does_not_choose_between_multiple_files(
    tmp_path: Path,
) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    result = download_supplement_material(
        store,
        "Noether1918",
        "10.5555/entitled",
        url_resolver=lambda doi: (
            "https://publisher.example/supplement-a.pdf",
            "https://publisher.example/supplement-b.pdf",
        ),
    )

    assert result.pdf_path is None
    assert result.candidates == 2
    assert result.reason is not None
    assert "multiple supplementary files" in result.reason
    assert not (tmp_path / "refs.files" / "Noether1918.supplement.pdf").exists()


def _tar_bytes(files: dict[str, bytes], *, symlinks: dict[str, str] | None = None) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
        for name, target in (symlinks or {}).items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return buffer.getvalue()


def _gzip_bytes(payload: bytes, *, name: bytes | None, extra: bytes = b"") -> bytes:
    """Build a gzip member by hand so the header can record any name (RFC 1952)."""
    flags = (0x04 if extra else 0) | (0x08 if name is not None else 0)
    header = b"\x1f\x8b\x08" + bytes([flags]) + b"\0\0\0\0\x00\x03"
    if extra:
        header += len(extra).to_bytes(2, "little") + extra
    if name is not None:
        header += name + b"\0"
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = compressor.compress(payload) + compressor.flush()
    trailer = zlib.crc32(payload).to_bytes(4, "little") + len(payload).to_bytes(4, "little")
    return header + body + trailer


# --- human-readable fetch report wording ------------------------------------


def test_dry_run_lines_say_what_would_happen_rather_than_skipped() -> None:
    # "Skipped X (would fetch)" makes two contradictory claims at once; over a
    # long queue it is unskimmable.
    from pynakes.cli_commands._fetch_report import fetch_report_lines

    report = {
        "fetched": [],
        "skipped": [
            {"key": "Euler_1748_Introductio", "reason": "would fetch"},
            {"key": "Gauss_1801_Disquisitiones", "reason": "no DOI"},
        ],
        "failed": [],
    }

    lines = fetch_report_lines(report)

    assert lines[0] == "Would fetch Euler_1748_Introductio."
    # A genuine no-action case keeps its "Skipped" wording.
    assert lines[1] == "Skipped Gauss_1801_Disquisitiones (no DOI)."


# --- regressions: a source bundle cannot unpack without bound ---------------


def test_tar_source_over_the_size_limit_is_refused_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pynakes.fetch.MAX_SOURCE_BYTES", 1024)
    target = tmp_path / "src"

    with pytest.raises(ArxivFetchError, match="unpacks to more than"):
        extract_arxiv_source(_tar_bytes({"main.tex": b"x" * 4096}), target)

    assert list(target.iterdir()) == []


def test_tar_source_with_too_many_members_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pynakes.fetch.MAX_SOURCE_MEMBERS", 3)
    files = {f"part{i}.tex": b"x" for i in range(5)}

    with pytest.raises(ArxivFetchError, match="members"):
        extract_arxiv_source(_tar_bytes(files), tmp_path / "src")


def test_single_file_source_over_the_size_limit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pynakes.fetch.MAX_SOURCE_BYTES", 1024)
    target = tmp_path / "src"

    with pytest.raises(ArxivFetchError, match="unpacks to more than"):
        extract_arxiv_source(_gzip_bytes(b"x" * (4 << 20), name=b"noether.tex"), target)

    assert list(target.iterdir()) == []


def test_truncated_single_file_source_is_an_arxiv_error(tmp_path: Path) -> None:
    data = _gzip_bytes(b"\\documentclass{article}\n" * 400, name=b"noether.tex")

    with pytest.raises(ArxivFetchError):
        extract_arxiv_source(data[: len(data) // 2], tmp_path / "src")
