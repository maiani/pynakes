"""Atomic writes reach the disk before and after the rename.

Each atomic writer syncs its temporary file before renaming it over the
destination, so a crash cannot leave the new name pointing at data still in the
page cache, and on POSIX syncs the directory afterwards, so the rename itself
survives. Windows has no directory sync, and a directory sync the filesystem
refuses does not fail a write that has already happened.
"""

import os
import stat
from pathlib import Path

import pytest

from pynakes import _atomic
from pynakes._filestore_atomic import _atomic_write_bytes
from pynakes.io import save_text
from pynakes.provider_cache import _atomic_write_text


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record file syncs, directory syncs, and renames, in order."""
    log: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        log.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        real_fsync(fd)

    def replace(src, dst) -> None:
        log.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    return log


def test_save_text_syncs_the_file_then_the_directory(tmp_path: Path, events: list[str]) -> None:
    path = tmp_path / "refs.bib"
    path.write_text("@book{Newton1687}\n")
    assert save_text("@book{Euler1748}\n", str(path), backup=False).success
    assert events == ["file", "replace", "dir"]
    assert path.read_text() == "@book{Euler1748}\n"


def test_the_staged_backup_is_synced_too(tmp_path: Path, events: list[str]) -> None:
    path = tmp_path / "refs.bib"
    path.write_text("@book{Newton1687}\n")
    assert save_text("@book{Euler1748}\n", str(path), backup=True).success
    assert events == ["file", "file", "replace", "dir", "replace", "dir"]
    assert (tmp_path / "refs.bib.bak").read_text() == "@book{Newton1687}\n"


def test_a_non_atomic_write_is_synced(tmp_path: Path, events: list[str]) -> None:
    path = tmp_path / "refs.bib"
    assert save_text("@book{Euler1748}\n", str(path), backup=False, atomic=False).success
    assert events == ["file"]


def test_the_provider_cache_and_material_store_sync(tmp_path: Path, events: list[str]) -> None:
    _atomic_write_text(tmp_path / "cache.jsonl", "{}\n")
    _atomic_write_bytes(tmp_path / "Newton1687.pdf", b"%PDF", tmp_path)
    assert events == ["file", "replace", "dir"] * 2


def test_windows_skips_the_directory_sync(
    tmp_path: Path, events: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_atomic.sys, "platform", "win32")
    assert save_text("@book{Euler1748}\n", str(tmp_path / "refs.bib"), backup=False).success
    assert events == ["file", "replace"]


def test_a_refused_directory_sync_does_not_fail_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = os.fsync

    def fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(22, "Invalid argument")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    path = tmp_path / "refs.bib"
    assert save_text("@book{Euler1748}\n", str(path), backup=False).success
    assert path.read_text() == "@book{Euler1748}\n"


def test_a_failed_file_sync_fails_the_write_and_keeps_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fsync(fd: int) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(os, "fsync", fsync)
    path = tmp_path / "refs.bib"
    path.write_text("@book{Newton1687}\n")
    result = save_text("@book{Euler1748}\n", str(path), backup=False)
    assert not result.success
    assert "Input/output error" in (result.error or "")
    assert path.read_text() == "@book{Newton1687}\n"
    assert [p.name for p in tmp_path.iterdir()] == ["refs.bib"]


def test_source_tree_is_synced_before_install(tmp_path: Path, events: list[str]) -> None:
    from pynakes._filestore_atomic import _atomic_replace_dir

    source = tmp_path / "source"
    source.mkdir()
    (source / "main.tex").write_text("Principia", encoding="utf-8")
    target = tmp_path / "installed"
    _atomic_replace_dir(source, target, tmp_path)
    assert "file" in events
    assert events.index("file") < events.index("replace")
    assert (target / "main.tex").read_text(encoding="utf-8") == "Principia"


def test_manifest_backup_is_synced_before_replacement(tmp_path: Path, events: list[str]) -> None:
    from pynakes.filestore import FileStore

    store = FileStore(tmp_path / "files", tmp_path / "refs.bib")
    manifest = {"version": 1, "files": {}}
    store.write_manifest(manifest)
    before = store.manifest_path.read_bytes()
    events.clear()
    store.write_manifest(manifest, backup=True)
    assert events.count("file") == 2
    assert events.index("file") < events.index("replace")
    assert Path(str(store.manifest_path) + ".bak").read_bytes() == before
