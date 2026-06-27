"""Pinax FileStore foundation tests."""

from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.engine import Bibliography
from pynakes.filestore import FileStore, resolve_files_dir


def test_resolve_files_dir_uses_default_for_empty_value(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"

    assert resolve_files_dir("", bib) == tmp_path / "refs.files"


def test_resolve_files_dir_accepts_relative_path_inside_bib_dir(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"

    assert resolve_files_dir("materials/papers", bib) == tmp_path / "materials" / "papers"


def test_resolve_files_dir_rejects_absolute_and_escaping_paths(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"

    with pytest.raises(ValueError, match="relative path"):
        resolve_files_dir(str(tmp_path / "elsewhere"), bib)
    with pytest.raises(ValueError, match="must not escape"):
        resolve_files_dir("../outside", bib)


def test_filestore_from_metadata_absent_for_plain_bibliography(tmp_path: Path) -> None:
    lib = parse_bib("@article{A, title = {T}}\n")

    assert FileStore.from_metadata(lib, tmp_path / "refs.bib") is None


def test_filestore_from_metadata_uses_pynakes_files_dir(tmp_path: Path) -> None:
    lib = parse_bib("@article{A, title = {T}}\n@comment{pynakes-meta:\nfiles-dir: materials\n}\n")

    store = FileStore.from_metadata(lib, tmp_path / "refs.bib")

    assert store is not None
    assert store.root == tmp_path / "materials"


def test_paths_for_key_are_deterministic(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    paths = store.paths_for("Bohr1913")

    assert paths.published_pdf == tmp_path / "refs.files" / "Bohr1913.pdf"
    assert paths.preprint_pdf == tmp_path / "refs.files" / "Bohr1913_preprint.pdf"
    assert paths.preprint_source == tmp_path / "refs.files" / "Bohr1913_preprint"


def test_paths_for_key_rejects_path_like_keys(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    with pytest.raises(ValueError, match="cannot address Pinax materials"):
        store.paths_for("../A")


def test_presence_for_key_reads_live_filesystem(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A.pdf").write_text("published")
    (root / "A_preprint.pdf").write_text("preprint")
    (root / "A_preprint").mkdir()
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    presence = store.presence_for("A")

    assert presence.published_pdf is True
    assert presence.preprint_pdf is True
    assert presence.preprint_source is True
    assert presence.any_present is True


def test_scan_reports_entries_and_material_shaped_orphans(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A.pdf").write_text("known")
    (root / "Ghost.pdf").write_text("orphan")
    (root / "Ghost_preprint.pdf").write_text("orphan preprint")
    (root / "Ghost_preprint").mkdir()
    (root / "notes.txt").write_text("ignored")
    (root / ".pinax").mkdir()
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    scan = store.scan(["A"])

    assert len(scan.entries) == 1
    assert scan.entries[0].published_pdf is True
    assert [(item.key, item.kind) for item in scan.orphans] == [
        ("Ghost", "published_pdf"),
        ("Ghost", "preprint_source"),
        ("Ghost", "preprint_pdf"),
    ]


def test_scan_rejects_duplicate_keys(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    with pytest.raises(ValueError, match="requires unique citation keys: A"):
        store.scan(["A", "A"])


def test_bibliography_open_exposes_filestore_when_files_dir_is_set(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, title = {T}}\n@comment{pynakes-meta:\nfiles-dir:\n}\n")

    coll = Bibliography.open(bib)

    assert coll.files is not None
    assert coll.files.root == tmp_path / "refs.files"


def test_bibliography_open_rejects_invalid_files_dir(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, title = {T}}\n@comment{pynakes-meta:\nfiles-dir: ../outside\n}\n")

    with pytest.raises(ValueError, match="must not escape"):
        Bibliography.open(bib)


def test_bibliography_set_metadata_validates_files_dir(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, title = {T}}\n")
    coll = Bibliography.open(bib)

    coll.set_metadata("files-dir", "materials")
    assert coll.files is not None
    assert coll.files.root == tmp_path / "materials"
    with pytest.raises(ValueError, match="must not escape"):
        coll.set_metadata("files-dir", "../outside")
