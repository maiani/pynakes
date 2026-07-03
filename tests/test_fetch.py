"""arXiv material download core tests."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from pynakes.fetch import (
    ArxivFetchError,
    ArxivSourceUnavailableError,
    PublishedPdfFetchError,
    download_arxiv_materials,
    download_published_material,
    extract_arxiv_source,
    fetch_arxiv_pdf,
    fetch_published_pdf,
    openalex_oa_pdf_url,
)
from pynakes.filestore import FileStore


def _mock_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("pynakes.providers._http.httpx.Client", MockClient)


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
        "pdf_path": str(tmp_path / "refs.files" / "Noether1918_preprint.pdf"),
        "source_path": str(tmp_path / "refs.files" / "Noether1918_preprint"),
    }
    assert (tmp_path / "refs.files" / "Noether1918_preprint.pdf").read_bytes() == (b"%PDF preprint")
    assert (tmp_path / "refs.files" / "Noether1918_preprint" / "paper.tex").read_bytes() == (
        b"\\title{Fixture}\n"
    )
    assert (
        tmp_path / "refs.files" / "Noether1918_preprint" / "src" / "notes.txt"
    ).read_bytes() == (b"notes\n")
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

    assert result.pdf_path == tmp_path / "refs.files" / "Noether1918_preprint.pdf"
    assert result.source_path is None
    assert result.source_unavailable is True
    assert (tmp_path / "refs.files" / "Noether1918_preprint.pdf").read_bytes() == b"%PDF preprint"
    assert not (tmp_path / "refs.files" / "Noether1918_preprint").exists()

    manifest = json.loads((tmp_path / "refs.files" / ".pinax" / "manifest.json").read_text())
    row = manifest["files"]["Noether1918"]
    assert "preprint_pdf" in row
    assert "preprint_source" not in row


def test_failed_source_download_leaves_existing_source_tree(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    existing = root / "Noether1918_preprint"
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
    cache_dir = tmp_path / "cache"
    calls: list[int] = []

    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        calls.append(1)
        return _FakeResponse(_OPENALEX_WITH_OA)

    url1 = openalex_oa_pdf_url(
        "10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen, cache_dir=cache_dir
    )
    assert url1 == "https://example.com/paper.pdf"
    assert len(calls) == 1

    url2 = openalex_oa_pdf_url(
        "10.1103/PhysRevLett.100.123456", urlopen=fake_urlopen, cache_dir=cache_dir
    )
    assert url2 == "https://example.com/paper.pdf"
    assert len(calls) == 1  # served from cache, no second call


def test_openalex_oa_pdf_url_does_not_cache_invalid_json(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"

    def fake_urlopen(request: object, timeout: float = 30.0) -> _FakeResponse:
        return _FakeResponse(b"<html>not json</html>")

    with pytest.raises(PublishedPdfFetchError, match="invalid JSON"):
        openalex_oa_pdf_url(
            "10.1103/PhysRevLett.100.123456",
            urlopen=fake_urlopen,
            cache_dir=cache_dir,
        )

    assert not list(cache_dir.rglob("*.json"))


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

    assert result.pdf_path == tmp_path / "refs.files" / "Noether1918.pdf"
    assert result.doi == "10.1103/PhysRevLett.100.123456"
    assert (tmp_path / "refs.files" / "Noether1918.pdf").read_bytes() == b"%PDF published"

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
    assert not (tmp_path / "refs.files" / "Noether1918.pdf").exists()


def test_download_published_material_wraps_malformed_doi(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    with pytest.raises(PublishedPdfFetchError, match="Malformed DOI"):
        download_published_material(store, "Noether1918", "not-a-doi")


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
