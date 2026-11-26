"""Explicit metadata decisions and text disclosure for managed ingestion."""

from __future__ import annotations

from pathlib import Path

from pynakes._pdf_evidence import BIB_FIELDS, PDFInspection, document_title_locations
from pynakes._pdf_review import metadata_problems
from pynakes.engine import Bibliography
from pynakes.model import BibEntry
from pynakes.pdf_import import _select_entry

DECISION_KEYS = {
    "sha256",
    "record",
    "identifier",
    "exclude",
    "destination",
    "mode",
    "role",
    "query",
}


def reviewed_entry(decision: dict, result: dict) -> BibEntry | None:
    """Validate a user-accepted record, keeping the decision as field provenance."""
    if decision.keys() - DECISION_KEYS:
        raise ValueError("Unknown ingestion decision fields")
    record = decision.get("record")
    if record is None:
        return None
    if (
        not isinstance(record, dict)
        or set(record) != {"entry_type", "fields"}
        or not isinstance(record["entry_type"], str)
        or not isinstance(record["fields"], dict)
        or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in record["fields"].items()
        )
    ):
        raise ValueError("Reviewed record requires entry_type and string-valued fields")
    entry = BibEntry(key="", type=record["entry_type"], fields=dict(record["fields"]))
    problems = metadata_problems(entry)
    if problems or set(entry.fields) - BIB_FIELDS:
        raise ValueError(f"Invalid reviewed metadata: {problems or 'nonbibliographic fields'}")
    result["selected_from"] = "reviewed_metadata"
    result["field_provenance"] = {name: "reviewed_metadata" for name in entry.fields}
    return entry


def select_entry(
    coll: Bibliography,
    inspection: PDFInspection,
    online: bool,
    decision: dict,
    cache_file: str | Path | None,
    result: dict,
) -> BibEntry | None:
    """Require inspectable document evidence or an explicit hash-bound decision."""
    entry = reviewed_entry(decision, result)
    if entry is not None:
        return entry
    query = decision.get("query")
    if query:
        if not isinstance(query, str):
            raise ValueError("Lookup query must be text")
        result["lookup_query"] = query
        if not online:
            result["reason"] = "text_lookup_requires_online"
            return None
        from pynakes.lookup import find_reference

        result["lookup"] = find_reference(query, cache_file=cache_file).to_dict()
        # Search returns candidates, never a bibliographic acceptance decision.
        if not decision.get("identifier"):
            result["reason"] = "review_lookup_candidates"
            return None
    entry, reason = _select_entry(
        coll, inspection, online, decision.get("identifier"), cache_file, result
    )
    if entry is None:
        result.setdefault("reason", reason)
        return None
    if decision.get("identifier"):
        result["field_provenance"] = {
            name: "reviewed_identifier_resolution" for name in entry.fields
        }
        return entry
    support = document_title_locations(inspection, entry.fields.get("title", ""))
    if not support:
        result["reason"] = "document_title_needs_review"
        return None
    result["title_evidence"] = support
    result["field_provenance"] = {
        name: result.get("selected_from", "document_evidence") for name in entry.fields
    }
    return entry
