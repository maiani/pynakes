"""EndNote tagged-text import/export."""

from pynakes.authors import split_name_list
from pynakes.interchange._shared import (
    assign_container,
    person_to_bibtex,
    split_keywords,
    split_pages,
    split_person,
    year_of,
)
from pynakes.keys import generate_key, unique_key
from pynakes.model import BibEntry, BibFile, EntryStore

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
_ENDNOTE_TO_BIB_FIELD = {
    "T": "title",
    "I": "publisher",
    "C": "address",
    "V": "volume",
    "N": "number",
    "R": "doi",
    "U": "url",
    "X": "abstract",
    "7": "edition",
    "S": "series",
    "Z": "note",
    "G": "language",
    "@": "isbn",
}


def _entry_to_endnote(entry: BibEntry) -> list[str]:
    fields = entry.fields
    lines = [f"%0 {_BIB_TO_ENDNOTE_TYPE.get(entry.type.lower(), 'Generic')}"]
    if entry.key:
        lines.append(f"%F {entry.key}")
    for person in split_name_list(fields.get("author", "")):
        lines.append(f"%A {person_to_bibtex(split_person(person))}")
    for person in split_name_list(fields.get("editor", "")):
        lines.append(f"%E {person_to_bibtex(split_person(person))}")
    for name, value in fields.items():
        if not value or not value.strip():
            continue
        tag = _BIB_TO_ENDNOTE_FIELD.get(name)
        if tag:
            lines.append(f"{tag} {value}")
    container = fields.get("journal") or fields.get("journaltitle")
    if container:
        lines.append(f"%J {container}")
    if fields.get("booktitle"):
        lines.append(f"%B {fields['booktitle']}")
    if fields.get("isbn"):
        lines.append(f"%@ {fields['isbn']}")
    elif fields.get("issn"):
        lines.append(f"%@ {fields['issn']}")
    if fields.get("pages"):
        start, end = split_pages(fields["pages"])
        lines.append(f"%P {start}-{end}" if end else f"%P {start}")
    year = year_of(fields)
    if year:
        lines.append(f"%D {year}")
    for keyword in split_keywords(fields.get("keywords", "")):
        lines.append(f"%K {keyword}")
    return lines


def export_endnote(lib: BibFile) -> str:
    """Serialize *lib* as EndNote tagged text."""
    records = [
        "\n".join(_entry_to_endnote(entry)) for entry in lib.entries.values() if entry.key.strip()
    ]
    return "\n\n".join(records) + ("\n" if records else "")


def _bib_pages(value: str) -> str:
    text = value.strip()
    if "--" in text:
        return text
    if "-" in text:
        start, _, end = text.partition("-")
        if start.strip() and end.strip():
            return f"{start.strip()}--{end.strip()}"
    return text


def _record_to_entry(record: list[tuple[str, str]], taken: set[str]) -> BibEntry:
    bib_type = "misc"
    fields: dict[str, str] = {}
    authors: list[str] = []
    editors: list[str] = []
    keywords: list[str] = []
    raw_key = ""
    container = ""
    for tag, value in record:
        if tag == "0":
            bib_type = _ENDNOTE_TO_BIB_TYPE.get(value.lower(), "misc")
        elif tag == "F":
            raw_key = value.strip()
        elif tag == "A":
            authors.append(value)
        elif tag == "E":
            editors.append(value)
        elif tag == "B":
            container = value
        elif tag == "J":
            fields.setdefault("journal", value)
        elif tag == "P":
            fields["pages"] = _bib_pages(value)
        elif tag == "D":
            year = value.strip()[:4]
            if year.isdigit():
                fields["year"] = year
        elif tag == "K":
            keywords.append(value)
        elif tag in _ENDNOTE_TO_BIB_FIELD:
            fields.setdefault(_ENDNOTE_TO_BIB_FIELD[tag], value)
    if authors:
        fields["author"] = " and ".join(authors)
    if editors:
        fields["editor"] = " and ".join(editors)
    if container:
        assign_container(fields, bib_type, container)
    if keywords:
        fields["keywords"] = ", ".join(keywords)

    entry = BibEntry(key="", type=bib_type, fields=fields)
    key = raw_key if raw_key and raw_key.isidentifier() else generate_key(entry)
    entry.key = unique_key(key, taken)
    taken.add(entry.key)
    return entry


def import_endnote(text: str) -> BibFile:
    """Parse EndNote tagged text into a new :class:`BibFile`."""
    store = EntryStore()
    taken: set[str] = set()
    record: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip():
            if record:
                store.add(_record_to_entry(record, taken))
                record = []
            continue
        if len(line) < 3 or not line.startswith("%"):
            continue
        tag, value = line[1], line[3:].strip() if len(line) > 3 else ""
        if tag == "0" and record:
            store.add(_record_to_entry(record, taken))
            record = []
        record.append((tag, value))
    if record:
        store.add(_record_to_entry(record, taken))
    return BibFile(entries=store)
