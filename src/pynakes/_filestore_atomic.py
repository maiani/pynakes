"""Atomic filesystem primitives for the Pinax material store.

Split out of :mod:`pynakes.filestore` to keep that module readable. Nothing here
knows about citation keys or manifests: it moves bytes and directories into place
atomically, and reports whether scratch found on disk belongs to a process that
has since exited.
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path

_FILESYSTEM_ERRORS = (OSError, shutil.Error)


def _process_alive(pid: int) -> bool:
    """Return whether ``pid`` is a live process, assuming alive when unsure.

    A pid we cannot signal belongs to another user, so it is not ours to clean
    up after; being wrong in that direction only delays a sweep.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _remove_path(path: Path) -> None:
    """Best-effort removal of a file, directory, or symlink."""
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except _FILESYSTEM_ERRORS:
        pass


def _atomic_write_bytes(path: Path, data: bytes, root: Path) -> None:
    tmp = tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=root,
        delete=False,
    )
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            tmp.write(data)
            tmp.flush()
        tmp_path.replace(path)
    except _FILESYSTEM_ERRORS:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_replace_dir(source: Path, target: Path, root: Path) -> None:
    backup = root / f".{target.name}.old-{uuid.uuid4().hex}"
    had_target = target.exists()
    if had_target:
        target.replace(backup)
    try:
        source.replace(target)
    except _FILESYSTEM_ERRORS:
        if had_target and backup.exists() and not target.exists():
            backup.replace(target)
        raise
    else:
        if had_target:
            if backup.is_dir():
                shutil.rmtree(backup)
            else:
                backup.unlink(missing_ok=True)
