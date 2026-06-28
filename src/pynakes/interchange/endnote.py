"""EndNote tagged-text import/export."""

from pynakes.interchange._shared import (
    _common_entry_to_format,
    _common_record_to_entry,
    _EntryFormatSpec,
    _export_records,
    _ImportFormatSpec,
    build_bibfile,
)
from pynakes.model import BibEntry, BibFile

_BIB_TO_ENDNOTE_TYPE = {
    "article": "Journal Article",
    "book": "Book",
    "mvbook": "Book",
    "booklet": "Book",
    "inbook": "Book Section",
    "incollection": "Book Section",
    "inproceedings": "Conference Paper",
    "conference": "Conference Paper",
    "proceedings": "Conference Proceedings",
    "phdthesis": "Thesis",
    "mastersthesis": "Thesis",
    "thesis": "Thesis",
    "techreport": "Report",
    "report": "Report",
    "manual": "Book",
    "online": "Web Page",
    "electronic": "Web Page",
    "misc": "Generic",
    "unpublished": "Manuscript",
    "dataset": "Dataset",
    "patent": "Patent",
}
_ENDNOTE_TO_BIB_TYPE = {
    "journal article": "article",
    "book": "book",
    "book section": "incollection",
    "conference paper": "inproceedings",
    "conference proceedings": "proceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "web page": "online",
    "electronic source": "online",
    "manuscript": "unpublished",
    "dataset": "misc",
    "patent": "misc",
    "generic": "misc",
}

_BIB_TO_ENDNOTE_FIELD = {
    "title": "%T",
    "publisher": "%I",
    "address": "%C",
    "location": "%C",
    "volume": "%V",
    "number": "%N",
    "issue": "%N",
    "doi": "%R",
    "url": "%U",
    "abstract": "%X",
    "edition": "%7",
    "series": "%S",
    "note": "%Z",
    "language": "%G",
}
# Auto-generated from _BIB_TO_ENDNOTE_FIELD (stripping the leading '%' from tag names);
# overrides fix collisions and hand-curated extras not present in the forward dict.
# "address"/"location" → "%C" → prefer "address" on import.
# "number"/"issue" → "%N" → prefer "number" on import.
# "%@" is used for isbn/issn on export but "@" maps to isbn on import (extra entry).
_ENDNOTE_TO_BIB_FIELD = {v.lstrip("%"): k for k, v in _BIB_TO_ENDNOTE_FIELD.items()} | {
    "C": "address",
    "N": "number",
    "@": "isbn",
}

_ENDNOTE_ENTRY_SPEC = _EntryFormatSpec(
    type_map=_BIB_TO_ENDNOTE_TYPE,
    default_type="Generic",
    type_fmt="%%0 %s",
    export_key=True,
    key_fmt="%%F %s",
    author_fmt="%%A %s",
    editor_fmt="%%E %s",
    field_map=_BIB_TO_ENDNOTE_FIELD,
    field_line_fmt="%s %s",
    journal_fmt="%%J %s",
    booktitle_fmt="%%B %s",
    isbn_fmt="%%@ %s",
    pages_fn=lambda start, end: [f"%P {start}-{end}" if end else f"%P {start}"],
    year_fmt="%%D %s",
    keyword_fmt="%%K %s",
    terminator=None,
)


def _bib_pages(value: str) -> str:
    text = value.strip()
    if "--" in text:
        return text
    if "-" in text:
        start, _, end = text.partition("-")
        if start.strip() and end.strip():
            return f"{start.strip()}--{end.strip()}"
    return text


_ENDNOTE_IMPORT_SPEC = _ImportFormatSpec(
    type_map=_ENDNOTE_TO_BIB_TYPE,
    default_type="misc",
    type_tag="0",
    type_value_transform=str.lower,
    author_tags=frozenset({"A"}),
    editor_tags=frozenset({"E"}),
    container_tags=frozenset({"B"}),
    journal_tag="J",
    pages_start_tag=None,
    pages_end_tag=None,
    pages_tag="P",
    pages_fn=_bib_pages,
    pages_join=None,
    year_tags=frozenset({"D"}),
    keyword_tag="K",
    field_map=_ENDNOTE_TO_BIB_FIELD,
    preserve_key=True,
    key_tag="F",
)


def _entry_to_endnote(entry: BibEntry) -> list[str]:
    return _common_entry_to_format(entry, _ENDNOTE_ENTRY_SPEC)


def export_endnote(lib: BibFile) -> str:
    """Serialize *lib* as EndNote tagged text."""
    return _export_records(lib, _entry_to_endnote)


def _record_to_entry(record: list[tuple[str, str]], taken: set[str]) -> BibEntry:
    return _common_record_to_entry(record, taken, _ENDNOTE_IMPORT_SPEC)


def _parse_endnote_records(text: str) -> list[list[tuple[str, str]]]:
    """Split raw EndNote tagged text into a list of tag-value records."""
    records: list[list[tuple[str, str]]] = []
    record: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            if record:
                records.append(record)
                record = []
            continue
        if len(line) < 3 or not line.startswith("%"):
            continue
        tag = line[1]
        value = line[3:].strip() if len(line) > 2 else ""
        if tag == "0" and record:
            records.append(record)
            record = []
        record.append((tag, value))
    if record:
        records.append(record)
    return records


def import_endnote(text: str) -> BibFile:
    """Parse EndNote tagged text into a new :class:`BibFile`."""
    return build_bibfile(_parse_endnote_records(text), _record_to_entry)
