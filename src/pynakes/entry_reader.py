"""Per-entry records for bounded, comparison-oriented reads.

:class:`EntryReader` turns entries of one :class:`~pynakes.engine.Bibliography`
into the JSON-friendly records that ``ref show --key`` and ``query run`` return.
A record carries either the triage summary (:func:`pynakes.triage.entry_summary`)
or, on request, a projection of exactly the stored fields asked for — the
abstract among them. On request it also *includes* what the library records
about the entry outside its fields:

``materials``
    What can be read for the work: Pinax materials present for the citation key
    (when the library declares ``pinax-files-dir``) and the BibLaTeX ``file``
    links with their resolution status.
``provenance``
    What the library recorded about where things came from: the Pinax manifest
    row for the key (source, dates, access, checksum) and the per-entry
    directives above the entry, with their stated reasons.

Everything is read from existing records, offline. Nothing is inferred,
generated, or scored: a record never contains a judgment about the work.
Absence is reported, not hidden — a selected field the entry lacks is listed
under ``missing_fields``, an included part with nothing recorded under
``missing`` — while a value cut by the text
limit is listed under ``truncated``, so a caller can always tell "the library
has nothing" from "the read left it out".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes.bounded import project_fields, truncate_text
from pynakes.directives import entry_directives
from pynakes.files import parse_file_field, resolve_linked_file
from pynakes.filestore import FileStore
from pynakes.model import BibEntry
from pynakes.triage import entry_summary

if TYPE_CHECKING:
    from pynakes.engine import Bibliography

__all__ = ["INCLUDE_PARTS", "EntryReader", "parse_include"]

#: What a record can include beyond the entry's fields, in report order.
INCLUDE_PARTS = ("materials", "provenance")

_MATERIAL_KINDS = (
    "published_pdf",
    "preprint_pdf",
    "preprint_source",
    "supplement_pdf",
    "erratum_pdf",
)


class EntryReader:
    """Build bounded records for entries of one bibliography.

    The reader opens the Pinax store, its manifest, and the directive index
    once and reuses them for every record, so reading a page of entries costs
    one manifest read rather than one per entry. A problem with one of those
    sources (an unreadable manifest, say) does not fail the read: it is
    reported once in :attr:`warnings`, and the affected part is reported as
    unavailable.
    """

    def __init__(self, coll: Bibliography, *, resolved: bool = False) -> None:
        self.coll = coll
        self.lib = coll.lib
        self.resolved = resolved
        self.warnings: list[dict[str, str]] = []
        self._key_counts = Counter(entry.key for entry in self.lib.entries.values())
        self._bib_path = Path(coll.path).resolve() if coll.path is not None else None
        self._store: FileStore | None = None
        self._manifest: dict[str, object] | None = None
        self._directives: dict[int, list] | None = None
        self._sources_ready = False

    # --- record ---------------------------------------------------------------

    def record(
        self,
        entry: BibEntry,
        *,
        include_abstract: bool = False,
        select: Sequence[str] | None = None,
        include: Sequence[str] = (),
        max_chars: int | None = None,
    ) -> dict[str, object]:
        """Return the bounded record of ``entry``.

        By default the record carries the triage ``summary``; ``include_abstract``
        adds the abstract to it (as the ``--abstract`` flag always has).
        ``select`` replaces the summary with a ``fields`` projection of exactly
        those fields, so a narrow read stays narrow. ``include`` names
        :data:`INCLUDE_PARTS` to add, each under its own key, and every included
        part with nothing recorded is listed under ``missing``. ``max_chars``
        caps every text value in the summary or fields, and every cut is listed
        under ``truncated``.
        """
        fields = self.lib.resolved_fields(entry) if self.resolved else entry.fields
        truncated: dict[str, dict[str, int]] = {}

        record: dict[str, object] = {"key": entry.key, "entry_type": entry.type}
        if self._key_counts[entry.key] > 1:
            record["duplicate_key"] = True

        if select is None:
            summary = entry_summary(entry, fields, include_abstract=include_abstract)
            record["summary"] = {
                name: self._bounded(value, max_chars, f"summary.{name}", truncated)
                for name, value in summary.items()
            }
        else:
            projection = project_fields(fields, select, max_chars)
            record["fields"] = projection.fields
            record["missing_fields"] = projection.missing
            record["omitted_fields"] = projection.omitted
            for name, cut in projection.truncated.items():
                truncated[f"fields.{name}"] = cut.to_dict()

        if include:
            self._prepare_sources()
            missing: list[str] = []
            for part in INCLUDE_PARTS:
                if part not in include:
                    continue
                value, present = (
                    self._materials(entry) if part == "materials" else self._provenance(entry)
                )
                record[part] = value
                if not present:
                    missing.append(part)
            record["missing"] = missing

        record["truncated"] = truncated
        return record

    @staticmethod
    def _bounded(
        value: str | None,
        max_chars: int | None,
        label: str,
        truncated: dict[str, dict[str, int]],
    ) -> str | None:
        if value is None:
            return None
        text, cut = truncate_text(value, max_chars)
        if cut is not None:
            truncated[label] = cut.to_dict()
        return text

    # --- included parts -----------------------------------------------------------

    def _prepare_sources(self) -> None:
        if self._sources_ready:
            return
        self._sources_ready = True
        self._directives = entry_directives(self.lib)
        if self._bib_path is None:
            return
        try:
            self._store = FileStore.from_metadata(self.lib, self._bib_path)
        except (OSError, ValueError) as exc:
            self._warn("pinax_unavailable", f"Pinax materials could not be read: {exc}")
            return
        if self._store is None:
            return
        try:
            self._manifest = self._store.read_manifest()
        except (OSError, ValueError) as exc:
            self._warn("pinax_manifest_unreadable", f"Pinax manifest could not be read: {exc}")

    def _warn(self, kind: str, message: str) -> None:
        warning = {"type": kind, "message": message}
        if warning not in self.warnings:
            self.warnings.append(warning)

    def _materials(self, entry: BibEntry) -> tuple[dict[str, object], bool]:
        linked = []
        for link in parse_file_field(entry):
            if self._bib_path is not None:
                resolve_linked_file(link, self._bib_path, [], self.lib)
            linked.append(
                {
                    "path": link.path,
                    "description": link.description,
                    "kind": link.kind,
                    "status": link.status,
                }
            )
        pinax = self._pinax(entry)
        present = bool(pinax.get("available")) or bool(linked)
        return {"pinax": pinax, "linked_files": linked}, present

    def _pinax(self, entry: BibEntry) -> dict[str, object]:
        if self._store is None:
            return {"configured": False}
        try:
            annotation = self._presence(entry.key)
        except (OSError, ValueError) as exc:
            return {"configured": True, "addressable": False, "reason": str(exc)}
        annotation["configured"] = True
        annotation["addressable"] = True
        return annotation

    def _presence(self, key: str) -> dict[str, object]:
        assert self._store is not None
        presence = self._store.presence_for(key)
        paths = presence.paths
        available = [kind for kind in _MATERIAL_KINDS if getattr(presence, kind)]
        canonical = (
            "published_pdf"
            if presence.published_pdf
            else "preprint_pdf"
            if presence.preprint_pdf
            else None
        )
        return {
            "available": available,
            "paths": {kind: str(getattr(paths, kind)) for kind in available},
            "canonical_pdf": str(getattr(paths, canonical)) if canonical else None,
        }

    def _provenance(self, entry: BibEntry) -> tuple[dict[str, object], bool]:
        recorded: dict[str, object] = {}
        files = self._manifest.get("files") if self._manifest is not None else None
        row = files.get(entry.key) if isinstance(files, dict) else None
        if isinstance(row, dict):
            recorded = {
                kind: dict(row[kind]) for kind in _MATERIAL_KINDS if isinstance(row.get(kind), dict)
            }
        directives = [
            {"verb": directive.verb, "args": list(directive.args), "reason": directive.reason}
            for directive in (self._directives or {}).get(id(entry), [])
        ]
        present = bool(recorded) or bool(directives)
        return {"materials": recorded, "directives": directives}, present


def parse_include(values: Iterable[str] | None) -> tuple[str, ...]:
    """Split repeated/comma-separated ``include`` values into :data:`INCLUDE_PARTS`.

    Returns the parts in report order, each once.

    Raises:
        ValueError: for a name that is not an includable part. ``abstract`` is
            a stored field, so it is pointed at the field selection instead.
    """
    names = [name.strip().lower() for value in values or () for name in value.split(",")]
    names = [name for name in names if name]
    unknown = sorted(set(names) - set(INCLUDE_PARTS))
    if unknown:
        hint = (
            "; the abstract is a stored field: select it (--select abstract)"
            if "abstract" in unknown
            else ""
        )
        raise ValueError(
            f"Cannot include {', '.join(unknown)}: expected {', '.join(INCLUDE_PARTS)}{hint}"
        )
    if values and not names:
        raise ValueError(f"Name at least one of {', '.join(INCLUDE_PARTS)} to include")
    return tuple(part for part in INCLUDE_PARTS if part in names)
