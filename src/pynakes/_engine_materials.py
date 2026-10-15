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

from pynakes._engine_fetch import build_fetch_queue, run_fetch_loop
from pynakes._engine_helpers import metadata_fetch_policy
from pynakes.fetch_progress import WOULD_FETCH, FetchProgress
from pynakes.filestore import FILES_DIR_KEY
from pynakes.metadata import FetchPolicy, library_dialect, metadata_bool, metadata_value

if TYPE_CHECKING:
    from pynakes import metadata as metadata_ops
    from pynakes._fetch_discovery import ArxivDiscovery
    from pynakes.filestore import FileStore
    from pynakes.model import BibEntry, BibFile
    from pynakes.providers.repositories.arxiv import ArxivRecord


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
        access: str | None = None,
        keys: Collection[str] | None = None,
        discover: bool | None = None,
        arxiv_lookup: Callable[[str], str | None] | None = None,
        arxiv_record_fetcher: Callable[[str], "ArxivRecord"] | None = None,
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
            access: Published-material access mode: ``open`` or ``institutional``;
                ``None`` reads the library's ``pinax-fetch-access`` (default ``open``).
            keys: Citation keys to fetch for, in place of ``target``; ``None`` for all.
            discover: Look up a missing arXiv id by DOI when a preprint is needed,
                check it against arXiv's record, and write a confirmed one to
                the entry (``eprint`` and its archive field, only when empty).
                ``None`` reads the library's ``pinax-discover-arxiv`` (default off).
            arxiv_lookup: Injectable DOI-to-arXiv-id lookup for testing.
            arxiv_record_fetcher: Injectable arXiv record fetcher for testing.

        Returns:
            A dict with ``fetched``, ``skipped``, ``failed`` lists, plus
            ``fetch_policy`` dict reflecting the resolved Pinax fetch policy,
            ``access``, a ``summary`` of counts (``requested`` entries, items
            ``fetched``, skips split into ``already_present``, ``unavailable``
            and dry-run ``planned``, and ``failed``), and ``warnings``: one
            ``download_failed`` object per failed download. A skipped or failed
            item for which a download was tried lists the requests in
            ``attempts``. ``coverage`` says whether the PDFs the policy asks
            for are now present: ``entries``, ``with_pdf``, ``without_pdf``,
            ``missing`` (each entry still lacking one, with the reason this
            run recorded) and ``complete``. ``discovered`` lists each arXiv-id
            lookup ``discover`` made and its outcome.
        """
        if access is None:
            access = (metadata_value(self.lib, "pinax-fetch-access") or "open").strip().lower()
        if discover is None:
            discover = metadata_bool(metadata_value(self.lib, "pinax-discover-arxiv"), False)
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
        run = run_fetch_loop(
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
            discover=self._arxiv_discoverer(cache_file, arxiv_lookup, arxiv_record_fetcher)
            if discover
            else None,
            dialect=library_dialect(self.lib),
        )
        if bootstrapped and not _anything_landed(run.fetched, run.skipped, dry_run):
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
            "fetched": run.fetched,
            "skipped": run.skipped,
            "failed": run.failed,
            "summary": run.summary(),
            "coverage": run.coverage(entry_queue, store, resolved),
            "discovered": run.discovered,
            "warnings": run.warnings,
        }

    @staticmethod
    def _arxiv_discoverer(
        cache_file: str | Path | None,
        lookup: Callable[[str], str | None] | None,
        record_fetcher: Callable[[str], "ArxivRecord"] | None,
    ) -> Callable[["BibEntry", str], "ArxivDiscovery"]:
        """Bind the arXiv-id lookup and its check to this run's providers."""
        from pynakes._fetch_discovery import discover_arxiv_id
        from pynakes.providers.identity import resolve_arxiv_id_for_doi
        from pynakes.providers.repositories import arxiv as arxiv_provider

        def default_lookup(doi: str) -> str | None:
            return resolve_arxiv_id_for_doi(doi, cache_file=cache_file)

        def discover(entry: "BibEntry", doi: str) -> "ArxivDiscovery":
            return discover_arxiv_id(
                entry,
                doi,
                lookup=lookup or default_lookup,
                record_fetcher=record_fetcher or arxiv_provider.fetch_record,
            )

        return discover
