"""Pinax FileStore foundation tests."""

import json
import os
import sys
from pathlib import Path

import pytest

from pynakes._filestore_atomic import _process_alive, _remove_path
from pynakes.bibtex_parser import parse_bib
from pynakes.engine import Bibliography
from pynakes.filestore import FileStore, resolve_files_dir


def test_resolve_files_dir_uses_default_for_empty_value(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"

    assert resolve_files_dir("", bib) == tmp_path / "refs.files"


def test_resolve_files_dir_anchors_symlinked_bib_at_link_path(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    link_dir = tmp_path / "linked"
    real_dir.mkdir()
    link_dir.mkdir()
    real_bib = real_dir / "refs.bib"
    real_bib.write_text("@article{A, title = {T}}\n")
    link_bib = link_dir / "refs.bib"
    link_bib.symlink_to(real_bib)

    assert resolve_files_dir("", link_bib) == link_dir / "refs.files"
    assert resolve_files_dir("materials", link_bib) == link_dir / "materials"


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
    lib = parse_bib(
        "@article{A, title = {T}}\n@comment{pynakes-meta:\npinax-files-dir: materials\n}\n"
    )

    store = FileStore.from_metadata(lib, tmp_path / "refs.bib")

    assert store is not None
    assert store.root == tmp_path / "materials"


def test_paths_for_key_are_deterministic(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    paths = store.paths_for("Bohr1913")

    assert paths.published_pdf == tmp_path / "refs.files" / "Bohr1913.published.pdf"
    assert paths.preprint_pdf == tmp_path / "refs.files" / "Bohr1913.preprint.pdf"
    assert paths.preprint_source == tmp_path / "refs.files" / "Bohr1913.source"


def test_paths_for_key_rejects_path_like_keys(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    with pytest.raises(ValueError, match="cannot address Pinax materials"):
        store.paths_for("../A")


def test_presence_for_key_reads_live_filesystem(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A.published.pdf").write_text("published")
    (root / "A.preprint.pdf").write_text("preprint")
    (root / "A.source").mkdir()
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    presence = store.presence_for("A")

    assert presence.published_pdf is True
    assert presence.preprint_pdf is True
    assert presence.preprint_source is True
    assert presence.any_present is True


def test_scan_reports_entries_and_material_shaped_orphans(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A.published.pdf").write_text("known")
    (root / "Ghost.published.pdf").write_text("orphan")
    (root / "Ghost.preprint.pdf").write_text("orphan preprint")
    (root / "Ghost.source").mkdir()
    (root / "notes.txt").write_text("ignored")
    (root / ".pinax").mkdir()
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    scan = store.scan(["A"])

    assert len(scan.entries) == 1
    assert scan.entries[0].published_pdf is True
    assert [(item.key, item.kind) for item in scan.orphans] == [
        ("Ghost", "preprint_pdf"),
        ("Ghost", "published_pdf"),
        ("Ghost", "preprint_source"),
    ]


def test_manifest_records_canonical_annotation_and_drift(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A.preprint.pdf").write_bytes(b"preprint")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    store.record_artifact(
        "A",
        "preprint_pdf",
        source="https://arxiv.org/pdf/2101.00001",
        fetched_date="2026-06-27",
        refetchable=True,
    )

    annotation = store.annotation_for("A")
    assert annotation["canonical_pdf"] == str(root / "A.preprint.pdf")
    assert annotation["refetchable"] is True

    (root / "A.preprint.pdf").unlink()
    scan = store.scan(["A"])
    assert scan.drift == [{"key": "A", "kind": "preprint_pdf", "reason": "manifest without file"}]


def test_copy_materials_copies_files_and_manifest_row(tmp_path: Path) -> None:
    source_root = tmp_path / "source.files"
    source_root.mkdir()
    (source_root / "A.preprint.pdf").write_bytes(b"preprint")
    (source_root / "A.source").mkdir()
    (source_root / "A.source" / "paper.tex").write_text("\\title{A}\n")
    source = FileStore(root=source_root, bib_path=tmp_path / "source.bib")
    source.record_artifact(
        "A",
        "preprint_pdf",
        source="https://arxiv.org/pdf/2101.00001",
        fetched_date="2026-06-27",
        refetchable=True,
    )
    target = FileStore(root=tmp_path / "target.files", bib_path=tmp_path / "target.bib")

    copied = target.copy_materials_from(source, "A")

    assert {item["kind"] for item in copied} == {"preprint_pdf", "preprint_source"}
    assert (tmp_path / "target.files" / "A.preprint.pdf").read_bytes() == b"preprint"
    assert (tmp_path / "target.files" / "A.source" / "paper.tex").read_text() == "\\title{A}\n"
    manifest = json.loads((tmp_path / "target.files" / ".pinax" / "manifest.json").read_text())
    assert manifest["files"]["A"]["preprint_pdf"]["refetchable"] is True


def test_canonical_is_the_published_pdf_when_there_is_one(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A.preprint.pdf").write_bytes(b"preprint")
    (root / "A.source").mkdir()
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    preprint_only = store.annotation_for("A")
    assert preprint_only["canonical_pdf"] == str(root / "A.preprint.pdf")
    assert preprint_only["canonical_source"] == str(root / "A.source")

    (root / "A.published.pdf").write_bytes(b"published")
    both = store.annotation_for("A")
    assert both["canonical_pdf"] == str(root / "A.published.pdf")
    assert both["canonical_source"] is None
    assert "preprint_canonical" not in both


def test_copy_materials_skips_root_creation_when_entry_has_no_files(tmp_path: Path) -> None:
    source_root = tmp_path / "source.files"
    source_root.mkdir()
    source = FileStore(root=source_root, bib_path=tmp_path / "source.bib")
    # This target root is never created if nothing is copied to it, so it can
    # point anywhere (e.g. a /dev/null-style discard bucket) without failing.
    target_root = tmp_path / "no-such-parent" / "target.files"
    target = FileStore(root=target_root, bib_path=tmp_path / "target.bib")

    copied = target.copy_materials_from(source, "NoFiles")

    assert copied == []
    assert not target_root.exists()
    assert not target_root.parent.exists()


def test_copy_materials_from_same_store_is_noop(tmp_path: Path) -> None:
    # A store copying an entry's materials onto itself (e.g. a combine whose --out
    # is also an input) must be a no-op, not a shutil.SameFileError.
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "A.published.pdf").write_bytes(b"pdf")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")

    copied = store.copy_materials_from(store, "A")

    assert copied == []
    assert (root / "A.published.pdf").read_bytes() == b"pdf"


def test_rename_materials_moves_paths_and_manifest_with_rollback(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "Old.preprint.pdf").write_bytes(b"pdf")
    store = FileStore(root=root, bib_path=tmp_path / "refs.bib")
    store.record_artifact(
        "Old",
        "preprint_pdf",
        source="https://arxiv.org/pdf/2101.00001",
        fetched_date="2026-06-27",
        refetchable=True,
    )

    transaction = store.rename_materials("Old", "New")

    assert not (root / "Old.preprint.pdf").exists()
    assert (root / "New.preprint.pdf").read_bytes() == b"pdf"
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "New" in manifest["files"]
    assert "Old" not in manifest["files"]

    transaction.rollback()

    assert (root / "Old.preprint.pdf").read_bytes() == b"pdf"
    assert not (root / "New.preprint.pdf").exists()
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "Old" in manifest["files"]


def test_merge_materials_moves_missing_kinds_and_manifest_row(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "Survivor.published.pdf").write_bytes(b"published")
    (root / "Duplicate.preprint.pdf").write_bytes(b"preprint")
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
            "source_path": str(root / "Duplicate.preprint.pdf"),
            "target_path": str(root / "Survivor.preprint.pdf"),
        }
    ]
    assert not (root / "Duplicate.preprint.pdf").exists()
    assert (root / "Survivor.preprint.pdf").read_bytes() == b"preprint"
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "Duplicate" not in manifest["files"]
    assert manifest["files"]["Survivor"]["preprint_pdf"]["refetchable"] is True

    transaction.rollback()

    assert (root / "Duplicate.preprint.pdf").read_bytes() == b"preprint"
    assert not (root / "Survivor.preprint.pdf").exists()
    manifest = json.loads((root / ".pinax" / "manifest.json").read_text())
    assert "Duplicate" in manifest["files"]


def test_merge_materials_rejects_existing_target_kind(tmp_path: Path) -> None:
    root = tmp_path / "refs.files"
    root.mkdir()
    (root / "Survivor.preprint.pdf").write_bytes(b"target")
    (root / "Duplicate.preprint.pdf").write_bytes(b"source")
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
    bib.write_text("@article{A, title = {T}}\n@comment{pynakes-meta:\npinax-files-dir:\n}\n")

    coll = Bibliography.open(bib)

    assert coll.files is not None
    assert coll.files.root == tmp_path / "refs.files"


def test_bibliography_fetch_materials_uses_symlinked_bib_directory(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    link_dir = tmp_path / "linked"
    real_dir.mkdir()
    link_dir.mkdir()
    real_bib = real_dir / "refs.bib"
    real_bib.write_text(
        "@misc{Noether1918,\n"
        "  title = {A Generic Example},\n"
        "  eprint = {2101.00001},\n"
        "  archiveprefix = {arXiv}\n"
        "}\n"
        "@comment{pynakes-meta:\n"
        "pinax-files-dir: refs.files\n"
        "pinax-fetch-policy: preprint\n"
        "}\n"
    )
    link_bib = link_dir / "refs.bib"
    link_bib.symlink_to(real_bib)
    coll = Bibliography.open(link_bib)

    report = coll.fetch_materials(
        target="Noether1918",
        pdf_fetcher=lambda arxiv_id: b"%PDF preprint",
    )

    assert report["failed"] == []
    assert (link_dir / "refs.files" / "Noether1918.preprint.pdf").read_bytes() == b"%PDF preprint"
    assert not (real_dir / "refs.files" / "Noether1918.preprint.pdf").exists()


def test_bibliography_open_rejects_invalid_files_dir(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        "@article{A, title = {T}}\n@comment{pynakes-meta:\npinax-files-dir: ../outside\n}\n"
    )

    with pytest.raises(ValueError, match="must not escape"):
        Bibliography.open(bib)


def test_bibliography_set_metadata_validates_files_dir(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{A, title = {T}}\n")
    coll = Bibliography.open(bib)

    coll.set_metadata("pinax-files-dir", "materials")
    assert coll.files is not None
    assert coll.files.root == tmp_path / "materials"
    with pytest.raises(ValueError, match="must not escape"):
        coll.set_metadata("pinax-files-dir", "../outside")


def test_write_published_pdf_writes_atomically(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    path = store.write_published_pdf("Einstein1905", b"%PDF version of record")
    assert path == tmp_path / "refs.files" / "Einstein1905.published.pdf"
    assert path.read_bytes() == b"%PDF version of record"


def test_material_writes_leave_no_debris_in_the_files_directory(tmp_path: Path) -> None:
    # The user looks at the files directory. Nothing but materials belongs in it.
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    store.write_published_pdf("euclid1482elements", b"%PDF-1.4 published")
    store.write_preprint_pdf("euclid1482elements", b"%PDF-1.4 preprint")
    store.record_artifact(
        "euclid1482elements",
        "published_pdf",
        source="https://example.org/p",
        refetchable=True,
    )

    assert sorted(item.name for item in store.root.iterdir()) == [
        ".pinax",
        "euclid1482elements.preprint.pdf",
        "euclid1482elements.published.pdf",
    ]
    # The scratch directory is released once no write is in flight.
    assert not store.scratch_root.exists()


def test_failed_material_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    store.ensure_root()
    # A directory where the material file must go makes the rename fail.
    (store.root / "euclid1482elements.published.pdf").mkdir()

    with pytest.raises(OSError):
        store.write_published_pdf("euclid1482elements", b"%PDF-1.4")

    assert not store.scratch_root.exists()
    assert sorted(item.name for item in store.root.iterdir()) == [
        "euclid1482elements.published.pdf"
    ]


def test_scratch_is_swept_for_dead_processes_but_not_live_ones(tmp_path: Path) -> None:
    # An interrupted fetch cannot clean up after itself, so the next run does.
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    store.ensure_root()
    scratch_root = store.scratch_root
    scratch_root.mkdir(parents=True)
    abandoned = scratch_root / "999999999"
    abandoned.mkdir()
    (abandoned / "euclid1482elements.published.pdf.xyz.tmp").write_bytes(b"partial")
    mine = scratch_root / str(os.getpid())
    mine.mkdir()
    (mine / "in-flight.tmp").write_bytes(b"busy")

    swept = store.sweep_scratch()

    assert swept == [abandoned]
    assert not abandoned.exists()
    assert (mine / "in-flight.tmp").is_file()


def test_scratch_sweep_is_a_noop_before_any_write(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")

    assert store.sweep_scratch() == []


def test_manifest_write_stages_inside_the_pinax_directory(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    store.write_manifest({"version": 1, "files": {}})

    assert sorted(item.name for item in store.root.iterdir()) == [".pinax"]
    assert sorted(item.name for item in (store.root / ".pinax").iterdir()) == ["manifest.json"]


class TestScratchOwnership:
    """Whether scratch may be swept turns on whether its owner still runs."""

    def test_our_own_process_counts_as_alive(self) -> None:
        assert _process_alive(os.getpid()) is True

    def test_an_exited_process_counts_as_dead(self) -> None:
        assert _process_alive(999999999) is False

    def test_a_nonsense_pid_counts_as_dead(self) -> None:
        assert _process_alive(0) is False
        assert _process_alive(-1) is False

    def test_a_process_we_may_not_signal_is_left_alone(self, monkeypatch) -> None:
        # Someone else's process is not ours to clean up after, so refuse to
        # treat "permission denied" as "gone".
        def denied(pid: int, signal: int) -> None:
            raise PermissionError("not yours")

        # The POSIX probe; Windows asks OpenProcess instead of signalling.
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(os, "kill", denied)

        assert _process_alive(4242) is True


class TestScratchRemoval:
    def test_removes_a_file_a_directory_and_a_dangling_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "file.tmp"
        target.write_bytes(b"x")
        tree = tmp_path / "tree"
        (tree / "nested").mkdir(parents=True)
        (tree / "nested" / "deep.tmp").write_bytes(b"x")
        dangling = tmp_path / "dangling"
        dangling.symlink_to(tmp_path / "absent")

        for path in (target, tree, dangling):
            _remove_path(path)

        assert sorted(item.name for item in tmp_path.iterdir()) == []

    def test_an_unremovable_path_is_tolerated(self, monkeypatch, tmp_path: Path) -> None:
        # Sweeping is opportunistic: failing to reclaim scratch must never
        # abort the write that was about to happen.
        stubborn = tmp_path / "stubborn.tmp"
        stubborn.write_bytes(b"x")
        monkeypatch.setattr(
            Path, "unlink", lambda self, missing_ok=False: (_ for _ in ()).throw(OSError("busy"))
        )

        _remove_path(stubborn)

        assert stubborn.is_file()


# --- regressions: scratch and manifest never act through a symlink ---------


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("linked", [".pinax", ".pinax/tmp"])
def test_symlinked_bookkeeping_is_refused_and_its_target_left_alone(
    tmp_path: Path, linked: str
) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "thesis.tex").write_text("precious")
    (victim / "12345").mkdir()
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    link = store.root / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(victim, target_is_directory=True)

    with pytest.raises(OSError, match="symbolic link"):
        store.sweep_scratch()
    with pytest.raises(OSError, match="symbolic link"):
        store.write_manifest({"version": 1, "files": {}})

    assert sorted(p.name for p in victim.iterdir()) == ["12345", "thesis.tex"]


def test_scratch_sweep_leaves_entries_that_are_not_pid_directories(tmp_path: Path) -> None:
    store = FileStore(root=tmp_path / "refs.files", bib_path=tmp_path / "refs.bib")
    store.scratch_root.mkdir(parents=True)
    stranger = store.scratch_root / "notes.txt"
    stranger.write_text("not ours")

    assert store.sweep_scratch() == []
    assert stranger.read_text() == "not ours"


def test_windows_liveness_probe_never_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    import pynakes._filestore_atomic as atomic

    def fail_kill(*_args):
        raise AssertionError("os.kill(pid, 0) sends CTRL_C_EVENT on Windows")

    monkeypatch.setattr(atomic.sys, "platform", "win32")
    monkeypatch.setattr(atomic.os, "kill", fail_kill)
    monkeypatch.setattr(atomic, "_windows_process_alive", lambda pid: pid == 4242)

    assert _process_alive(4242) is True
    assert _process_alive(4243) is False
