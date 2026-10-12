"""Entry selection and the per-entry loop behind ``Bibliography.fetch_materials``.

Split out of :mod:`pynakes._engine_helpers` to keep both modules readable. Not
public API: :meth:`pynakes.engine.Bibliography.fetch_materials` is the entry
point.
"""

from collections.abc import Callable, Collection
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pynakes.fetch_progress import WOULD_FETCH, FetchProgress, FetchProgressEvent
from pynakes.metadata import FetchPolicy
from pynakes.model import BibEntry, BibFile

if TYPE_CHECKING:
    from pynakes.fetch import FetchAccess
    from pynakes.filestore import FileStore, MaterialPresence


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
) -> tuple[list[dict], list[dict], list[dict]]:
    """Iterate *entry_queue* and download materials into *store*.

    For entries with an arXiv id, downloads the preprint PDF and/or source
    bundle. For entries with a DOI, downloads the selected published and
    supplementary PDFs as directed by *policy* and *access*.

    ``policy.bestpdf`` means "try published PDF first, fall back to preprint
    PDF when no open-access copy is available".

    Returns ``(fetched, skipped, failed)`` lists.
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

    fetched: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    # ``Bibliography.fetch_materials`` has already rejected any other value.
    fetch_access = cast("FetchAccess", access)

    entry_total = len(entry_queue)
    for index, entry in enumerate(entry_queue, start=1):
        if not entry.key.strip():
            skipped.append({"key": entry.key, "reason": "empty key"})
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
            if missing_arxiv and missing_doi:
                reason = "no arXiv id and no DOI"
            elif usable and missing_doi:
                reason = "materials already present (no DOI for a published version)"
            elif usable and missing_arxiv:
                reason = "materials already present (no arXiv id for a preprint)"
            elif missing_arxiv:
                reason = "no arXiv id"
            elif missing_doi:
                reason = "no DOI"
            else:
                reason = "materials already present"
            skipped.append({"key": key, "reason": reason})
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
            skipped.append({"key": key, "reason": WOULD_FETCH, "planned": planned})
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
                    skipped.append(
                        {"key": key, "reason": "no arXiv source archive (PDF-only submission)"}
                    )
            except ArxivFetchError as exc:
                failed.append({"key": key, "error": str(exc)})
                _emit_fetch_progress(
                    progress,
                    FetchProgressEvent(
                        kind="fail",
                        key=key,
                        entry_index=index,
                        entry_total=entry_total,
                        message=str(exc),
                    ),
                )

        # --- Fetch published PDF ---
        if fetch_published_now:
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
                if pub_result.pdf_path is not None:
                    fetched.append(pub_result.to_dict())
                    # bestpdf: published succeeded, so we're done (skip preprint).
                elif policy.bestpdf and not presence.preprint_pdf and arxiv_id is not None:
                    # bestpdf fallback: try preprint PDF now
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
                    except ArxivFetchError as exc:
                        failed.append({"key": key, "error": str(exc)})
                        _emit_fetch_progress(
                            progress,
                            FetchProgressEvent(
                                kind="fail",
                                key=key,
                                entry_index=index,
                                entry_total=entry_total,
                                message=str(exc),
                            ),
                        )
                else:
                    skipped.append(
                        {"key": key, "artifact": "published_pdf", "reason": pub_result.reason}
                    )
                    _emit_fetch_progress(
                        progress,
                        FetchProgressEvent(
                            kind="skip",
                            key=key,
                            entry_index=index,
                            entry_total=entry_total,
                            message=pub_result.reason or "published PDF unavailable",
                        ),
                    )
            except PublishedPdfFetchError as exc:
                failed.append({"key": key, "error": str(exc)})
                _emit_fetch_progress(
                    progress,
                    FetchProgressEvent(
                        kind="fail",
                        key=key,
                        entry_index=index,
                        entry_total=entry_total,
                        message=str(exc),
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
                    skipped.append(supplement_result.to_dict())
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
                failed.append({"key": key, "artifact": "supplement_pdf", "error": str(exc)})
                _emit_fetch_progress(
                    progress,
                    FetchProgressEvent(
                        kind="fail",
                        key=key,
                        entry_index=index,
                        entry_total=entry_total,
                        message=str(exc),
                    ),
                )

    return fetched, skipped, failed


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
