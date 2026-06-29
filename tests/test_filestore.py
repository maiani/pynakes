"""Pinax FileStore foundation tests."""

import json
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


def test_manifest_records_canonical_annotation_and_drift(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A_preprint.pdf").write_bytes(b"preprint")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    store.record_artifact(
        "A",
        "preprint_pdf",
        source="https://arxiv.org/pdf/2101.00001",
        fetched_date="2026-06-27",
        refetchable=True,
    )
    store.set_preprint_canonical("A", True)

    annotation = store.annotation_for("A")
    assert annotation["canonical_pdf"] == str(root / "A_preprint.pdf")
    assert annotation["preprint_canonical"] is True
    assert annotation["refetchable"] is True

    (root / "A_preprint.pdf").unlink()
    scan = store.scan(["A"])
    assert scan.drift == [{"key": "A", "kind": "preprint_pdf", "reason": "manifest without file"}]


def test_copy_materials_copies_files_and_manifest_row(tmp_path: Path) -> None:
    source_root = tmp_path / "source.files"
    source_root.mkdir()
    (source_root / "A_preprint.pdf").write_bytes(b"preprint")
    (source_root / "A_preprint").mkdir()
    (source_root / "A_preprint" / "paper.tex").write_text("\\title{A}\n")
    source = FileStore(root=source_root, bib_path=tmp_path / "source.bib")
    source.record_artifact(
        "A",
        "preprint_pdf",
        source="https://arxiv.org/pdf/2101.00001",
        fetched_date="2026-06-27",
        refetchable=True,
    )
    source.set_preprint_canonical("A", True)
    target = FileStore(root=tmp_path / "target.files", bib_path=tmp_path / "target.bib")

    copied = target.copy_materials_from(source, "A")

    assert {item["kind"] for item in copied} == {"preprint_pdf", "preprint_source"}
    assert (tmp_path / "target.files" / "A_preprint.pdf").read_bytes() == b"preprint"
    assert (tmp_path / "target.files" / "A_preprint" / "paper.tex").read_text() == "\\title{A}\n"
    manifest = json.loads((tmp_path / "target.files" / ".pinax" / "manifest.json").read_text())
    assert manifest["files"]["A"]["preprint_canonical"] is True


def test_rename_materials_moves_paths_and_manifest_with_rollback(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "Old_preprint.pdf").write_bytes(b"pdf")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")
    store.record_artifact(
        "Old",
        "preprint_pdf",
        source="https://arxiv.org/pdf/2101.00001",
        fetched_date="2026-06-27",
        refetchable=True,
    )

    transaction = store.rename_materials("Old", "New")

    assert not (root / "Old_preprint.pdf").exists()
    assert (root / "New_preprint.pdf").read_bytes() == b"pdf"
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "New" in manifest["files"]
    assert "Old" not in manifest["files"]

    transaction.rollback()

    assert (root / "Old_preprint.pdf").read_bytes() == b"pdf"
    assert not (root / "New_preprint.pdf").exists()
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "Old" in manifest["files"]


def test_merge_materials_moves_missing_kinds_and_manifest_row(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "Survivor.pdf").write_bytes(b"published")
    (root / "Duplicate_preprint.pdf").write_bytes(b"preprint")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")
    store.record_artifact(
        "Duplicate",
        "preprint_pdf",
        source="https://arxiv.org/pdf/2101.00001",
        fetched_date="2026-06-27",
        refetchable=True,
    )

    planned = store.plan_material_merge("Duplicate", "Survivor")
    transaction = store.merge_materials("Duplicate", "Survivor")

    assert planned == [
        {
            "source_key": "Duplicate",
            "target_key": "Survivor",
            "kind": "preprint_pdf",
            "source_path": str(root / "Duplicate_preprint.pdf"),
            "target_path": str(root / "Survivor_preprint.pdf"),
        }
    ]
    assert not (root / "Duplicate_preprint.pdf").exists()
    assert (root / "Survivor_preprint.pdf").read_bytes() == b"preprint"
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "Duplicate" not in manifest["files"]
    assert manifest["files"]["Survivor"]["preprint_pdf"]["refetchable"] is True

    transaction.rollback()

    assert (root / "Duplicate_preprint.pdf").read_bytes() == b"preprint"
    assert not (root / "Survivor_preprint.pdf").exists()
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "Duplicate" in manifest["files"]


def test_merge_materials_rejects_existing_target_kind(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "Survivor_preprint.pdf").write_bytes(b"target")
    (root / "Duplicate_preprint.pdf").write_bytes(b"source")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    with pytest.raises(ValueError, match="target exists"):
        store.plan_material_merge("Duplicate", "Survivor")


def test_scan_deduplicates_keys(tmp_path: Path) -> None:
    # Duplicate keys must be tolerated (invariant #5): scan silently deduplicates.
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    result = store.scan(["A", "A"])
    assert len(result.entries) == 1
    assert result.entries[0].key == "A"


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


def test_write_published_pdf_writes_atomically(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    path = store.write_published_pdf("Einstein1905", b"%PDF version of record")
    assert path == tmp_path / "refs.files" / "Einstein1905.pdf"
    assert path.read_bytes() == b"%PDF version of record"
