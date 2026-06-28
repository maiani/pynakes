"""arXiv material download core tests."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

from pynakes.fetch import (
    ArxivFetchError,
    arxiv_pdf_url,
    arxiv_source_url,
    download_arxiv_materials,
    extract_arxiv_source,
    fetch_arxiv_pdf,
)
from pynakes.filestore import FileStore


def test_arxiv_material_urls_normalize_identifiers() -> None:
    assert arxiv_pdf_url("https://arxiv.org/pdf/2101.00001v2.pdf") == (
        "https://arxiv.org/pdf/2101.00001"
    )
    assert arxiv_source_url("arXiv:hep-th/9901001v3") == (
        "https://arxiv.org/e-print/hep-th/9901001"
    )


def test_fetch_arxiv_pdf_reads_bytes_with_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Request] = []

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"%PDF fixture"

    def fake_urlopen(request: Request, timeout: float) -> Response:
        seen.append(request)
        assert timeout == 30.0
        return Response()

    monkeypatch.setattr("pynakes.importer.urlopen", fake_urlopen)

    data = fetch_arxiv_pdf("2101.00001v2")

    assert data == b"%PDF fixture"
    assert seen[0].full_url == "https://arxiv.org/pdf/2101.00001"
    assert seen[0].headers["User-agent"].startswith("pynakes/")


def test_fetch_arxiv_pdf_wraps_url_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Request, timeout: float) -> None:
        raise URLError("offline")

    monkeypatch.setattr("pynakes.importer.urlopen", fake_urlopen)

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
