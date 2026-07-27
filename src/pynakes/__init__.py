"""Public Python API for pynakes.

The :class:`Bibliography` facade is the recommended entry point for applications:
it stages changes in memory, exposes previews and structured change plans, and
commits through the same validated atomic-write path as the CLI. The lower-level
model and parser/writer entry points exported here support in-memory workflows.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pynakes")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0+unknown"

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.canonical import CanonicalLayout, FormatLintError
from pynakes.engine import (
    Bibliography,
    CommitResult,
    ExternalModificationError,
    FileFingerprint,
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
    "__version__",
    "load_bib",
    "parse_bib",
    "save_bib",
    "write_bib",
]
