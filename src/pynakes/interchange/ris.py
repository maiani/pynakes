"""RIS import/export."""

from pynakes.interchange._shared import (
    _common_entry_to_format,
    _common_record_to_entry,
    _EntryFormatSpec,
    _export_records,
    _ImportFormatSpec,
    build_bibfile,
)
from pynakes.model import BibEntry, BibFile

_BIB_TO_RIS_TYPE = {
    "article": "JOUR",
    "book": "BOOK",
    "mvbook": "BOOK",
    "inbook": "CHAP",
    "incollection": "CHAP",
    "inproceedings": "CPAPER",
    "conference": "CPAPER",
    "proceedings": "CONF",
    "phdthesis": "THES",
    "mastersthesis": "THES",
    "thesis": "THES",
    "techreport": "RPRT",
    "report": "RPRT",
    "manual": "BOOK",
    "online": "ELEC",
    "electronic": "ELEC",
    "misc": "GEN",
    "unpublished": "GEN",
    "dataset": "DATA",
    "patent": "PAT",
}
_RIS_TO_BIB_TYPE = {
    "JOUR": "article",
    "BOOK": "book",
    "CHAP": "incollection",
    "CPAPER": "inproceedings",
    "CONF": "proceedings",
    "THES": "phdthesis",
    "RPRT": "techreport",
    "ELEC": "online",
    "DATA": "misc",
    "PAT": "misc",
    "GEN": "misc",
}

_BIB_TO_RIS_FIELD = {
    "title": "TI",
    "publisher": "PB",
    "address": "CY",
    "location": "CY",
    "volume": "VL",
    "number": "IS",
    "issue": "IS",
    "doi": "DO",
    "url": "UR",
    "abstract": "AB",
    "edition": "ET",
    "series": "T3",
    "note": "N1",
}
# Auto-generated from _BIB_TO_RIS_FIELD; overrides fix collisions and expand import vocab.
# "address"/"location" → "CY" → prefer "address" on import.
# "number"/"issue" → "IS" → prefer "number" on import.
# T1, JO, JF, SN are import-only aliases not present in the forward dict.
_RIS_TO_BIB_FIELD = {v: k for k, v in _BIB_TO_RIS_FIELD.items()} | {
    "CY": "address",
    "IS": "number",
    "T1": "title",
    "JO": "journal",
    "JF": "journal",
    "SN": "isbn",
}

_RIS_ENTRY_SPEC = _EntryFormatSpec(
    type_map=_BIB_TO_RIS_TYPE,
    default_type="GEN",
    type_fmt="TY  - %s",
    export_key=False,
    key_fmt=None,
    author_fmt="AU  - %s",
    editor_fmt="ED  - %s",
    field_map=_BIB_TO_RIS_FIELD,
    field_line_fmt="%s  - %s",
    journal_fmt="JO  - %s",
    booktitle_fmt="T2  - %s",
    isbn_fmt="SN  - %s",
    pages_fn=lambda start, end: [f"SP  - {start}"] + ([f"EP  - {end}"] if end else []),
    year_fmt="PY  - %s",
    keyword_fmt="KW  - %s",
    terminator="ER  - ",
)

_RIS_IMPORT_SPEC = _ImportFormatSpec(
    type_map=_RIS_TO_BIB_TYPE,
    default_type="misc",
    type_tag="TY",
    type_value_transform=str.upper,
    author_tags=frozenset({"AU", "A1"}),
    editor_tags=frozenset({"ED", "A2"}),
    container_tags=frozenset({"T2", "BT"}),
    journal_tag=None,
    pages_start_tag="SP",
    pages_end_tag="EP",
    pages_tag=None,
    pages_fn=None,
    pages_join=lambda s, e: f"{s}--{e}" if e else s,
    year_tags=frozenset({"PY", "Y1"}),
    keyword_tag="KW",
    field_map=_RIS_TO_BIB_FIELD,
    preserve_key=True,
    key_tag="ID",
)


def _entry_to_ris(entry: BibEntry) -> list[str]:
    return _common_entry_to_format(entry, _RIS_ENTRY_SPEC)


def _ris_record_to_entry(record: list[tuple[str, str]], taken: set[str]) -> BibEntry:
    return _common_record_to_entry(record, taken, _RIS_IMPORT_SPEC)


def export_ris(lib: BibFile) -> str:
    return _export_records(lib, _entry_to_ris)


def _parse_ris_records(text: str) -> list[list[tuple[str, str]]]:
    """Split raw RIS text into a list of tag-value records."""
    records: list[list[tuple[str, str]]] = []
    record: list[list[tuple[str, str]]] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if len(line) >= 6 and line[2:6] == "  - ":
            tag, value = line[:2].strip().upper(), line[6:].strip()
            if tag == "TY":
                record = [(tag, value)]
            elif tag == "ER":
                if record:
                    records.append(record)
                record = []
            elif record:
                record.append((tag, value))
    if record:
        records.append(record)
    return records


def import_ris(text: str) -> BibFile:
    return build_bibfile(_parse_ris_records(text), _ris_record_to_entry)
