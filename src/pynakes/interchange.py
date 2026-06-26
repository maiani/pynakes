"""Bibliography interchange formats: CSL-JSON and RIS (import and export).

Translates between pynakes' BibTeX/BibLaTeX entry model and the two dominant
interchange formats — CSL-JSON (the Zotero/pandoc/citeproc lingua franca) and
RIS (reference-manager and database exports). This is bibliographic-*data*
conversion, distinct from the in-place BibTeX↔BibLaTeX dialect conversion in
:mod:`pynakes.convert`: *export* turns a library into foreign-format text and
*import* parses foreign text into a new :class:`~pynakes.model.BibFile`.

Mappings cover the common entry types and fields. Unmapped fields are dropped
on export (with the rest of the conversion's best effort) rather than guessed.
Conversion is deterministic and offline.
"""

import json

from pynakes.authors import split_name_list
from pynakes.keys import generate_key, unique_key
from pynakes.model import BibEntry, BibFile, EntryStore

FORMATS = ("csl-json", "ris")

# --- entry-type maps -------------------------------------------------------

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

# Bib entry types whose container is a book/proceedings, so an incoming
# "container-title" (CSL) or T2 (RIS) maps to ``booktitle`` rather than ``journal``.
_BOOKTITLE_TYPES = {"incollection", "inbook", "inproceedings", "conference"}

# --- scalar field maps (names and dates handled separately) ----------------

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


# --- shared helpers --------------------------------------------------------


def _split_person(person: str) -> dict[str, str]:
    """Split one BibTeX name into a CSL-style ``{family, given}`` (or literal)."""
    person = person.strip()
    if person.startswith("{") and person.endswith("}"):
        return {"literal": person[1:-1]}
    if person.lower() in {"others", "et al", "et al."}:
        return {"literal": "others"}
    if "," in person:
        family, _, given = person.partition(",")
        return _name_parts(family.strip(), given.strip())
    tokens = person.split()
    if len(tokens) == 1:
        return {"literal": tokens[0]}
    return _name_parts(tokens[-1], " ".join(tokens[:-1]))


def _name_parts(family: str, given: str) -> dict[str, str]:
    parts = {"family": family}
    if given:
        parts["given"] = given
    return parts


def _person_to_bibtex(name: dict) -> str:
    if name.get("literal"):
        return str(name["literal"])
    family = (name.get("family") or "").strip()
    given = (name.get("given") or "").strip()
    return f"{family}, {given}" if given else family


def _names_to_bibtex(names: list) -> str:
    return " and ".join(_person_to_bibtex(n) for n in names if isinstance(n, dict))


def _split_pages(value: str) -> tuple[str, str]:
    """Return ``(start, end)`` from a BibTeX page range, end empty if single."""
    text = value.replace("--", "-").strip()
    if "-" in text:
        start, _, end = text.partition("-")
        return start.strip(), end.strip()
    return text, ""


def _year_of(fields: dict[str, str]) -> str:
    date = fields.get("date") or fields.get("year") or ""
    digits = date.strip()
    return digits[:4] if digits[:4].isdigit() else ""


def _assign_container(fields: dict[str, str], bib_type: str, value: str) -> None:
    """Place an incoming container title into journal or booktitle by type."""
    if not value:
        return
    fields["booktitle" if bib_type in _BOOKTITLE_TYPES else "journal"] = value


# --- CSL-JSON --------------------------------------------------------------


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
        start, end = _split_pages(fields["pages"])
        item["page"] = f"{start}-{end}" if end else start
    for role, csl_role in (("author", "author"), ("editor", "editor")):
        if fields.get(role):
            people = [_split_person(p) for p in split_name_list(fields[role])]
            if people:
                item[csl_role] = people
    year = _year_of(fields)
    if year:
        parts: list[int] = [int(year)]
        month = _month_number(fields.get("month", "")) or _date_part(fields.get("date", ""), 1)
        if month:
            parts.append(int(month))
            day = _date_part(fields.get("date", ""), 2)
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
        _assign_container(fields, bib_type, item["container-title"])
    if isinstance(item.get("page"), str):
        fields["pages"] = item["page"].replace("-", "--")
    for role in ("author", "editor"):
        if isinstance(item.get(role), list):
            names = _names_to_bibtex(item[role])
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


# --- RIS -------------------------------------------------------------------

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
_RIS_TO_BIB_FIELD = {
    "TI": "title",
    "T1": "title",
    "PB": "publisher",
    "CY": "address",
    "VL": "volume",
    "IS": "number",
    "DO": "doi",
    "UR": "url",
    "AB": "abstract",
    "ET": "edition",
    "T3": "series",
    "N1": "note",
    "JO": "journal",
    "JF": "journal",
    "SN": "isbn",
}


def _entry_to_ris(entry: BibEntry) -> list[str]:
    fields = entry.fields
    lines = [f"TY  - {_BIB_TO_RIS_TYPE.get(entry.type.lower(), 'GEN')}"]
    for person in split_name_list(fields.get("author", "")):
        lines.append(f"AU  - {_person_to_bibtex(_split_person(person))}")
    for person in split_name_list(fields.get("editor", "")):
        lines.append(f"ED  - {_person_to_bibtex(_split_person(person))}")
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
        start, end = _split_pages(fields["pages"])
        lines.append(f"SP  - {start}")
        if end:
            lines.append(f"EP  - {end}")
    year = _year_of(fields)
    if year:
        lines.append(f"PY  - {year}")
    for keyword in _split_keywords(fields.get("keywords", "")):
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
        _assign_container(fields, bib_type, container)
    if start:
        fields["pages"] = f"{start}--{end}" if end else start
    if keywords:
        fields["keywords"] = ", ".join(keywords)

    entry = BibEntry(key="", type=bib_type, fields=fields)
    entry.key = unique_key(generate_key(entry), taken)
    taken.add(entry.key)
    return entry


def export_ris(lib: BibFile) -> str:
    records = [
        "\n".join(_entry_to_ris(entry)) for entry in lib.entries.values() if entry.key.strip()
    ]
    return "\n\n".join(records) + ("\n" if records else "")


def import_ris(text: str) -> BibFile:
    store = EntryStore()
    taken: set[str] = set()
    record: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if len(line) >= 6 and line[2:6] == "  - ":
            tag, value = line[:2].strip().upper(), line[6:].strip()
            if tag == "TY":
                record = [(tag, value)]
            elif tag == "ER":
                if record:
                    store.add(_ris_record_to_entry(record, taken))
                record = []
            elif record:
                record.append((tag, value))
    if record:
        store.add(_ris_record_to_entry(record, taken))
    return BibFile(entries=store)


# --- small parsing utilities -----------------------------------------------

_MONTH_NUMBERS = {
    "jan": "1", "feb": "2", "mar": "3", "apr": "4", "may": "5", "jun": "6",
    "jul": "7", "aug": "8", "sep": "9", "oct": "10", "nov": "11", "dec": "12",
}  # fmt: skip


def _month_number(value: str) -> str:
    token = value.strip().strip("{}").lower()[:3]
    if token in _MONTH_NUMBERS:
        return _MONTH_NUMBERS[token]
    digits = value.strip()
    return digits if digits.isdigit() and 1 <= int(digits) <= 12 else ""


def _date_part(date: str, index: int) -> str:
    parts = date.strip().split("-")
    return parts[index] if len(parts) > index and parts[index].isdigit() else ""


def _split_keywords(value: str) -> list[str]:
    separator = ";" if ";" in value else ","
    return [part.strip() for part in value.split(separator) if part.strip()]


# --- dispatch --------------------------------------------------------------


def export_library(lib: BibFile, fmt: str) -> str:
    """Serialize *lib* to the named interchange format."""
    if fmt == "csl-json":
        return export_csl_json(lib)
    if fmt == "ris":
        return export_ris(lib)
    raise ValueError(f"Unsupported export format {fmt!r}; choose one of {', '.join(FORMATS)}")


def import_library(text: str, fmt: str) -> BibFile:
    """Parse interchange-format *text* into a new :class:`BibFile`."""
    if fmt == "csl-json":
        return import_csl_json(text)
    if fmt == "ris":
        return import_ris(text)
    raise ValueError(f"Unsupported import format {fmt!r}; choose one of {', '.join(FORMATS)}")
