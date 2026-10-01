"""Keep a file's identity across a replace-by-rename write.

Writing a temporary file and renaming it over the destination means no reader
ever sees a half-written file. A bare rename also swaps out what the user set up
at the destination, though: a symlink becomes a regular file (leaving its real
target stale), and the permissions become the temporary file's 0600. The
helpers here keep both, for every writer in the package that replaces a file.

On Windows the rename itself can fail for a moment: while JabRef, an editor, a
backup tool, or antivirus holds the destination open, ``os.replace`` raises
``PermissionError``. :func:`replace_file` retries that briefly before giving up.
"""

import os
import stat
import sys
import time
from pathlib import Path

# Pauses between rename attempts on Windows, about 1.5 s in all: long enough to
# outlast a scanner or an editor's save, short enough not to hang a command.
_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


def replacement_target(path: Path) -> Path:
    """Return the file a write to ``path`` replaces: a symlink's final target."""
    return Path(os.path.realpath(path)) if path.is_symlink() else path


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


def replace_file(source: Path, target: Path) -> None:
    """Rename ``source`` over ``target``, retrying while Windows holds it open.

    Elsewhere a ``PermissionError`` is a real refusal and is raised at once.
    """
    for delay in _REPLACE_RETRY_DELAYS:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if sys.platform != "win32":
                raise
            time.sleep(delay)
    os.replace(source, target)
