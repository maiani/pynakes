"""Compatibility imports for the read-only local Zotero backend.

The implementation lives in :mod:`pynakes.library.backends.zotero`. Existing
``from pynakes.zotero import ZoteroLibraryBackend`` imports remain supported.
"""

from pynakes.library.backends.zotero import CollectionRef, MaterialRef, ZoteroLibraryBackend

__all__ = ["CollectionRef", "MaterialRef", "ZoteroLibraryBackend"]
