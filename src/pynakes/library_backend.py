"""Compatibility imports for Library reads.

Contracts live in :mod:`pynakes.library.backends.base`; the native adapter lives
in :mod:`pynakes.library.backends.bibtex`. Existing public imports remain valid.
"""

from pynakes.library.backends.base import (
    ItemRef,
    LibraryBackend,
    ReadPage,
    ReferenceView,
    Revision,
    SourceChanged,
    SourceError,
    SourceMissing,
    SourceUnavailable,
    SourceUnsupported,
    search_page,
)
from pynakes.library.backends.bibtex import BibTeXLibraryBackend

__all__ = [
    "BibTeXLibraryBackend",
    "ItemRef",
    "LibraryBackend",
    "ReadPage",
    "ReferenceView",
    "Revision",
    "SourceChanged",
    "SourceError",
    "SourceMissing",
    "SourceUnavailable",
    "SourceUnsupported",
    "search_page",
]
