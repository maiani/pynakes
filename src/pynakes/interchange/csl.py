"""CSL-JSON import/export."""

import json

from pynakes.interchange._shared import (
    assign_container,
    date_part,
    entry_people,
    month_number,
    names_to_bibtex,
    split_pages,
    year_of,
)
from pynakes.keys import generate_key, unique_key
from pynakes.model import BibEntry, BibFile, EntryStore

_BIB_TO_CSL_TYPE = {
    "article": "article-journal",
    "book": "book",
    "mvbook": "book",
    "booklet": "pamphlet",
    "inbook": "chapter",
    "incollection": "chapter",
    "inproceedings": "paper-conference",
    "conference": "paper-conference",
    "proceedings": "book",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "manual": "book",
    "online": "webpage",
    "electronic": "webpage",
    "misc": "document",
    "unpublished": "manuscript",
    "dataset": "dataset",
    "patent": "patent",
}
_CSL_TO_BIB_TYPE = {
    "article-journal": "article",
    "article-magazine": "article",
    "article-newspaper": "article",
    "article": "article",
    "book": "book",
    "pamphlet": "booklet",
    "chapter": "incollection",
    "paper-conference": "inproceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "webpage": "online",
    "manuscript": "unpublished",
    "dataset": "misc",
    "patent": "misc",
    "document": "misc",
}

_BIB_TO_CSL_FIELD = {
    "title": "title",
    "publisher": "publisher",
    "address": "publisher-place",
    "location": "publisher-place",
    "volume": "volume",
    "number": "issue",
    "issue": "issue",
    "doi": "DOI",
    "url": "URL",
    "isbn": "ISBN",
    "issn": "ISSN",
    "note": "note",
    "abstract": "abstract",
    "edition": "edition",
    "series": "collection-title",
    "language": "language",
    "chapter": "chapter-number",
}
_CSL_TO_BIB_FIELD = {
    "title": "title",
    "publisher": "publisher",
    "publisher-place": "address",
    "volume": "volume",
    "issue": "number",
    "DOI": "doi",
    "URL": "url",
    "ISBN": "isbn",
    "ISSN": "issn",
    "note": "note",
    "abstract": "abstract",
    "edition": "edition",
    "collection-title": "series",
    "language": "language",
    "chapter-number": "chapter",
}


def _entry_to_csl(entry: BibEntry) -> dict:
    fields = entry.fields
    item: dict = {
        "id": entry.key,
        "type": _BIB_TO_CSL_TYPE.get(entry.type.lower(), "document"),
    }
    for name, value in fields.items():
        if not value or not value.strip():
            continue
        csl_name = _BIB_TO_CSL_FIELD.get(name)
        if csl_name:
            item[csl_name] = value
    if fields.get("journal") or fields.get("journaltitle") or fields.get("booktitle"):
        item["container-title"] = (
            fields.get("journal") or fields.get("journaltitle") or fields.get("booktitle")
        )
    if fields.get("pages"):
        start, end = split_pages(fields["pages"])
        item["page"] = f"{start}-{end}" if end else start
    for role, csl_role in (("author", "author"), ("editor", "editor")):
        people = entry_people(entry, role)
        if people:
            item[csl_role] = people
    year = year_of(fields)
    if year:
        parts: list[int] = [int(year)]
        month = month_number(fields.get("month", "")) or date_part(fields.get("date", ""), 1)
        if month:
            parts.append(int(month))
            day = date_part(fields.get("date", ""), 2)
            if day:
                parts.append(int(day))
        item["issued"] = {"date-parts": [parts]}
    if fields.get("keywords"):
        item["keyword"] = fields["keywords"]
    return item


def _csl_to_entry(item: dict, taken: set[str]) -> BibEntry:
    bib_type = _CSL_TO_BIB_TYPE.get(str(item.get("type", "")).lower(), "misc")
    fields: dict[str, str] = {}
    for csl_name, value in item.items():
        bib_name = _CSL_TO_BIB_FIELD.get(csl_name)
        if bib_name and isinstance(value, str):
            fields[bib_name] = value
    if isinstance(item.get("container-title"), str):
        assign_container(fields, bib_type, item["container-title"])
    if isinstance(item.get("page"), str):
        fields["pages"] = item["page"].replace("-", "--")
    for role in ("author", "editor"):
        if isinstance(item.get(role), list):
            names = names_to_bibtex(item[role])
            if names:
                fields[role] = names
    issued = item.get("issued")
    if isinstance(issued, dict) and issued.get("date-parts"):
        parts = issued["date-parts"][0]
        if parts:
            fields["year"] = str(parts[0])
    if isinstance(item.get("keyword"), str):
        fields["keywords"] = item["keyword"]

    entry = BibEntry(key="", type=bib_type, fields=fields)
    raw_id = str(item.get("id", "")).strip()
    key = raw_id if raw_id and raw_id.isidentifier() else generate_key(entry)
    entry.key = unique_key(key, taken)
    taken.add(entry.key)
    return entry


def export_csl_json(lib: BibFile) -> str:
    items = [_entry_to_csl(entry) for entry in lib.entries.values() if entry.key.strip()]
    return json.dumps(items, indent=2, ensure_ascii=False)


def import_csl_json(text: str) -> BibFile:
    data = json.loads(text) if text.strip() else []
    if isinstance(data, dict):
        data = [data]
    store = EntryStore()
    taken: set[str] = set()
    for item in data:
        if isinstance(item, dict):
            store.add(_csl_to_entry(item, taken))
    return BibFile(entries=store)
