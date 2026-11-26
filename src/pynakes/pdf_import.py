"""Import references from local PDFs, retaining evidence and linking originals.

Inspection is offline. Provider resolution requires ``online=True``; a PDF is
never uploaded. Accepted entries are staged in a Bibliography for the normal
preview/commit lifecycle. Uncertain documents remain explicit per-file results.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes._pdf_evidence import (
    PDFDependencyError,
    PDFInspection,
    file_digest,
    inspect_pdf,
    require_pdf_dependency,
    title_supported,
)
from pynakes.convert import convert
from pynakes.editing import rename_entry_key, set_entry_field
from pynakes.engine._entry_style import apply_library_style
from pynakes.engine._insert import add_entry_ordered
from pynakes.fields import check_field_value
from pynakes.files import parse_file_field, resolve_linked_file
from pynakes.identity import (
    compare_work_evidence,
    evidence_from_entry,
    identity_class,
    normalize_work_identifier,
)
from pynakes.keys import generate_key, unique_key
from pynakes.metadata import library_dialect
from pynakes.model import BibEntry, BibFile, EntryStore

if TYPE_CHECKING:
    from pynakes.engine import Bibliography

__all__ = ["PDFDependencyError", "PDFImportReport", "PDFInspection", "import_pdfs", "inspect_pdf"]


@dataclass
class PDFImportReport:
    """Per-file outcomes; ``complete`` means every file was imported or present."""

    results: list[dict]

    def to_dict(self) -> dict:
        counts = {
            status: sum(r["status"] == status for r in self.results)
            for status in (
                "imported",
                "linked",
                "existing",
                "ambiguous",
                "unresolved",
                "needs_online",
                "failed",
            )
        }
        return {
            "requested": len(self.results),
            "complete": all(
                r["status"] in {"imported", "linked", "existing"} for r in self.results
            ),
            "summary": counts,
            "results": self.results,
        }


def _paths(paths: Sequence[str | Path]) -> list[Path]:
    expanded: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            members = sorted(
                (p for p in path.iterdir() if p.suffix.lower() == ".pdf"), key=lambda p: p.name
            )
            # An empty folder is an explicit failed input, not silent success.
            expanded.extend(members or [path])
        else:
            expanded.append(path)
    return list(dict.fromkeys(expanded))


def import_pdfs(
    bibliography: Bibliography,
    paths: Sequence[str | Path],
    *,
    online: bool = False,
    identifier: str | None = None,
    key: str | None = None,
    key_source: str | None = None,
    cache_file: str | Path | None = None,
    mode: str | None = None,
    role: str | None = None,
) -> PDFImportReport:
    """Stage references and attachments, adopting files when Pinax is configured.

    Paths can be files or directories (immediate PDFs only, sorted by filename).
    ``identifier`` explicitly confirms a DOI/arXiv candidate for a single PDF;
    it can also supply an identifier missing from a scan. ``key`` is likewise
    single-file. ``key_source`` uses the existing ``import-key-source`` setting.
    Online text candidates require title corroboration; multiple plausible
    records remain ambiguous. Partial batches stage only successful outcomes.
    Repeating an import recognizes linked bytes and existing work identifiers.

    Requires a bound bibliography path so attachment links are meaningful.
    Pinax defaults to moving originals after durable storage; ``mode="copy"``
    preserves them. Without Pinax, links continue to reference the originals.
    Source hashes are checked again at commit. The returned report carries
    evidence/provenance and should be saved by callers needing an import log.
    """
    from pynakes.importer import library_key_source, resolve_identifier

    require_pdf_dependency()
    if bibliography.path is None:
        raise ValueError("PDF import requires a bibliography bound to a path")
    inputs = _paths(paths)
    if not inputs:
        raise ValueError("Provide at least one PDF or directory")
    if (identifier is not None or key is not None) and len(inputs) != 1:
        raise ValueError("--identifier and --key require exactly one PDF")
    if identifier is not None:
        kind, _ = resolve_identifier(identifier)
        if kind not in {"doi", "arxiv", "isbn"}:
            raise ValueError("PDF identifier selection supports DOI, arXiv and ISBN identifiers")
    source = library_key_source(bibliography.lib, key_source)
    if source not in {"generated", "provider"}:
        raise ValueError("key_source must be generated or provider")
    if key is not None and not _valid_key(key):
        raise ValueError("Invalid citation key")
    results: list[dict] = []
    hashes: dict[Path, str] = {}
    for path in inputs:
        result: dict = {"path": str(path), "status": "failed"}
        try:
            inspection = inspect_pdf(path)
            result.update(inspection.to_dict())
            byte_matches = _byte_matches(bibliography, inspection, hashes)
            if byte_matches:
                result.update(
                    status="existing" if len(byte_matches) == 1 else "ambiguous",
                    existing_keys=byte_matches,
                    reason="matching_pdf_bytes",
                )
                if key is not None and byte_matches != [key]:
                    result.update(status="ambiguous", reason="existing_work_has_different_key")
                if identifier is not None:
                    selected = normalize_work_identifier(*resolve_identifier(identifier))
                    matches = [
                        entry
                        for entry in bibliography.lib.entries.values()
                        if entry.key in byte_matches
                    ]
                    if not all(
                        selected in evidence_from_entry(entry).identifiers.items
                        for entry in matches
                    ):
                        result.update(
                            status="ambiguous", reason="existing_pdf_has_different_identity"
                        )
                if result["status"] == "existing" and bibliography.files is not None:
                    result["adoption"] = bibliography.adopt_file(
                        byte_matches[0], inspection.path, mode=mode, role=role
                    )
            else:
                entry, reason = _select_entry(
                    bibliography, inspection, online, identifier, cache_file, result
                )
                if entry is None:
                    result.update(status=reason)
                else:
                    _stage(
                        bibliography, inspection, entry, key, source, result, mode=mode, role=role
                    )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result.update(status="failed", message=str(exc))
        results.append(result)
    return PDFImportReport(results)


def _byte_matches(
    coll: Bibliography, inspection: PDFInspection, hashes: dict[Path, str]
) -> list[str]:
    assert coll.path is not None
    matches: list[str] = []
    for entry in coll.lib.entries.values():
        for link in parse_file_field(entry):
            resolve_linked_file(link, coll.path.resolve(), [], coll.lib)
            path = link.resolved_path
            if path is None or not path.is_file():
                continue
            path = path.resolve()
            if path not in hashes:
                try:
                    hashes[path] = file_digest(path)
                except OSError:
                    continue
            if hashes[path] == inspection.sha256:
                matches.append(entry.key)
                break
    return matches


def _record_entry(record: dict) -> BibEntry:
    return BibEntry(
        key=record.get("provider_key") or "",
        type=record["entry_type"],
        fields=dict(record["fields"]),
        modified=True,
    )


def _select_entry(
    coll: Bibliography,
    inspection: PDFInspection,
    online: bool,
    identifier: str | None,
    cache_file: str | Path | None,
    result: dict,
) -> tuple[BibEntry | None, str]:
    from pynakes import importer
    from pynakes._pdf_review import metadata_problems
    from pynakes.provider_cache import cache_scope

    complete = []
    if identifier is None:
        for record in inspection.records:
            fields = record["fields"]
            if not (
                fields.get("title")
                and (fields.get("author") or fields.get("editor"))
                and (fields.get("year") or fields.get("date"))
            ):
                continue
            # A .bib attachment can be the paper's reference list, not its own
            # citation. Require its title to agree with the actual document.
            if record["source"].startswith("attachment:") and not title_supported(
                inspection, fields["title"]
            ):
                continue
            entry = _record_entry(record)
            problems = metadata_problems(entry)
            if problems:
                result.setdefault("metadata_issues", []).append(
                    {"source": record["source"], "problems": problems, "record": record}
                )
                continue
            if not any(e.type == entry.type and e.fields == entry.fields for e in complete):
                complete.append(entry)
        if len(complete) == 1 and not online:
            result["selected_from"] = "embedded_metadata"
            return complete[0], "ready"
        if len(complete) > 1:
            result["reason"] = "multiple_embedded_records"
            return None, "ambiguous"
    identifiers = (
        [identifier]
        if identifier is not None
        else list(
            dict.fromkeys(
                (
                    "arXiv:"
                    if candidate["kind"] == "arxiv"
                    else "ISBN:"
                    if candidate["kind"] == "isbn"
                    else ""
                )
                + candidate["value"]
                for candidate in inspection.identifiers
            )
        )
    )
    # Complete embedded records can carry identifiers absent from page text.
    for embedded in complete:
        for work_id in evidence_from_entry(embedded).identifiers.items:
            kind, value = work_id.kind, work_id.value
            if kind in {"doi", "arxiv", "isbn"}:
                candidate = (
                    "arXiv:" if kind == "arxiv" else "ISBN:" if kind == "isbn" else ""
                ) + value
                if candidate not in identifiers:
                    identifiers.append(candidate)
    if not identifiers and len(complete) == 1:
        result["selected_from"] = "embedded_metadata"
        return complete[0], "ready"
    if not identifiers:
        result["reason"] = "no_complete_metadata_or_identifier"
        return None, "unresolved"
    if len(identifiers) > 8:
        result["reason"] = "too_many_identifier_candidates"
        return None, "ambiguous"
    if not online:
        result["reason"] = "identifier_resolution_requires_online"
        return None, "needs_online"
    resolved: list[BibEntry] = []
    attempts: list[dict] = []
    for value in identifiers:
        assert value is not None
        try:
            with cache_scope(cache_file):
                _, entry = importer.prepare_imported_reference(
                    coll.lib,
                    value,
                    dialect=library_dialect(coll.lib),
                    allow_duplicate=True,
                    key_source="provider",
                )
            supported = identifier is not None or title_supported(
                inspection, entry.fields.get("title", "")
            )
            attempts.append(
                {
                    "identifier": value,
                    "title": entry.fields.get("title"),
                    "supported": supported,
                    "entry_type": entry.type,
                    "fields": dict(entry.fields),
                }
            )
            problems = metadata_problems(entry)
            if problems:
                attempts[-1]["metadata_issues"] = problems
            if supported and not problems:
                resolved.append(entry)
        except (importer.ReferenceImportError, ValueError, OSError) as exc:
            attempts.append({"identifier": value, "error": str(exc)})
    result["resolution"] = attempts
    if complete and resolved:
        from pynakes._pdf_evidence import normalized_title

        embedded = complete[0]
        provider = resolved[0]
        differences = {
            name: {"embedded": embedded.fields.get(name), "provider": provider.fields.get(name)}
            for name in embedded.fields.keys() & provider.fields.keys()
            if embedded.fields[name] != provider.fields[name]
            and not (
                name == "title"
                and normalized_title(embedded.fields[name])
                == normalized_title(provider.fields[name])
            )
        }
        if differences or embedded.type != provider.type:
            result.update(
                reason="metadata_disagreement",
                field_choices=differences,
                type_choices=[embedded.type, provider.type],
            )
            return None, "ambiguous"
    if len(resolved) == 1 and not any("error" in attempt for attempt in attempts):
        result["selected_from"] = "user_identifier" if identifier else "identifier_and_title"
        return resolved[0], "ready"
    result["reason"] = (
        "multiple_supported_records" if len(resolved) > 1 else "unverified_or_failed_candidates"
    )
    return None, "ambiguous" if resolved else "unresolved"


def _valid_key(key: str) -> bool:
    return bool(key) and not re.search(r"[\s{},%\\]", key)


def _stage(
    coll: Bibliography,
    inspection: PDFInspection,
    entry: BibEntry,
    key: str | None,
    key_source: str,
    result: dict,
    *,
    managed: bool = True,
    mode: str | None = None,
    role: str | None = None,
) -> None:
    assert coll.path is not None
    candidate = evidence_from_entry(entry)
    exact, probable, conflicts = [], [], []
    for existing in coll.lib.entries.values():
        evidence = evidence_from_entry(existing)
        match = compare_work_evidence(candidate, evidence)
        if match.status == "exact" and {identity_class(entry), identity_class(existing)} == {
            "preprint",
            "published",
        }:
            conflicts.append(existing)
        elif match.status == "exact":
            exact.append(existing)
        elif match.status == "probable":
            probable.append(existing)
        elif match.status == "conflict" and set(candidate.identifiers.items) & set(
            evidence.identifiers.items
        ):
            conflicts.append(existing)
    if len(exact) > 1 or probable or conflicts:
        result.update(
            status="ambiguous",
            reason="existing_work_candidates",
            existing_keys=[e.key for e in [*exact, *probable, *conflicts]],
        )
        return
    if exact:
        target = exact[0]
        if key is not None and target.key != key:
            result.update(
                status="ambiguous",
                reason="existing_work_has_different_key",
                existing_keys=[target.key],
            )
            return
    else:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", entry.type):
            raise ValueError("Invalid embedded entry type")
        if key is not None and key in coll.lib.entries:
            result.update(status="ambiguous", reason="citation_key_conflict", existing_keys=[key])
            return
        convert(BibFile(entries=EntryStore([entry])), library_dialect(coll.lib))
        selected_key = key or unique_key(
            entry.key
            if key_source == "provider" and _valid_key(entry.key)
            else generate_key(entry, coll.lib),
            set(coll.lib.entries.keys()),
        )
        rename_entry_key(entry, selected_key)
        for name, value in entry.fields.items():
            check_field_value(name, value)
        apply_library_style(coll.lib, entry, base_dir=coll.path.parent)
        target = entry
    if managed and coll.files is not None:
        if not exact:
            add_entry_ordered(coll.lib, target)
            coll._appended_entries.append(target)
        try:
            result["adoption"] = coll.adopt_file(target.key, inspection.path, mode=mode, role=role)
        except (OSError, ValueError):
            if not exact:
                coll.lib.entries.remove(target)
                coll._appended_entries.remove(target)
            raise
    else:
        path = Path(inspection.path).as_posix().replace(":", "\\:").replace(";", "\\;")
        descriptor = f":{path}:PDF"
        old = target.fields.get("file", "")
        value = f"{old};{descriptor}" if old else descriptor
        check_field_value("file", value)
        set_entry_field(target, "file", value)
        if not exact:
            add_entry_ordered(coll.lib, target)
            coll._appended_entries.append(target)
    coll._pdf_import_sources.append((Path(inspection.path), inspection.sha256))
    result.update(
        status="linked" if exact else "imported",
        key=target.key,
        title=target.fields.get("title"),
        attachment=result.get("adoption", {}).get("target", inspection.path),
    )
