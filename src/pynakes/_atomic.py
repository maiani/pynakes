"""Keep a file's identity across a replace-by-rename write.

Writing a temporary file and renaming it over the destination means no reader
ever sees a half-written file. A bare rename also swaps out what the user set up
at the destination, though: a symlink becomes a regular file (leaving its real
target stale), and the permissions become the temporary file's 0600. The
helpers here keep both, for every writer in the package that replaces a file.
"""

import os
import stat
from pathlib import Path


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
