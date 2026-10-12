"""Pinax material-fetch mixin for :class:`~pynakes.engine.Bibliography`.

``ensure_files_dir`` and ``fetch_materials``, split out of
:mod:`pynakes._engine_ops`. The per-entry work lives in
:mod:`pynakes._engine_fetch`. Do not import this module directly; use
``pynakes.engine``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes._engine_helpers import (
    build_fetch_queue,
    metadata_fetch_policy,
    run_fetch_loop,
)
from pynakes.fetch_progress import WOULD_FETCH, FetchProgress
from pynakes.filestore import FILES_DIR_KEY
from pynakes.metadata import FetchPolicy

if TYPE_CHECKING:
    from pynakes import metadata as metadata_ops
    from pynakes.filestore import FileStore
    from pynakes.model import BibFile


def _anything_landed(fetched: list[dict], skipped: list[dict], dry_run: bool) -> bool:
    """Whether a fetch wrote a material, or — for a dry run — would write one."""
    if dry_run:
        return any(item.get("reason") == WOULD_FETCH for item in skipped)
    return bool(fetched)


def _remove_empty_tree(root: Path) -> None:
    """Remove *root* and its subdirectories, but only while they hold no file.

    A fetch that wrote nothing may still have created the store directory and
    its bookkeeping folders; those go, and a directory holding any file stays.
    """
    if not root.is_dir() or root.is_symlink():
        return
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            return
    try:
        root.rmdir()
    except OSError:
        return


class BibliographyMaterials:
    """Mixin providing Pinax material fetching for :class:`~pynakes.engine.Bibliography`.

    Consumers must not instantiate this class directly.
    """

    if TYPE_CHECKING:
        # Provided by the concrete ``Bibliography`` dataclass and the operations mixin.
        lib: BibFile
        path: Path | None

        @property
        def files(self) -> FileStore | None: ...
        def set_metadata(
            self, key: str, value: str, *, namespace: str | None = None
        ) -> metadata_ops.MetadataUpdate: ...
        def remove_metadata(
            self, key: str, *, namespace: str | None = None
        ) -> metadata_ops.MetadataUpdate | None: ...

    def ensure_files_dir(self) -> bool:
        """Bootstrap ``pinax-files-dir`` metadata if not already configured.

        Returns True if metadata was set (bibliography marked dirty), False if
        ``pinax-files-dir`` was already present.
        """
        for name in self.lib.metadata:
            if name.strip().lower() == FILES_DIR_KEY:
                return False
        if self.path is None:
            raise ValueError("ensure_files_dir requires a bound path")
        default = f"{self.path.stem}.files"
        self.set_metadata(FILES_DIR_KEY, default)
        return True

    def fetch_materials(
        self,
        target: str | None = None,
        *,
        policy: FetchPolicy | None = None,
        dry_run: bool = False,
        pdf_fetcher: Callable[[str], bytes] | None = None,
        source_fetcher: Callable[[str], bytes] | None = None,
        published_url_fetcher: Callable[[str], str | None] | None = None,
        institutional_url_fetcher: Callable[[str], str | None] | None = None,
        published_pdf_fetcher: Callable[[str], bytes] | None = None,
        supplement_url_fetcher: Callable[[str], tuple[str, ...]] | None = None,
        supplement_pdf_fetcher: Callable[[str], bytes] | None = None,
        cache_file: str | Path | None = None,
        progress: FetchProgress | None = None,
        access: str = "open",
        keys: Collection[str] | None = None,
    ) -> dict:
        """Download selected arXiv, published, and supplementary materials for entries.

        Args:
            target: Optional single citation key to fetch. If None, fetch all.
            policy: Optional explicit fetch policy. When provided, overrides the
                library's metadata ``pinax-fetch-policy`` setting.
            dry_run: If True, report what would be fetched without downloading.
            pdf_fetcher: Injectable arXiv PDF fetcher for testing.
            source_fetcher: Injectable arXiv source fetcher for testing.
            published_url_fetcher: Injectable OA PDF URL resolver for testing.
            institutional_url_fetcher: Injectable publisher PDF URL resolver.
            published_pdf_fetcher: Injectable published PDF bytes fetcher.
            supplement_url_fetcher: Injectable supplement URL resolver.
            supplement_pdf_fetcher: Injectable supplement PDF bytes fetcher.
            cache_file: Optional path to a provider-response cache file.
            progress: Optional callback receiving fetch progress events.
            access: Published-material access mode: ``open`` or ``institutional``.
            keys: Citation keys to fetch for, in place of ``target``; ``None`` for all.

        Returns:
            A dict with ``fetched``, ``skipped``, ``failed`` lists, plus
            ``fetch_policy`` dict reflecting the resolved Pinax fetch policy.
        """
        if access not in {"open", "institutional"}:
            raise ValueError(f"Unknown fetch access mode: {access!r}")
        store = self.files
        bootstrapped = False
        if store is None:
            bootstrapped = self.ensure_files_dir()
            store = self.files
            if store is None:
                raise ValueError("could not resolve pinax-files-dir after bootstrapping")

        root_existed = store.root.exists()
        if not dry_run:  # a dry run creates nothing, not even the files directory
            store.ensure_root()
        if policy is not None:
            resolved = policy
        else:
            resolved = metadata_fetch_policy(self.lib)

        entry_queue = build_fetch_queue(self.lib, target, keys)
        fetched, skipped, failed = run_fetch_loop(
            entry_queue,
            store,
            resolved,
            dry_run,
            pdf_fetcher=pdf_fetcher,
            source_fetcher=source_fetcher,
            published_url_fetcher=published_url_fetcher,
            institutional_url_fetcher=institutional_url_fetcher,
            published_pdf_fetcher=published_pdf_fetcher,
            supplement_url_fetcher=supplement_url_fetcher,
            supplement_pdf_fetcher=supplement_pdf_fetcher,
            cache_file=cache_file,
            progress=progress,
            access=access,
        )
        if bootstrapped and not _anything_landed(fetched, skipped, dry_run):
            # The store was only ever needed to hold what this run fetched;
            # with nothing fetched the library keeps no store it did not have.
            self.remove_metadata(FILES_DIR_KEY)
            if not root_existed:
                _remove_empty_tree(store.root)

        return {
            "fetch_policy": {
                "preprint": resolved.preprint,
                "published": resolved.published,
                "source": resolved.source,
                "supplement": resolved.supplement,
                "bestpdf": resolved.bestpdf,
            },
            "access": access,
            "fetched": fetched,
            "skipped": skipped,
            "failed": failed,
        }
