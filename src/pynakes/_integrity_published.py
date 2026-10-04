"""Preprint detection and published-metadata application.

The ``published`` half of :mod:`pynakes.integrity`: decide whether an entry is
a preprint, look up whether it has since appeared, and apply what is found.

Two opposite directions of travel live here, and keeping them distinct is the
point of the split. A *promotion* gives a preprint its published metadata (DOI,
journal, ``@article`` type). A *backfill* goes the other way, giving an
already-published entry the ``eprint`` provenance of the preprint behind it.
Both change entries and both are driven by ``--published``, but they are
counted apart (:attr:`~pynakes.integrity.PublishedReport.promoted` and
``linked``) because reporting one as the other describes the reverse of what
happened.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pynakes._identifiers import is_arxiv_doi, normalize_arxiv, normalize_doi
from pynakes._integrity_common import (
    _PREPRINT_DOI_PREFIXES,
    FieldUpdate,
    MetadataFetchError,
    PublishedCandidate,
    PublishedReport,
    _container_update,
    _emit_progress,
    _field_value,
    _journal,
    _map_concurrently,
)
from pynakes.editing import set_entry_field, set_entry_type
from pynakes.identity import evidence_from_entry
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry, BibFile
from pynakes.progress import EntryProgress, EntryProgressEvent
from pynakes.provider_cache import open_cache
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.identity import resolve_arxiv_id_for_doi
from pynakes.providers.repositories import arxiv as arxiv_provider


def _backfill_job(
    args: tuple[
        str,
        str | Path | None,
        Callable[[str], dict | None] | None,
        Callable[[str], dict | None] | None,
    ],
) -> str | None | ProviderFetchError:
    normalized, cache_file, openalex_fetcher, semantic_scholar_fetcher = args
    try:
        return resolve_arxiv_id_for_doi(
            normalized,
            cache_file=cache_file,
            openalex_fetcher=openalex_fetcher,
            semantic_scholar_fetcher=semantic_scholar_fetcher,
        )
    except ProviderFetchError as exc:
        return exc


def _finish_doi_to_arxiv_backfill(
    entry: BibEntry,
    normalized: str,
    result: str | None | ProviderFetchError,
    report: PublishedReport,
    *,
    apply: bool,
    dialect: str,
) -> None:
    if isinstance(result, ProviderFetchError):
        report.warnings.append(
            {"type": "doi_to_arxiv_lookup_failed", "key": entry.key, "message": str(result)}
        )
        return

    if result is None:
        report.candidates.append(
            PublishedCandidate(
                entry.key,
                "doi",
                normalized,
                "not_found",
                doi=normalized,
                message="No arXiv id found in OpenAlex or Semantic Scholar",
            )
        )
        return

    candidate = PublishedCandidate(
        entry.key,
        "doi",
        normalized,
        "arxiv_found",
        doi=normalized,
        arxiv_id=result,
        message="arXiv identity found",
    )
    report.candidates.append(candidate)
    if apply:
        _apply_arxiv_backfill_candidate(entry, candidate, report, dialect)


def _arxiv_check_job(
    args: tuple[str, str | Path | None],
) -> dict[str, str] | MetadataFetchError:
    identifier, cache_file = args
    try:
        return fetch_arxiv_metadata(identifier, cache_file=cache_file)
    except MetadataFetchError as exc:
        return exc


def _finish_arxiv_check(
    entry: BibEntry,
    source: str,
    identifier: str,
    result: dict[str, str] | MetadataFetchError,
    report: PublishedReport,
    *,
    apply: bool,
    dialect: str = "bibtex",
) -> None:
    if isinstance(result, MetadataFetchError):
        report.warnings.append(
            {"type": "preprint_lookup_failed", "key": entry.key, "message": str(result)}
        )
        return

    status = "published" if result.get("doi") or result.get("journal") else "not_found"
    candidate = PublishedCandidate(
        entry.key,
        source,
        identifier,
        status,
        doi=result.get("doi"),
        journal=result.get("journal"),
        metadata=result,
        message="Published metadata found"
        if status == "published"
        else "No published metadata found",
    )
    report.candidates.append(candidate)
    if apply and status == "published":
        _apply_published_candidate(entry, candidate, report, dialect)


def check_published(
    lib: BibFile,
    *,
    online: bool = False,
    apply: bool = False,
    cache_file: str | Path | None = None,
    openalex_fetcher: Callable[[str], dict | None] | None = None,
    semantic_scholar_fetcher: Callable[[str], dict | None] | None = None,
    progress: EntryProgress | None = None,
    concurrency: int = 1,
) -> PublishedReport:
    """Detect preprints and optionally apply published DOI/journal metadata.

    ``concurrency`` bounds how many arXiv/backfill lookups run at once;
    candidates, warnings, and applied updates are still produced in the
    library's own entry order regardless of fetch completion order.
    """
    report = PublishedReport()
    dialect = library_dialect(lib)
    entries = list(lib.entries.values())
    entry_total = len(entries)

    # kind in {"noop", "done", "backfill", "arxiv"}. "done" entries were
    # already fully resolved (no network involved) during this first pass.
    plan: list[tuple[str, object]] = []
    backfill_positions: list[int] = []
    backfill_jobs: list[
        tuple[
            str,
            str | Path | None,
            Callable[[str], dict | None] | None,
            Callable[[str], dict | None] | None,
        ]
    ] = []
    arxiv_positions: list[int] = []
    arxiv_jobs: list[tuple[str, str | Path | None]] = []

    for pos, entry in enumerate(entries):
        preprint = _preprint_identity(entry)
        if preprint is None:
            doi = entry.fields.get("doi", "").strip()
            normalized = None
            if online and doi:
                try:
                    normalized = normalize_doi(doi)
                except ValueError:
                    normalized = None
            if normalized is None:
                plan.append(("noop", None))
                continue
            plan.append(("backfill", normalized))
            backfill_positions.append(pos)
            backfill_jobs.append(
                (normalized, cache_file, openalex_fetcher, semantic_scholar_fetcher)
            )
            continue

        source, identifier = preprint
        existing_doi = entry.fields.get("doi", "").strip()
        existing_journal = _journal(entry)
        if existing_doi and existing_journal:
            candidate = PublishedCandidate(
                entry.key,
                source,
                identifier,
                "published_present",
                doi=existing_doi,
                journal=existing_journal,
                message="Entry already has DOI and journal metadata",
            )
            report.candidates.append(candidate)
            if apply:
                _apply_published_candidate(entry, candidate, report, dialect)
            plan.append(("done", None))
            continue
        if not online:
            report.candidates.append(
                PublishedCandidate(
                    entry.key,
                    source,
                    identifier,
                    "unchecked",
                    message="Pass --online to check authoritative preprint metadata",
                )
            )
            plan.append(("done", None))
            continue
        if source != "arxiv":
            report.candidates.append(
                PublishedCandidate(
                    entry.key,
                    source,
                    identifier,
                    "unsupported_source",
                    message="Online published-version lookup currently supports arXiv metadata",
                )
            )
            plan.append(("done", None))
            continue

        plan.append(("arxiv", (source, identifier)))
        arxiv_positions.append(pos)
        arxiv_jobs.append((identifier, cache_file))

    backfill_results = _map_concurrently(backfill_jobs, _backfill_job, concurrency=concurrency)
    backfill_by_pos = dict(zip(backfill_positions, backfill_results))
    arxiv_results = _map_concurrently(arxiv_jobs, _arxiv_check_job, concurrency=concurrency)
    arxiv_by_pos = dict(zip(arxiv_positions, arxiv_results))

    for index, entry in enumerate(entries, start=1):
        _emit_progress(progress, EntryProgressEvent(entry.key, index, entry_total))
        pos = index - 1
        kind, data = plan[pos]
        if kind in ("noop", "done"):
            continue
        if kind == "backfill":
            _finish_doi_to_arxiv_backfill(
                entry, data, backfill_by_pos[pos], report, apply=apply, dialect=dialect
            )
            continue
        source, identifier = data
        _finish_arxiv_check(
            entry, source, identifier, arxiv_by_pos[pos], report, apply=apply, dialect=dialect
        )
    return report


def _fetch_arxiv_record(
    identifier: str, *, cache_file: str | Path | None = None
) -> arxiv_provider.ArxivRecord:
    normalized = normalize_arxiv(identifier)
    if normalized is None:
        raise MetadataFetchError(f"Malformed arXiv identifier: {identifier!r}")
    cache = open_cache(cache_file)
    try:
        text = cache.get("arxiv", normalized, "xml")
        if text is None:
            text = arxiv_provider.fetch_atom(normalized)
            cache.put("arxiv", normalized, "xml", text)
        return arxiv_provider.parse_atom(text, normalized)
    except ProviderFetchError as exc:
        raise MetadataFetchError(str(exc)) from exc


def fetch_arxiv_metadata(
    identifier: str, *, cache_file: str | Path | None = None
) -> dict[str, str]:
    """Fetch publication metadata an arXiv preprint links to, if any.

    Delegates fetch/parse to :mod:`pynakes.providers.repositories.arxiv` and keeps
    only the cache lookup here. A conventional arXiv journal reference is split
    into journal, volume, pages, and year rather than stored wholesale as a
    journal title.
    """
    record = _fetch_arxiv_record(identifier, cache_file=cache_file)
    fields = {"doi": record.doi}
    fields.update(_parse_journal_reference(record.journal))
    return fields


def _parse_journal_reference(value: str) -> dict[str, str]:
    """Parse the common arXiv ``journal_ref`` shape conservatively."""
    clean = " ".join(value.split()).rstrip(".")
    match = re.fullmatch(
        r"(?P<journal>.+?)\s+(?P<volume>[^\s,]+),\s*"
        r"(?P<pages>[^\s,]+)(?:\s*\((?P<year>\d{4})\))?",
        clean,
    )
    if match is None:
        return {"journal": clean} if clean else {}
    return {name: part for name, part in match.groupdict().items() if part}


def _fetch_arxiv_fields(identifier: str, *, cache_file: str | Path | None = None) -> dict[str, str]:
    """Fetch arXiv metadata as BibTeX-style field names, for field comparison."""
    record = _fetch_arxiv_record(identifier, cache_file=cache_file)
    fields: dict[str, str] = {"eprint": record.arxiv_id}
    if record.title:
        fields["title"] = record.title
    if record.authors:
        fields["author"] = " and ".join(record.authors)
    if record.published:
        fields["year"] = record.published[:4]
    if record.doi:
        fields["doi"] = record.doi
    if record.journal:
        fields.update(_parse_journal_reference(record.journal))
    if record.summary:
        fields["abstract"] = record.summary
    return fields


def _apply_published_candidate(
    entry: BibEntry,
    candidate: PublishedCandidate,
    report: PublishedReport,
    dialect: str = "bibtex",
) -> None:
    before = len(report.updates)
    existing_doi = _field_value(entry, "doi").strip()
    if candidate.doi and (not existing_doi or is_arxiv_doi(existing_doi)):
        try:
            value = normalize_doi(candidate.doi)
        except ValueError:
            value = candidate.doi
        if set_entry_field(entry, "doi", value):
            report.updates.append(FieldUpdate(entry.key, "doi", value))
    # Promote before writing the container, so the container lands in the field
    # the *promoted* type accepts: a preprint becoming an @article takes the
    # journal it was just found to have published in.
    if entry.type.lower() in {"misc", "online", "unpublished"} and (
        candidate.doi or candidate.journal
    ):
        if set_entry_type(entry, "article"):
            report.updates.append(FieldUpdate(entry.key, "type", "article"))
    container = _container_update(entry, (candidate.journal or "").strip(), dialect=dialect)
    if container is not None:
        target, value = container
        if set_entry_field(entry, target, value):
            report.updates.append(FieldUpdate(entry.key, target, value))
    for field_name in ("volume", "number", "pages", "numpages"):
        value = candidate.metadata.get(field_name, "").strip()
        if value and not _field_value(entry, field_name).strip():
            if set_entry_field(entry, field_name, value):
                report.updates.append(FieldUpdate(entry.key, field_name, value))
    published_year = candidate.metadata.get("year", "").strip()
    if published_year and _field_value(entry, "year").strip() != published_year:
        if set_entry_field(entry, "year", published_year):
            report.updates.append(FieldUpdate(entry.key, "year", published_year))
    if len(report.updates) > before and entry.key not in report.promoted_keys:
        report.promoted_keys.append(entry.key)


def _apply_arxiv_backfill_candidate(
    entry: BibEntry,
    candidate: PublishedCandidate,
    report: PublishedReport,
    dialect: str,
) -> None:
    if not candidate.arxiv_id:
        return

    before = len(report.updates)
    existing_eprint = _field_value(entry, "eprint").strip()
    if existing_eprint:
        existing_arxiv = normalize_arxiv(existing_eprint)
        if existing_arxiv != candidate.arxiv_id:
            return
    elif set_entry_field(entry, "eprint", candidate.arxiv_id):
        report.updates.append(FieldUpdate(entry.key, "eprint", candidate.arxiv_id))

    archive_field = "eprinttype" if dialect == "biblatex" else "archiveprefix"
    archive_value = "arxiv" if dialect == "biblatex" else "arXiv"
    if not _field_value(entry, archive_field).strip():
        if set_entry_field(entry, archive_field, archive_value):
            report.updates.append(FieldUpdate(entry.key, archive_field, archive_value))
    if len(report.updates) > before and entry.key not in report.linked_keys:
        report.linked_keys.append(entry.key)


def _preprint_identity(entry: BibEntry) -> tuple[str, str] | None:
    identifiers = evidence_from_entry(entry).identifiers.by_kind()
    if arxiv := identifiers.get("arxiv"):
        return "arxiv", sorted(arxiv)[0]
    if doi := identifiers.get("doi"):
        normalized = sorted(doi)[0]
        if normalized.startswith(_PREPRINT_DOI_PREFIXES):
            return "preprint_doi", normalized
    if ssrn := identifiers.get("ssrn"):
        return "ssrn", sorted(ssrn)[0]
    url = " ".join(entry.fields.get(field, "") for field in ("url", "howpublished", "note")).lower()
    if "ssrn.com" in url:
        return "ssrn", url
    return None
