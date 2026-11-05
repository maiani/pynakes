"""Read adapter over the existing file-backed Library.

File occurrence identities are snapshot-scoped; native Library ownership and
mutation remain separate from the common read contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from pynakes.bounded import request_digest
from pynakes.engine import ExternalModificationError
from pynakes.identity import evidence_from_entry
from pynakes.library import Library
from pynakes.library.backends.base import (
    ItemRef,
    ReadPage,
    ReferenceView,
    Revision,
    SourceChanged,
    SourceMissing,
    _next_cursor,
    _page_start,
)
from pynakes.model import BibEntry


class BibTeXLibraryBackend:
    """Adapt an existing Library without changing its file-oriented API.

    Missing members remain coverage issues. Reopen the underlying Library to
    refresh. Occurrence IDs reject stale snapshots instead of guessing across
    duplicate keys, external reordering or edits.
    """

    def __init__(self, library: Library) -> None:
        self.library = library
        locator = (
            str(library.manifest)
            if library.manifest
            else json.dumps([str(p) for p in library.members])
        )
        self.source = "bibtex:" + hashlib.sha256(locator.encode()).hexdigest()

    def _revision(self) -> Revision:
        try:
            self.library._assert_current()
        except (OSError, ValueError, ExternalModificationError) as exc:
            raise SourceChanged("File Library changed; reopen it") from exc
        return Revision(self.source, "bibtex/1:" + self.library.source_sha256)

    def describe(self) -> dict:
        revision = self._revision()
        return {
            "backend": "bibtex",
            "source": self.source,
            "revision": asdict(revision),
            "capabilities": {"reads": "supported", "source_writes": "unsupported"},
            "issues": [i.to_dict() for i in self.library.issues],
        }

    def _records(self, revision: Revision, native: bool = False) -> list[ReferenceView]:
        result = []
        for member in self.library._loaded:
            for index, entry in enumerate(member.bib.entries.values()):
                resolved = member.bib.resolved_fields(entry)
                allowed = set(
                    "title author editor year date journal journaltitle booktitle publisher address location series volume number pages doi eprint archiveprefix eprinttype primaryclass url isbn issn edition language abstract school institution type".split()
                )
                fields = {k: v for k, v in resolved.items() if k.lower() in allowed}
                omitted = sorted(set(resolved) - set(fields))
                evidence = evidence_from_entry(
                    BibEntry(key=entry.key, type=entry.type, fields=fields)
                )
                key = json.dumps([str(member.path), member.sha256, index], separators=(",", ":"))
                result.append(
                    ReferenceView(
                        ItemRef(self.source, key),
                        revision,
                        entry.type,
                        entry.type,
                        tuple(fields.items()),
                        entry.key,
                        tuple((i.kind, i.value) for i in evidence.identifiers.items),
                        issues=("Unmapped/private fields omitted: " + ", ".join(omitted),)
                        if omitted
                        else (),
                        native_json=json.dumps(
                            {
                                "type": entry.type,
                                "key": entry.key,
                                "fields": entry.fields,
                                "raw_content": entry.raw_content,
                            }
                        )
                        if native
                        else None,
                    )
                )
        return result

    def scan(self, *, limit: int = 50, cursor: str | None = None) -> ReadPage[ReferenceView]:
        revision = self._revision()
        request = request_digest(backend="bibtex", limit=limit)
        start = _page_start(limit, cursor, revision, request)
        records = self._records(revision)
        page = tuple(records[start : start + limit])
        return ReadPage(
            page,
            revision,
            _next_cursor(start, len(page), len(records), revision, request),
            len(records),
            len(page),
            issues=tuple(i.message for i in self.library.issues),
        )

    def get(
        self, ref: ItemRef, *, expected_revision: Revision | None = None, native: bool = False
    ) -> ReferenceView:
        revision = self._revision()
        if ref.source != self.source or (
            expected_revision is not None and revision != expected_revision
        ):
            raise SourceChanged("Source or revision differs")
        for record in self._records(revision, native):
            if record.ref == ref:
                return record
        raise SourceMissing("Occurrence missing or from an older file snapshot")
