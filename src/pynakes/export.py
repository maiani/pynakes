"""Read-only selection export with explicit bibliography dependencies."""

from collections.abc import Iterable
from dataclasses import dataclass

from pynakes.bibtex_writer import write_bib
from pynakes.interchange import export_library
from pynakes.keys import entry_reference_keys
from pynakes.model import BibEntry, BibFile


@dataclass
class ExportReport:
    """Serialized selection, including dependency additions and warnings."""

    content: str
    selected_entries: int
    exported_entries: int
    dependency_keys: list[str]
    warnings: list[dict]


def export_selection(lib: BibFile, entries: Iterable[BibEntry], fmt: str) -> ExportReport:
    """Export selected physical entries without modifying the source library.

    ``bib`` retains source entry text, all string definitions, preambles and
    library metadata/comments, plus transitive citation-key dependencies in
    source order. Missing references are reported; duplicate dependencies are
    retained with a warning. This is not a scrubbed public release copy.

    Interchange formats export only the selected entries, with inheritance
    resolved against the full source library before applying the codec.
    """
    selected = list(entries)
    original = {id(entry) for entry in lib.entries.values()}
    if any(id(entry) not in original for entry in selected):
        raise ValueError("Export entries must belong to the source library")
    selected_ids = {id(entry) for entry in selected}
    selected = [entry for entry in lib.entries.values() if id(entry) in selected_ids]
    warnings: list[dict] = []
    dependency_keys: list[str] = []
    included = set(selected_ids)
    queue = list(selected)
    seen_refs: set[str] = set()
    for entry in queue:
        for field, key in entry_reference_keys(entry):
            if key in seen_refs:
                continue
            seen_refs.add(key)
            targets = lib.entries.get_all(key)
            if not targets:
                warnings.append(
                    {
                        "type": "missing_export_dependency",
                        "key": entry.key,
                        "field": field,
                        "target": key,
                    }
                )
            if len(targets) > 1:
                warnings.append(
                    {
                        "type": "ambiguous_export_dependency",
                        "target": key,
                        "message": "Referenced key is duplicated; native export retains all instances; interchange inheritance follows the engine's first-match resolution",
                    }
                )
            added = False
            for target in targets:
                if id(target) not in included:
                    included.add(id(target))
                    queue.append(target)
                    added = True
            if added:
                dependency_keys.append(key)
    if fmt != "bib":
        resolved = [
            BibEntry(entry.key, entry.type, lib.resolved_fields(entry)) for entry in selected
        ]
        return ExportReport(
            export_library(lib.derive(resolved), fmt), len(selected), len(selected), [], warnings
        )
    exported = [entry for entry in lib.entries.values() if id(entry) in included]
    content = write_bib(lib.derive(exported)) if exported else ""
    return ExportReport(content, len(selected), len(exported), dependency_keys, warnings)
