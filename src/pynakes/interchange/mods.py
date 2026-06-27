"""MODS XML import/export."""

from xml.etree import ElementTree as ET

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

MODS_NS = "http://www.loc.gov/mods/v3"
NS = {"mods": MODS_NS}
ET.register_namespace("", MODS_NS)

_BIB_TO_MODS_GENRE = {
    "article": "article",
    "book": "book",
    "mvbook": "book",
    "booklet": "book",
    "inbook": "book chapter",
    "incollection": "book chapter",
    "inproceedings": "conference publication",
    "conference": "conference publication",
    "proceedings": "conference publication",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "manual": "book",
    "online": "web site",
    "electronic": "web site",
    "misc": "miscellaneous",
    "unpublished": "manuscript",
    "dataset": "dataset",
    "patent": "patent",
}
_MODS_GENRE_TO_BIB = {
    "article": "article",
    "journal article": "article",
    "book": "book",
    "book chapter": "incollection",
    "conference publication": "inproceedings",
    "conference paper": "inproceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "web site": "online",
    "webpage": "online",
    "manuscript": "unpublished",
    "dataset": "misc",
    "patent": "misc",
    "miscellaneous": "misc",
}


def _q(name: str) -> str:
    return f"{{{MODS_NS}}}{name}"


def _sub(parent: ET.Element, name: str, text: str | None = None, **attrs: str) -> ET.Element:
    elem = ET.SubElement(parent, _q(name), attrs)
    if text is not None:
        elem.text = text
    return elem


def _first_text(parent: ET.Element, path: str) -> str:
    found = parent.find(path, NS)
    return (found.text or "").strip() if found is not None else ""


def _children(parent: ET.Element, local: str) -> list[ET.Element]:
    return [child for child in list(parent) if child.tag.rsplit("}", 1)[-1] == local]


def _entry_to_mods(entry: BibEntry) -> ET.Element:
    fields = entry.fields
    mods = ET.Element(_q("mods"), {"version": "3.7"})
    if entry.key:
        mods.set("ID", entry.key)
    _sub(mods, "genre", _BIB_TO_MODS_GENRE.get(entry.type.lower(), "miscellaneous"))
    if fields.get("title"):
        title_info = _sub(mods, "titleInfo")
        _sub(title_info, "title", fields["title"])
    for role, role_text in (("author", "author"), ("editor", "editor")):
        for person in split_name_list(fields.get(role, "")):
            _add_name(mods, person, role_text)
    _add_origin_info(mods, fields)
    _add_related_item(mods, fields)
    _add_identifiers(mods, fields)
    if fields.get("url"):
        location = _sub(mods, "location")
        _sub(location, "url", fields["url"])
    if fields.get("abstract"):
        _sub(mods, "abstract", fields["abstract"])
    if fields.get("note"):
        _sub(mods, "note", fields["note"])
    if fields.get("language"):
        language = _sub(mods, "language")
        _sub(language, "languageTerm", fields["language"], type="text")
    for keyword in split_keywords(fields.get("keywords", "")):
        subject = _sub(mods, "subject")
        _sub(subject, "topic", keyword)
    return mods


def _add_name(mods: ET.Element, person: str, role_text: str) -> None:
    name = _sub(mods, "name", type="personal")
    split = split_person(person)
    if "literal" in split:
        _sub(name, "namePart", split["literal"])
    else:
        if split.get("family"):
            _sub(name, "namePart", split["family"], type="family")
        if split.get("given"):
            _sub(name, "namePart", split["given"], type="given")
    role = _sub(name, "role")
    _sub(role, "roleTerm", role_text, type="text")


def _add_origin_info(mods: ET.Element, fields: dict[str, str]) -> None:
    origin = _sub(mods, "originInfo")
    if fields.get("publisher"):
        _sub(origin, "publisher", fields["publisher"])
    place = fields.get("address") or fields.get("location")
    if place:
        place_elem = _sub(origin, "place")
        _sub(place_elem, "placeTerm", place, type="text")
    year = year_of(fields)
    if year:
        _sub(origin, "dateIssued", year, encoding="w3cdtf")
    if fields.get("edition"):
        _sub(origin, "edition", fields["edition"])


def _add_related_item(mods: ET.Element, fields: dict[str, str]) -> None:
    container = fields.get("journal") or fields.get("journaltitle") or fields.get("booktitle")
    if not container and not fields.get("series"):
        return
    related = _sub(mods, "relatedItem", type="host")
    if container:
        title_info = _sub(related, "titleInfo")
        _sub(title_info, "title", container)
    if fields.get("series"):
        _sub(related, "partName", fields["series"])
    part = _sub(related, "part")
    for bib_name, detail_type in (("volume", "volume"), ("number", "issue"), ("issue", "issue")):
        if fields.get(bib_name):
            detail = _sub(part, "detail", type=detail_type)
            _sub(detail, "number", fields[bib_name])
    if fields.get("pages"):
        start, end = split_pages(fields["pages"])
        extent = _sub(part, "extent", unit="pages")
        _sub(extent, "start", start)
        if end:
            _sub(extent, "end", end)


def _add_identifiers(mods: ET.Element, fields: dict[str, str]) -> None:
    for bib_name, id_type in (("doi", "doi"), ("isbn", "isbn"), ("issn", "issn")):
        if fields.get(bib_name):
            _sub(mods, "identifier", fields[bib_name], type=id_type)


def export_mods(lib: BibFile) -> str:
    """Serialize *lib* as a MODS collection."""
    root = ET.Element(_q("modsCollection"))
    for entry in lib.entries.values():
        if entry.key.strip():
            root.append(_entry_to_mods(entry))
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def _parse_xml(text: str) -> ET.Element | None:
    if not text.strip():
        return None
    return ET.fromstring(text)


def _mods_records(root: ET.Element) -> list[ET.Element]:
    local = root.tag.rsplit("}", 1)[-1]
    if local == "mods":
        return [root]
    if local == "modsCollection":
        return _children(root, "mods")
    return []


def _mods_to_entry(mods: ET.Element, taken: set[str]) -> BibEntry:
    genre = _first_text(mods, "mods:genre").lower()
    bib_type = _MODS_GENRE_TO_BIB.get(genre, "misc")
    fields: dict[str, str] = {}
    _read_title(mods, fields)
    _read_names(mods, fields)
    _read_origin_info(mods, fields)
    _read_related_item(mods, bib_type, fields)
    _read_identifiers(mods, fields)
    url = _first_text(mods, "mods:location/mods:url")
    if url:
        fields["url"] = url
    for mods_name, bib_name in (("abstract", "abstract"), ("note", "note")):
        value = _first_text(mods, f"mods:{mods_name}")
        if value:
            fields[bib_name] = value
    language = _first_text(mods, "mods:language/mods:languageTerm")
    if language:
        fields["language"] = language
    keywords = [_text(topic) for subject in mods.findall("mods:subject", NS) for topic in subject]
    keywords = [kw for kw in keywords if kw]
    if keywords:
        fields["keywords"] = ", ".join(keywords)

    entry = BibEntry(key="", type=bib_type, fields=fields)
    raw_id = (mods.get("ID") or mods.get("id") or "").strip()
    key = raw_id if raw_id and raw_id.isidentifier() else generate_key(entry)
    entry.key = unique_key(key, taken)
    taken.add(entry.key)
    return entry


def _text(elem: ET.Element) -> str:
    return (elem.text or "").strip()


def _read_title(mods: ET.Element, fields: dict[str, str]) -> None:
    title = _first_text(mods, "mods:titleInfo/mods:title")
    if title:
        fields["title"] = title


def _read_names(mods: ET.Element, fields: dict[str, str]) -> None:
    authors: list[str] = []
    editors: list[str] = []
    for name in mods.findall("mods:name", NS):
        role_terms = [
            _text(term).lower()
            for role in name.findall("mods:role", NS)
            for term in role.findall("mods:roleTerm", NS)
        ]
        target = editors if "editor" in role_terms else authors
        rendered = _render_name(name)
        if rendered:
            target.append(rendered)
    if authors:
        fields["author"] = " and ".join(authors)
    if editors:
        fields["editor"] = " and ".join(editors)


def _render_name(name: ET.Element) -> str:
    family = given = ""
    parts: list[str] = []
    for part in name.findall("mods:namePart", NS):
        value = _text(part)
        if not value:
            continue
        if part.get("type") == "family":
            family = value
        elif part.get("type") == "given":
            given = value
        else:
            parts.append(value)
    if family:
        return person_to_bibtex({"family": family, "given": given})
    return " ".join(parts)


def _read_origin_info(mods: ET.Element, fields: dict[str, str]) -> None:
    origin = mods.find("mods:originInfo", NS)
    if origin is None:
        return
    for mods_path, bib_name in (
        ("mods:publisher", "publisher"),
        ("mods:place/mods:placeTerm", "address"),
        ("mods:edition", "edition"),
    ):
        value = _first_text(origin, mods_path)
        if value:
            fields[bib_name] = value
    date = _first_text(origin, "mods:dateIssued")
    year = date[:4]
    if year.isdigit():
        fields["year"] = year


def _read_related_item(mods: ET.Element, bib_type: str, fields: dict[str, str]) -> None:
    related = mods.find("mods:relatedItem[@type='host']", NS)
    if related is None:
        return
    title = _first_text(related, "mods:titleInfo/mods:title")
    if title:
        assign_container(fields, bib_type, title)
    series = _first_text(related, "mods:partName")
    if series:
        fields["series"] = series
    for detail in related.findall("mods:part/mods:detail", NS):
        value = _first_text(detail, "mods:number")
        if not value:
            continue
        if detail.get("type") == "volume":
            fields["volume"] = value
        elif detail.get("type") == "issue":
            fields["number"] = value
    start = _first_text(related, "mods:part/mods:extent[@unit='pages']/mods:start")
    end = _first_text(related, "mods:part/mods:extent[@unit='pages']/mods:end")
    if start:
        fields["pages"] = f"{start}--{end}" if end else start


def _read_identifiers(mods: ET.Element, fields: dict[str, str]) -> None:
    for identifier in mods.findall("mods:identifier", NS):
        id_type = (identifier.get("type") or "").lower()
        value = _text(identifier)
        if id_type in {"doi", "isbn", "issn"} and value:
            fields[id_type] = value


def import_mods(text: str) -> BibFile:
    """Parse MODS XML into a new :class:`BibFile`."""
    root = _parse_xml(text)
    store = EntryStore()
    taken: set[str] = set()
    if root is None:
        return BibFile(entries=store)
    for mods in _mods_records(root):
        store.add(_mods_to_entry(mods, taken))
    return BibFile(entries=store)
