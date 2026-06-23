"""Integrity verification and conservative metadata enrichment."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pynakes.authors import last_name, split_name_list
from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.doi import canonical_doi, fetch_bibtex_for_doi, normalize_doi
from pynakes.editing import set_entry_field, set_entry_type
from pynakes.model import BibEntry, BibFile


@dataclass
class IntegrityIssue:
    """One verification or enrichment finding."""

    type: str
    severity: str
    message: str
    key: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "key": self.key,
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class VerifyReport:
    """Result of verifying entries against DOI metadata."""

    checked: int = 0
    issues: list[IntegrityIssue] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def infos(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "info")

    def to_dict(self) -> dict[str, object]:
        return {
            "checked": self.checked,
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class FieldUpdate:
    """One field added or updated by an enrichment operation."""

    key: str
    field: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "field": self.field, "value": self.value}


@dataclass
class EnrichReport:
    """Result of conservative metadata enrichment."""

    updates: list[FieldUpdate] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def changed_entries(self) -> int:
        return len({update.key for update in self.updates})

    @property
    def changed_fields(self) -> int:
        return len(self.updates)

    def to_dict(self) -> dict[str, object]:
        return {
            "changed_entries": self.changed_entries,
            "changed_fields": self.changed_fields,
            "updates": [update.to_dict() for update in self.updates],
        }


@dataclass
class PublishedCandidate:
    """A preprint that may have published metadata available."""

    key: str
    source: str
    identifier: str
    status: str
    doi: str | None = None
    journal: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "source": self.source,
            "identifier": self.identifier,
            "status": self.status,
            "doi": self.doi,
            "journal": self.journal,
            "message": self.message,
        }


@dataclass
class PublishedReport:
    """Result of checking preprints for published metadata."""

    candidates: list[PublishedCandidate] = field(default_factory=list)
    updates: list[FieldUpdate] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def checked(self) -> int:
        return len(self.candidates)

    @property
    def published(self) -> int:
        return sum(1 for c in self.candidates if c.status in {"published", "published_present"})

    @property
    def changed_entries(self) -> int:
        return len({update.key for update in self.updates})

    def to_dict(self) -> dict[str, object]:
        return {
            "checked": self.checked,
            "published": self.published,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "updates": [update.to_dict() for update in self.updates],
        }


class MetadataFetchError(Exception):
    """Raised when authoritative metadata cannot be fetched or parsed."""


_DOI_URL_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)(10\.\d{4,9}/\S+)", re.I)
_YEAR_RE = re.compile(r"\d{4}")
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#\s]+)", re.I)
_ARXIV_VERSION_RE = re.compile(r"v\d+$", re.I)
_PREPRINT_DOI_PREFIXES = ("10.1101/", "10.21203/", "10.2139/")


def verify_library(
    lib: BibFile,
    *,
    online: bool = False,
    cache_dir: str | Path | None = None,
) -> VerifyReport:
    """Verify DOI-backed entries against provider metadata.

    Network access is never implicit. With ``online=False``, DOI entries are
    only syntax-checked and reported as unchecked.
    """
    report = VerifyReport()
    for entry in lib.entries.values():
        doi = entry.fields.get("doi", "").strip()
        if not doi:
            continue
        try:
            normalized = normalize_doi(doi)
        except ValueError:
            report.issues.append(
                IntegrityIssue(
                    "malformed_doi",
                    "error",
                    f"Entry {entry.key!r} has a malformed DOI",
                    entry.key,
                    "doi",
                    actual=doi,
                )
            )
            continue

        if not online:
            report.issues.append(
                IntegrityIssue(
                    "doi_not_checked",
                    "info",
                    "Pass --online to verify this DOI against provider metadata",
                    entry.key,
                    "doi",
                    actual=normalized,
                )
            )
            continue

        try:
            remote = fetch_doi_entry(normalized, cache_dir=cache_dir)
        except MetadataFetchError as exc:
            report.issues.append(
                IntegrityIssue("doi_unresolved", "error", str(exc), entry.key, "doi", actual=doi)
            )
            continue

        report.checked += 1
        report.issues.extend(_compare_entry(entry, remote))
    return report


def enrich_library(
    lib: BibFile,
    *,
    online: bool = False,
    cache_dir: str | Path | None = None,
) -> EnrichReport:
    """Fill missing fields from local DOI URLs and DOI provider metadata."""
    report = EnrichReport()
    for entry in lib.entries.values():
        doi = entry.fields.get("doi", "").strip()
        if not doi:
            inferred = _doi_from_entry_urls(entry)
            if inferred and set_entry_field(entry, "doi", inferred):
                report.updates.append(FieldUpdate(entry.key, "doi", inferred))
                doi = inferred

        if not doi:
            continue
        try:
            normalized = normalize_doi(doi)
        except ValueError:
            report.warnings.append(
                {"type": "malformed_doi", "key": entry.key, "message": f"Malformed DOI: {doi!r}"}
            )
            continue
        if not online:
            continue

        try:
            remote = fetch_doi_entry(normalized, cache_dir=cache_dir)
        except MetadataFetchError as exc:
            report.warnings.append(
                {"type": "doi_unresolved", "key": entry.key, "message": str(exc)}
            )
            continue
        for field_name, value in _missing_field_updates(entry, remote):
            if set_entry_field(entry, field_name, value):
                report.updates.append(FieldUpdate(entry.key, field_name, value))
    return report


def check_published(
    lib: BibFile,
    *,
    online: bool = False,
    apply: bool = False,
    cache_dir: str | Path | None = None,
) -> PublishedReport:
    """Detect preprints and optionally apply published DOI/journal metadata."""
    report = PublishedReport()
    for entry in lib.entries.values():
        preprint = _preprint_identity(entry)
        if preprint is None:
            continue
        source, identifier = preprint
        existing_doi = entry.fields.get("doi", "").strip()
        existing_journal = _journal(entry)
        if existing_doi and existing_journal:
            report.candidates.append(
                PublishedCandidate(
                    entry.key,
                    source,
                    identifier,
                    "published_present",
                    doi=existing_doi,
                    journal=existing_journal,
                    message="Entry already has DOI and journal metadata",
                )
            )
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
            continue

        try:
            arxiv = fetch_arxiv_metadata(identifier, cache_dir=cache_dir)
        except MetadataFetchError as exc:
            report.warnings.append(
                {"type": "preprint_lookup_failed", "key": entry.key, "message": str(exc)}
            )
            continue
        status = "published" if arxiv.get("doi") or arxiv.get("journal") else "not_found"
        candidate = PublishedCandidate(
            entry.key,
            source,
            identifier,
            status,
            doi=arxiv.get("doi"),
            journal=arxiv.get("journal"),
            message="Published metadata found"
            if status == "published"
            else "No published metadata found",
        )
        report.candidates.append(candidate)
        if apply and status == "published":
            _apply_published_candidate(entry, candidate, report)
    return report


def fetch_doi_entry(doi: str, *, cache_dir: str | Path | None = None) -> BibEntry:
    """Fetch DOI BibTeX metadata, using a deterministic cache when provided."""
    normalized = normalize_doi(doi)
    cache_path = _cache_path(cache_dir, "doi", normalized, ".bib")
    if cache_path is not None and cache_path.exists():
        text = cache_path.read_text(encoding="utf-8", errors="replace")
    else:
        try:
            text = fetch_doi_bibtex(normalized)
        except Exception as exc:
            raise MetadataFetchError(f"Could not fetch DOI {normalized!r}: {exc}") from exc
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")

    try:
        entries = parse_bib(text).entries.values()
    except ParseError as exc:
        raise MetadataFetchError(
            f"Provider returned invalid BibTeX for {normalized}: {exc}"
        ) from exc
    if not entries:
        raise MetadataFetchError(f"Provider returned no BibTeX for {normalized}")
    return entries[0]


def fetch_doi_bibtex(doi: str) -> str:
    """Fetch DOI BibTeX. Split out for tests to stub without network."""
    return fetch_bibtex_for_doi(doi)


def fetch_arxiv_metadata(identifier: str, *, cache_dir: str | Path | None = None) -> dict[str, str]:
    """Fetch and parse arXiv Atom metadata for one identifier."""
    normalized = _normalize_arxiv(identifier)
    if normalized is None:
        raise MetadataFetchError(f"Malformed arXiv identifier: {identifier!r}")
    cache_path = _cache_path(cache_dir, "arxiv", normalized, ".xml")
    if cache_path is not None and cache_path.exists():
        text = cache_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = fetch_arxiv_atom(normalized)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
    return _parse_arxiv_atom(text, normalized)


def fetch_arxiv_atom(identifier: str) -> str:
    """Fetch arXiv Atom XML. Split out for tests to stub without network."""
    url = f"https://export.arxiv.org/api/query?id_list={quote(identifier)}"
    request = Request(url, headers={"User-Agent": "pynakes/0.3.0 integrity"})
    try:
        with urlopen(request, timeout=15.0) as response:
            data = response.read()
            encoding = response.headers.get_content_charset() or "utf-8"
            return data.decode(encoding, errors="replace")
    except HTTPError as exc:
        raise MetadataFetchError(f"arXiv returned HTTP {exc.code} for {identifier}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise MetadataFetchError(
            f"Could not fetch arXiv metadata for {identifier}: {reason}"
        ) from exc


def _compare_entry(local: BibEntry, remote: BibEntry) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []
    local_title = local.fields.get("title", "")
    remote_title = remote.fields.get("title", "")
    if local_title and remote_title and _similarity(local_title, remote_title) < 0.86:
        issues.append(
            IntegrityIssue(
                "title_mismatch",
                "error",
                "Local title does not match DOI provider title",
                local.key,
                "title",
                expected=remote_title,
                actual=local_title,
            )
        )
    local_year = _year(local)
    remote_year = _year(remote)
    if local_year and remote_year and local_year != remote_year:
        issues.append(
            IntegrityIssue(
                "year_mismatch",
                "warning",
                "Local year does not match DOI provider year",
                local.key,
                "year",
                expected=remote_year,
                actual=local_year,
            )
        )
    local_author = _first_author(local)
    remote_author = _first_author(remote)
    if local_author and remote_author and local_author != remote_author:
        issues.append(
            IntegrityIssue(
                "author_mismatch",
                "warning",
                "Local first author does not match DOI provider first author",
                local.key,
                "author",
                expected=remote_author,
                actual=local_author,
            )
        )
    if _has_retraction_flag(remote):
        issues.append(
            IntegrityIssue(
                "retraction_flag",
                "error",
                "DOI provider metadata appears to flag this work as retracted",
                local.key,
                "doi",
            )
        )
    return issues


def _missing_field_updates(entry: BibEntry, remote: BibEntry) -> list[tuple[str, str]]:
    updates: list[tuple[str, str]] = []
    for field_name in (
        "title",
        "author",
        "editor",
        "volume",
        "number",
        "pages",
        "publisher",
        "isbn",
        "url",
    ):
        value = remote.fields.get(field_name, "").strip()
        if value and not entry.fields.get(field_name, "").strip():
            updates.append((field_name, value))
    if not entry.fields.get("journal") and not entry.fields.get("journaltitle"):
        journal = remote.fields.get("journal") or remote.fields.get("journaltitle")
        if journal:
            updates.append(("journal", journal))
    if not entry.fields.get("year") and not entry.fields.get("date"):
        date = remote.fields.get("date") or remote.fields.get("year")
        if date:
            updates.append(("date" if "-" in date else "year", date))
    for field_name in ("doi", "pmid", "pmcid"):
        value = remote.fields.get(field_name, "").strip()
        if value and not entry.fields.get(field_name, "").strip():
            updates.append((field_name, value))
    return updates


def _apply_published_candidate(
    entry: BibEntry, candidate: PublishedCandidate, report: PublishedReport
) -> None:
    if candidate.doi and not entry.fields.get("doi"):
        try:
            value = normalize_doi(candidate.doi)
        except ValueError:
            value = candidate.doi
        if set_entry_field(entry, "doi", value):
            report.updates.append(FieldUpdate(entry.key, "doi", value))
    if candidate.journal and not _journal(entry):
        if set_entry_field(entry, "journal", candidate.journal):
            report.updates.append(FieldUpdate(entry.key, "journal", candidate.journal))
    if entry.type.lower() in {"misc", "online", "unpublished"} and (
        candidate.doi or candidate.journal
    ):
        if set_entry_type(entry, "article"):
            report.updates.append(FieldUpdate(entry.key, "type", "article"))


def _cache_path(
    cache_dir: str | Path | None, namespace: str, identifier: str, suffix: str
) -> Path | None:
    if cache_dir is None:
        return None
    digest = hashlib.sha256(identifier.lower().encode("utf-8")).hexdigest()
    return Path(cache_dir) / namespace / f"{digest}{suffix}"


def _doi_from_entry_urls(entry: BibEntry) -> str | None:
    for field_name in ("url", "howpublished", "note"):
        match = _DOI_URL_RE.search(entry.fields.get(field_name, ""))
        if match:
            try:
                return normalize_doi(match.group(1).rstrip(").,;"))
            except ValueError:
                continue
    return None


def _preprint_identity(entry: BibEntry) -> tuple[str, str] | None:
    arxiv = _entry_arxiv_id(entry)
    if arxiv:
        return "arxiv", arxiv
    doi = entry.fields.get("doi", "")
    try:
        normalized = canonical_doi(doi)
    except ValueError:
        normalized = ""
    if normalized.startswith(_PREPRINT_DOI_PREFIXES):
        return "preprint_doi", normalized
    url = " ".join(entry.fields.get(field, "") for field in ("url", "howpublished", "note")).lower()
    if "ssrn.com" in url:
        return "ssrn", url
    return None


def _entry_arxiv_id(entry: BibEntry) -> str | None:
    for field_name in ("arxiv", "eprint"):
        value = entry.fields.get(field_name)
        if not value:
            continue
        archive = entry.fields.get("archiveprefix") or entry.fields.get("eprinttype") or ""
        if field_name == "arxiv" or archive.lower() == "arxiv":
            normalized = _normalize_arxiv(value)
            if normalized:
                return normalized
    for field_name in ("url", "howpublished", "note"):
        match = _ARXIV_URL_RE.search(entry.fields.get(field_name, ""))
        if match:
            normalized = _normalize_arxiv(match.group(1))
            if normalized:
                return normalized
    return None


def _normalize_arxiv(value: str) -> str | None:
    cleaned = value.strip().strip("{}<>")
    cleaned = re.sub(r"^arxiv:\s*", "", cleaned, flags=re.I)
    match = _ARXIV_URL_RE.search(cleaned)
    if match:
        cleaned = match.group(1)
    cleaned = cleaned.removesuffix(".pdf")
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned)
    cleaned = cleaned.strip("/")
    return cleaned.lower() or None


def _parse_arxiv_atom(text: str, identifier: str) -> dict[str, str]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise MetadataFetchError(f"arXiv returned invalid XML for {identifier}") from exc
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise MetadataFetchError(f"arXiv returned no entry for {identifier}")
    doi = _xml_text(entry, "arxiv:doi", ns)
    journal = _xml_text(entry, "arxiv:journal_ref", ns)
    return {"doi": doi, "journal": journal}


def _xml_text(element: ET.Element, path: str, ns: dict[str, str]) -> str:
    found = element.find(path, ns)
    return " ".join((found.text or "").split()) if found is not None else ""


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, _text_key(left), _text_key(right)).ratio()


def _text_key(value: str) -> str:
    value = value.replace("{", "").replace("}", "")
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _year(entry: BibEntry) -> str:
    raw = entry.fields.get("year") or entry.fields.get("date") or ""
    match = _YEAR_RE.search(raw)
    return match.group(0) if match else ""


def _first_author(entry: BibEntry) -> str:
    raw = entry.fields.get("author") or entry.fields.get("editor") or ""
    names = split_name_list(raw)
    return last_name(names[0]).lower() if names else ""


def _journal(entry: BibEntry) -> str:
    return entry.fields.get("journal", "").strip() or entry.fields.get("journaltitle", "").strip()


def _has_retraction_flag(entry: BibEntry) -> bool:
    haystack = " ".join(entry.fields.get(field, "") for field in ("title", "note", "annote"))
    return "retract" in haystack.lower()
