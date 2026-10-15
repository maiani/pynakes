"""Public Python API for pynakes.

The :class:`Bibliography` facade is the recommended entry point for applications:
it stages changes in memory, exposes previews and structured change plans, and
commits through the same validated atomic-write path as the CLI. The lower-level
model and parser/writer entry points exported here support in-memory workflows.
"""

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.canonical import CanonicalLayout, FormatLintError
from pynakes.engine import (
    Bibliography,
    CommitResult,
    ExternalModificationError,
    FileFingerprint,
)
from pynakes.identity import (
    WorkEvidence,
    WorkIdentifier,
    WorkIdentifiers,
    WorkMatch,
    compare_work_evidence,
    evidence_from_entry,
)
from pynakes.io import SaveResult, load_bib, save_bib
from pynakes.model import BibEntry, BibFile, EntryStore, QueryFilter

__all__ = [
    "BibEntry",
    "BibFile",
    "Bibliography",
    "CanonicalLayout",
    "CommitResult",
    "EntryStore",
    "ExternalModificationError",
    "FileFingerprint",
    "FormatLintError",
    "ParseError",
    "QueryFilter",
    "SaveResult",
    "WorkEvidence",
    "WorkIdentifier",
    "WorkIdentifiers",
    "WorkMatch",
    "__version__",
    "compare_work_evidence",
    "evidence_from_entry",
    "load_bib",
    "parse_bib",
    "save_bib",
    "write_bib",
]


#: Resolved on first access by :func:`__getattr__` below.
__version__: str


def __getattr__(name: str) -> str:
    """Resolve ``__version__`` on first use.

    Reading installed metadata costs tens of milliseconds, which every command
    would otherwise pay at startup whether or not it reports a version.
    """
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            value = version("pynakes")
        except PackageNotFoundError:  # running from a source tree that isn't installed
            value = "0.0.0+unknown"
        globals()["__version__"] = value
        return value
    raise AttributeError(f"module 'pynakes' has no attribute {name!r}")
