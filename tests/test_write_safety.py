"""Writes keep what the user set up at the destination.

A replace-by-rename write must not turn a symlinked library into a regular file,
reset its permissions to the temporary file's 0600, or overwrite a file the user
made read-only.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

from pynakes.engine import Bibliography
from pynakes.io import save_text

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions and symlinks")

LIBRARY = "@article{Euler1748,\n  title = {Introductio}\n}\n"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("mode", [0o644, 0o664, 0o600])
def test_save_keeps_the_destination_mode(tmp_path: Path, mode: int) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY)
    bib.chmod(mode)

    assert save_text(LIBRARY + "\n", str(bib)).success

    assert _mode(bib) == mode


def test_save_gives_a_new_file_the_umask_default(tmp_path: Path) -> None:
    bib = tmp_path / "new.bib"
    umask = os.umask(0o022)
    try:
        assert save_text(LIBRARY, str(bib)).success
    finally:
        os.umask(umask)

    assert _mode(bib) == 0o644


def test_save_writes_through_a_symlink_to_its_target(tmp_path: Path) -> None:
    real = tmp_path / "shared" / "refs.bib"
    real.parent.mkdir()
    real.write_text(LIBRARY)
    link = tmp_path / "refs.bib"
    link.symlink_to(real)

    coll = Bibliography.open(link)
    coll.add_entry("book", "Gauss1801", {"title": "Disquisitiones"})
    coll.commit()

    assert link.is_symlink()
    assert "Gauss1801" in real.read_text()


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores modes")
def test_save_refuses_a_read_only_file(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY)
    bib.chmod(0o444)

    result = save_text("@misc{Other,}\n", str(bib))

    assert not result.success
    assert "read-only" in (result.error or "")
    assert bib.read_text() == LIBRARY


def test_backup_keeps_the_source_mode(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(LIBRARY)
    bib.chmod(0o644)

    result = save_text(LIBRARY + "\n", str(bib), backup=True)

    assert result.backup_path is not None
    assert _mode(Path(result.backup_path)) == 0o644
