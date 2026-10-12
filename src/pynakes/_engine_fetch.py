"""Entry selection and the per-entry loop behind ``Bibliography.fetch_materials``.

Split out of :mod:`pynakes._engine_helpers` to keep both modules readable. Not
public API: :meth:`pynakes.engine.Bibliography.fetch_materials` is the entry
point.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pynakes.fetch_progress import WOULD_FETCH, FetchProgress, FetchProgressEvent
from pynakes.metadata import FetchPolicy
from pynakes.model import BibEntry, BibFile

if TYPE_CHECKING:
    from pynakes.fetch import FetchAccess
    from pynakes.filestore import FileStore, MaterialPresence

#: Where a skip names a missing arXiv id for an entry that has a DOI: the
#: engine's existing DOI-to-arXiv backfill. Nothing attaches one automatically.
ARXIV_LOOKUP_HINT = "`pynakes enrich --published --online` can look one up by DOI"


@dataclass
class FetchLoopResult:
    """What :func:`run_fetch_loop` did, item by item, and how each skip counts.

    ``already_present``, ``unavailable`` and ``planned`` partition ``skipped``:
    a skip because what the policy selects is already in the store, a skip
    because a requested material could not be had, and a dry run's planned
    work. ``warnings`` holds one structured warning per failed download.
    """

    entries: int = 0
    fetched: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    already_present: int = 0
    unavailable: int = 0
    planned: int = 0

    def skip(self, item: dict, kind: str) -> None:
        """Record a skipped item, counted as ``already_present``, ``unavailable`` or ``planned``."""
        self.skipped.append(item)
        setattr(self, kind, getattr(self, kind) + 1)

    def fail(self, key: str, exc: Exception, artifact: str | None = None) -> dict:
        """Record a failed download, with its requests and a warning naming it."""
        item = failure_item(key, exc, artifact)
        self.failed.append(item)
        self.warnings.append(download_warning(item))
        return item

    def summary(self) -> dict[str, int]:
        """Return the envelope's ``summary`` counts."""
        return {
            "requested": self.entries,
            "fetched": len(self.fetched),
            "already_present": self.already_present,
            "unavailable": self.unavailable,
            "failed": len(self.failed),
            "planned": self.planned,
        }


def failure_item(key: str, exc: Exception, artifact: str | None = None) -> dict:
    """Return the ``failed`` item for *exc*: the error, the artifact, and the requests made."""
    item: dict[str, object] = {"key": key, "error": str(exc)}
    named = getattr(exc, "artifact", None) or artifact
    if named:
        item["artifact"] = named
    item["attempts"] = list(getattr(exc, "attempts", ()))
    return item


def download_warning(item: dict, *, fallback: str | None = None) -> dict:
    """Return the structured warning for one failed download.

    The message is the failure's own error, so human output, which prints a
    warning only when its text is not already shown, does not repeat it.
    """
    warning: dict[str, object] = {"type": "download_failed", "key": item["key"]}
    if item.get("artifact"):
        warning["artifact"] = item["artifact"]
    message = str(item["error"])
    if fallback is not None:
        warning["fallback"] = fallback
        message = f"{item['key']}: {message}; fetched the preprint PDF instead"
    warning["message"] = message
    return warning


def build_fetch_queue(
    lib: BibFile, target: str | None, keys: Collection[str] | None = None
) -> list[BibEntry]:
    """Resolve the list of entries to fetch, raising on ambiguous keys.

    When *target* is given only that one entry is returned; with *keys*, the
    entries they name; otherwise all entries in *lib*. Either way no citation
    key in the queue may be duplicated (Pinax material addressing requires
    unique keys).
    """
    if keys is not None:
        queue = [entry for entry in lib.entries.values() if entry.key in keys]
        duplicated = sorted(
            {entry.key for entry in queue if len(lib.entries.get_all(entry.key)) > 1}
        )
        if duplicated:
            raise ValueError(
                f"Cannot fetch for duplicate key(s) {', '.join(map(repr, duplicated))}"
            )
        return queue
    if target is not None:
        entries = list(lib.entries.get_all(target))
        if not entries:
            raise ValueError(f"No entry with key {target!r} in the library")
        if len(entries) > 1:
            raise ValueError(f"Cannot fetch for duplicate key {target!r}")
        return [entries[0]]

    duplicates = lib.entries.duplicate_keys()
    if duplicates:
        instances = lib.entries.duplicate_key_instances()
        parts = []
        for key in sorted(duplicates):
            indices = instances.get(key, [])
            line_refs = f" (entry {', '.join(f'#{i}' for i in indices)})" if indices else ""
            parts.append(f"{key} ×{duplicates[key]}{line_refs}")
        raise ValueError(
            f"Pinax material addressing requires unique citation keys: {'; '.join(parts)}"
        )
    return lib.entries.values()


def run_fetch_loop(
    entry_queue: list[BibEntry],
    store: "FileStore",
    policy: FetchPolicy,
    dry_run: bool,
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
) -> FetchLoopResult:
    """Iterate *entry_queue* and download materials into *store*.

    For entries with an arXiv id, downloads the preprint PDF and/or source
    bundle. For entries with a DOI, downloads the selected published and
    supplementary PDFs as directed by *policy* and *access*.

    ``policy.bestpdf`` means "try published PDF first, fall back to preprint
    PDF when no open-access copy is available".

    Returns a :class:`FetchLoopResult`.
    """
    from pynakes.fetch import (
        ArxivFetchError,
        PublishedPdfFetchError,
        SupplementPdfFetchError,
        download_arxiv_materials,
        download_published_material,
        download_supplement_material,
    )
    from pynakes.identity import entry_arxiv_id

    run = FetchLoopResult(entries=len(entry_queue))
    fetched, skipped = run.fetched, run.skipped
    # ``Bibliography.fetch_materials`` has already rejected any other value.
    fetch_access = cast("FetchAccess", access)

    entry_total = len(entry_queue)
    for index, entry in enumerate(entry_queue, start=1):
        if not entry.key.strip():
            run.skip({"key": entry.key, "reason": "empty key"}, "unavailable")
            _emit_fetch_progress(
                progress,
                FetchProgressEvent(
                    kind="skip",
                    key=entry.key,
                    entry_index=index,
                    entry_total=entry_total,
                    message="empty key",
                ),
            )
            continue

        key = entry.key
        _emit_fetch_progress(
            progress,
            FetchProgressEvent(kind="entry", key=key, entry_index=index, entry_total=entry_total),
        )
        arxiv_id = entry_arxiv_id(entry)
        doi = entry.fields.get("doi", "").strip()
        presence = store.presence_for(key)

        can_fetch_preprint = bool(arxiv_id) and policy.preprint and not presence.preprint_pdf
        can_fetch_source = bool(arxiv_id) and policy.source and not presence.preprint_source
        can_fetch_published = bool(doi) and policy.published and not presence.published_pdf
        can_fetch_supplement = bool(doi) and policy.supplement and not presence.supplement_pdf

        # bestpdf: fetch published if OA, otherwise fall back to preprint.
        if policy.bestpdf and not policy.preprint and not policy.published:
            can_fetch_published = bool(doi) and not presence.published_pdf
            can_fetch_preprint = (
                bool(arxiv_id) and not presence.preprint_pdf and not can_fetch_published
            )

        anything_to_fetch = (
            can_fetch_preprint or can_fetch_source or can_fetch_published or can_fetch_supplement
        )

        if not anything_to_fetch:
            wants_arxiv = policy.preprint or policy.source or policy.bestpdf
            wants_doi = policy.published or policy.supplement or policy.bestpdf
            missing_arxiv = wants_arxiv and arxiv_id is None
            missing_doi = wants_doi and not doi
            # An identifier the policy uses is there, so what it can fetch is
            # already present: say so first. "no DOI" alone read as though
            # nothing had been checked for an arXiv entry with its PDF in place.
            usable = (wants_arxiv and arxiv_id is not None) or (wants_doi and bool(doi))
            # What is present counts as complete unless the policy names the
            # missing material itself; best-pdf is satisfied by either PDF.
            kind = "unavailable"
            hint = f"; {ARXIV_LOOKUP_HINT}" if doi else ""
            if missing_arxiv and missing_doi:
                reason = "no arXiv id and no DOI"
            elif usable and missing_doi:
                reason = "materials already present (no DOI for a published version)"
                if not (policy.published or policy.supplement):
                    kind = "already_present"
            elif usable and missing_arxiv:
                if policy.preprint or policy.source:
                    reason = f"materials already present (no arXiv id for a preprint{hint})"
                else:
                    reason = "materials already present (no arXiv id for a preprint)"
                    kind = "already_present"
            elif missing_arxiv:
                # The backfill looks an arXiv id up by DOI, so name it when
                # there is a DOI to look one up by.
                reason = f"no arXiv id ({ARXIV_LOOKUP_HINT})" if doi else "no arXiv id"
            elif missing_doi:
                reason = "no DOI"
            else:
                reason = "materials already present"
                kind = "already_present"
            run.skip({"key": key, "reason": reason}, kind)
            _emit_fetch_progress(
                progress,
                FetchProgressEvent(
                    kind="skip",
                    key=key,
                    entry_index=index,
                    entry_total=entry_total,
                    message=skipped[-1]["reason"],
                ),
            )
            continue

        # --- Determine fetch order for bestpdf ---
        fetch_published_now = can_fetch_published
        fetch_preprint_now = can_fetch_preprint

        if policy.bestpdf:
            # Published PDF is preferred over preprint.
            if can_fetch_published:
                fetch_preprint_now = False
            elif can_fetch_preprint:
                fetch_published_now = False

        if dry_run:
            planned = _planned_artifacts(
                presence,
                arxiv_id=arxiv_id,
                doi=doi,
                published=fetch_published_now,
                preprint=fetch_preprint_now,
                preprint_fallback=(
                    policy.bestpdf
                    and fetch_published_now
                    and not presence.preprint_pdf
                    and arxiv_id is not None
                ),
                source=can_fetch_source,
                supplement=can_fetch_supplement,
            )
            run.skip({"key": key, "reason": WOULD_FETCH, "planned": planned}, "planned")
            _emit_fetch_progress(
                progress,
                FetchProgressEvent(
                    kind="skip",
                    key=key,
                    entry_index=index,
                    entry_total=entry_total,
                    message=WOULD_FETCH,
                ),
            )
            continue

        # --- Fetch arXiv preprint materials ---
        if fetch_preprint_now or can_fetch_source:
            assert arxiv_id is not None  # both are only planned for an arXiv entry
            try:
                result = download_arxiv_materials(
                    store,
                    key,
                    arxiv_id,
                    pdf=fetch_preprint_now,
                    source=can_fetch_source,
                    pdf_fetcher=pdf_fetcher,
                    source_fetcher=source_fetcher,
                    progress=progress,
                )
                if result.pdf_path is not None or result.source_path is not None:
                    fetched.append(result.to_dict())
                if result.source_unavailable:
                    run.skip(
                        {
                            "key": key,
                            "artifact": "preprint_source",
                            "reason": "no arXiv source archive (PDF-only submission)",
                        },
                        "unavailable",
                    )
            except ArxivFetchError as exc:
                if exc.partial is not None:
                    # The preprint PDF landed before the source failed.
                    fetched.append(exc.partial.to_dict())
                run.fail(key, exc)
                _emit_fail(progress, key, index, entry_total, exc)

        # --- Fetch published PDF ---
        if fetch_published_now:
            pub_result = None
            pub_error: PublishedPdfFetchError | None = None
            try:
                pub_result = download_published_material(
                    store,
                    key,
                    doi,
                    url_resolver=published_url_fetcher,
                    institutional_url_resolver=institutional_url_fetcher,
                    pdf_fetcher=published_pdf_fetcher,
                    cache_file=cache_file,
                    progress=progress,
                    access=fetch_access,
                )
            except PublishedPdfFetchError as exc:
                pub_error = exc
            if pub_result is not None and pub_result.pdf_path is not None:
                fetched.append(pub_result.to_dict())
            elif policy.bestpdf and not presence.preprint_pdf and arxiv_id is not None:
                # best-pdf: no published PDF, whether unavailable or failed, so
                # the preprint is the best PDF there is.
                landed = False
                try:
                    result = download_arxiv_materials(
                        store,
                        key,
                        arxiv_id,
                        pdf=True,
                        source=False,
                        pdf_fetcher=pdf_fetcher,
                        progress=progress,
                    )
                    if result.pdf_path is not None:
                        fetched.append(result.to_dict())
                        landed = True
                except ArxivFetchError as exc:
                    run.fail(key, exc)
                    _emit_fail(progress, key, index, entry_total, exc)
                if pub_error is not None:
                    item = failure_item(key, pub_error, "published_pdf")
                    if landed:
                        run.warnings.append(download_warning(item, fallback="preprint_pdf"))
                    else:
                        run.fail(key, pub_error, "published_pdf")
                        _emit_fail(progress, key, index, entry_total, pub_error)
            elif pub_error is not None:
                run.fail(key, pub_error, "published_pdf")
                _emit_fail(progress, key, index, entry_total, pub_error)
            else:
                assert pub_result is not None
                reason = pub_result.reason or "published PDF unavailable"
                kind = "unavailable"
                if policy.bestpdf and presence.preprint_pdf:
                    # The preprint already in the store is the best PDF there is.
                    reason = f"{reason}; the preprint PDF is already present"
                    kind = "already_present"
                elif policy.bestpdf and arxiv_id is None:
                    reason = f"{reason}; no arXiv id for a preprint fallback ({ARXIV_LOOKUP_HINT})"
                run.skip(
                    {
                        "key": key,
                        "artifact": "published_pdf",
                        "reason": reason,
                        "attempts": list(pub_result.attempts),
                    },
                    kind,
                )
                _emit_fetch_progress(
                    progress,
                    FetchProgressEvent(
                        kind="skip",
                        key=key,
                        entry_index=index,
                        entry_total=entry_total,
                        message=reason,
                    ),
                )

        # --- Fetch supplementary PDF ---
        if can_fetch_supplement:
            try:
                supplement_result = download_supplement_material(
                    store,
                    key,
                    doi,
                    url_resolver=supplement_url_fetcher,
                    pdf_fetcher=supplement_pdf_fetcher,
                    progress=progress,
                    access=fetch_access,
                )
                if supplement_result.pdf_path is not None:
                    fetched.append(supplement_result.to_dict())
                else:
                    run.skip(supplement_result.to_dict(), "unavailable")
                    _emit_fetch_progress(
                        progress,
                        FetchProgressEvent(
                            kind="skip",
                            key=key,
                            entry_index=index,
                            entry_total=entry_total,
                            message=supplement_result.reason or "supplement unavailable",
                        ),
                    )
            except SupplementPdfFetchError as exc:
                run.fail(key, exc, "supplement_pdf")
                _emit_fail(progress, key, index, entry_total, exc)

    return run


def _planned_artifacts(
    presence: "MaterialPresence",
    *,
    arxiv_id: str | None,
    doi: str,
    published: bool,
    preprint: bool,
    preprint_fallback: bool,
    source: bool,
    supplement: bool,
) -> list[dict[str, object]]:
    """Name what a real run would try to download for one entry, and where to.

    A dry run makes no network request, so this is the plan rather than its
    outcome: each item is one artifact a real run would request, the store
    path it would be written to, and the identifier it would be requested by.
    ``fallback`` marks the preprint ``best-pdf`` falls back to only when no
    published PDF can be had. A consumer such as an approval dialog can then
    name the files and the network requests without knowing the store's
    addressing scheme.
    """
    paths = presence.paths
    planned: list[dict[str, object]] = []

    def add(artifact: str, path: Path, *, by_doi: bool, fallback: bool = False) -> None:
        item: dict[str, object] = {"artifact": artifact, "path": str(path)}
        if by_doi:
            item["doi"] = doi
        else:
            item["arxiv_id"] = arxiv_id
        item["fallback"] = fallback
        planned.append(item)

    if published:
        add("published_pdf", paths.published_pdf, by_doi=True)
    if preprint:
        add("preprint_pdf", paths.preprint_pdf, by_doi=False)
    elif preprint_fallback:
        add("preprint_pdf", paths.preprint_pdf, by_doi=False, fallback=True)
    if source:
        add("preprint_source", paths.preprint_source, by_doi=False)
    if supplement:
        add("supplement_pdf", paths.supplement_pdf, by_doi=True)
    return planned


def _emit_fetch_progress(progress: FetchProgress | None, event: FetchProgressEvent) -> None:
    if progress is not None:
        progress(event)


def _emit_fail(
    progress: FetchProgress | None, key: str, index: int, entry_total: int, exc: Exception
) -> None:
    _emit_fetch_progress(
        progress,
        FetchProgressEvent(
            kind="fail", key=key, entry_index=index, entry_total=entry_total, message=str(exc)
        ),
    )
