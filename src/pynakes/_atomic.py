"""Keep a file's identity across a replace-by-rename write.

Writing a temporary file and renaming it over the destination means no reader
ever sees a half-written file. A bare rename also swaps out what the user set up
at the destination, though: a symlink becomes a regular file (leaving its real
target stale), and the permissions become the temporary file's 0600. The
helpers here keep both, for every writer in the package that replaces a file.

On Windows the rename itself can fail for a moment: while JabRef, an editor, a
backup tool, or antivirus holds the destination open, ``os.replace`` raises
``PermissionError``. :func:`replace_file` retries that briefly before giving up.

A rename is only as durable as what reaches the disk. Writers call
:func:`sync_file` on the temporary file before renaming it, so the new name
cannot end up pointing at data still in the page cache after a crash, and
:func:`replace_file` syncs the directory afterwards on POSIX, so the rename
itself survives one.
"""

import os
import stat
import sys
import time
from pathlib import Path
from typing import IO

# Pauses between rename attempts on Windows, about 1.5 s in all: long enough to
# outlast a scanner or an editor's save, short enough not to hang a command.
_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


def replacement_target(path: Path) -> Path:
    """Return the file a write to ``path`` replaces: a symlink's final target."""
    return Path(os.path.realpath(path)) if path.is_symlink() else path


def next_backup_path(path: Path) -> Path:
    """Return where a backup of ``path`` goes without replacing an earlier one.

    The first backup is ``<path>.bak``; while that exists, the lowest free
    ``<path>.bak.N`` (N = 1, 2, ...). The name depends only on what is on disk.
    """
    candidate = Path(f"{path}.bak")
    number = 0
    while os.path.lexists(candidate):
        number += 1
        candidate = Path(f"{path}.bak.{number}")
    return candidate


def _new_file_mode() -> int:
    """Return the mode an ordinary ``open(..., "w")`` would create a file with."""
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def match_mode(tmp_path: Path, target: Path) -> None:
    """Give ``tmp_path`` the permissions of ``target``, or new-file defaults."""
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = _new_file_mode()
    os.chmod(tmp_path, mode)


def sync_file(handle: IO[bytes] | IO[str]) -> None:
    """Flush ``handle`` and make the operating system write its data to disk."""
    handle.flush()
    os.fsync(handle.fileno())


def sync_directory(directory: Path) -> None:
    """Make a rename or a new name in ``directory`` durable, where possible.

    POSIX only: Windows cannot open a directory for syncing, and NTFS journals
    the rename itself. A filesystem that refuses a directory sync (some network
    and FUSE mounts do) is ignored, since the rename has already happened.
    """
    if sys.platform == "win32":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def replace_file(source: Path, target: Path) -> None:
    """Rename ``source`` over ``target``, then sync the directory holding it.

    On Windows a ``PermissionError`` is retried briefly while another program
    holds the destination open; elsewhere it is a real refusal and is raised at
    once.
    """
    for delay in _REPLACE_RETRY_DELAYS:
        try:
            os.replace(source, target)
            break
        except PermissionError:
            if sys.platform != "win32":
                raise
            time.sleep(delay)
    else:
        os.replace(source, target)
    sync_directory(target.parent)
