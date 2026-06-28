"""RIS import/export."""

from pynakes.authors import split_name_list
from pynakes.interchange._shared import (
    assign_container,
    assign_key,
    build_bibfile,
    person_to_bibtex,
    split_keywords,
    split_pages,
    split_person,
    year_of,
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


def _entry_to_ris(entry: BibEntry) -> list[str]:
    fields = entry.fields
    lines = [f"TY  - {_BIB_TO_RIS_TYPE.get(entry.type.lower(), 'GEN')}"]
    for person in split_name_list(fields.get("author", "")):
        lines.append(f"AU  - {person_to_bibtex(split_person(person))}")
    for person in split_name_list(fields.get("editor", "")):
        lines.append(f"ED  - {person_to_bibtex(split_person(person))}")
    for name, value in fields.items():
        if not value or not value.strip():
            continue
        tag = _BIB_TO_RIS_FIELD.get(name)
        if tag:
            lines.append(f"{tag}  - {value}")
    container = fields.get("journal") or fields.get("journaltitle")
    if container:
        lines.append(f"JO  - {container}")
    if fields.get("booktitle"):
        lines.append(f"T2  - {fields['booktitle']}")
    if fields.get("isbn"):
        lines.append(f"SN  - {fields['isbn']}")
    elif fields.get("issn"):
        lines.append(f"SN  - {fields['issn']}")
    if fields.get("pages"):
        start, end = split_pages(fields["pages"])
        lines.append(f"SP  - {start}")
        if end:
            lines.append(f"EP  - {end}")
    year = year_of(fields)
    if year:
        lines.append(f"PY  - {year}")
    for keyword in split_keywords(fields.get("keywords", "")):
        lines.append(f"KW  - {keyword}")
    lines.append("ER  - ")
    return lines


def _ris_record_to_entry(record: list[tuple[str, str]], taken: set[str]) -> BibEntry:
    bib_type = "misc"
    fields: dict[str, str] = {}
    authors: list[str] = []
    editors: list[str] = []
    keywords: list[str] = []
    start = end = container = ""
    for tag, value in record:
        if tag == "TY":
            bib_type = _RIS_TO_BIB_TYPE.get(value.upper(), "misc")
        elif tag == "AU" or tag == "A1":
            authors.append(value)
        elif tag == "ED" or tag == "A2":
            editors.append(value)
        elif tag in {"T2", "BT"}:
            container = value
        elif tag == "SP":
            start = value
        elif tag == "EP":
            end = value
        elif tag == "PY" or tag == "Y1":
            year = value.strip()[:4]
            if year.isdigit():
                fields["year"] = year
        elif tag == "KW":
            keywords.append(value)
        elif tag in _RIS_TO_BIB_FIELD:
            fields.setdefault(_RIS_TO_BIB_FIELD[tag], value)
    if authors:
        fields["author"] = " and ".join(authors)
    if editors:
        fields["editor"] = " and ".join(editors)
    if container:
        assign_container(fields, bib_type, container)
    if start:
        fields["pages"] = f"{start}--{end}" if end else start
    if keywords:
        fields["keywords"] = ", ".join(keywords)

    entry = BibEntry(key="", type=bib_type, fields=fields)
    assign_key(entry, taken)
    return entry


def export_ris(lib: BibFile) -> str:
    records = [
        "\n".join(_entry_to_ris(entry)) for entry in lib.entries.values() if entry.key.strip()
    ]
    return "\n\n".join(records) + ("\n" if records else "")


def _parse_ris_records(text: str) -> list[list[tuple[str, str]]]:
    """Split raw RIS text into a list of tag-value records."""
    records: list[list[tuple[str, str]]] = []
    record: list[tuple[str, str]] = []
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
