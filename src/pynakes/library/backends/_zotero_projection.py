"""Explicit Zotero-to-citation projection; retain native data at the source."""

from __future__ import annotations

import json
import re

from pynakes._markup import TITLE_LIKE_FIELDS, markup_to_latex
from pynakes.formatters._pages import normalize_page_numbers
from pynakes.identity import evidence_from_entry
from pynakes.library.backends.base import ItemRef, ReferenceView, Revision, SourceUnavailable
from pynakes.model import BibEntry

_TYPES = {
    "journalArticle": "article",
    "book": "book",
    "bookSection": "incollection",
    "conferencePaper": "inproceedings",
    "thesis": "thesis",
    "report": "techreport",
    "preprint": "misc",
    "webpage": "online",
    "manuscript": "unpublished",
}
_FIELDS = {
    "title": "title",
    "DOI": "doi",
    "url": "url",
    "volume": "volume",
    "issue": "number",
    "pages": "pages",
    "publisher": "publisher",
    "place": "address",
    "ISBN": "isbn",
    "ISSN": "issn",
    "edition": "edition",
    "language": "language",
    "abstractNote": "abstract",
    "series": "series",
    "university": "school",
    "institution": "institution",
    "reportNumber": "number",
    "thesisType": "type",
}
_ADMIN = {
    "key",
    "version",
    "itemType",
    "dateAdded",
    "dateModified",
    "collections",
    "relations",
    "tags",
    "creators",
    "date",
    "publicationTitle",
    "bookTitle",
    "proceedingsTitle",
    "repository",
    "archiveID",
    "extra",
}


def project(data: dict, ref: ItemRef, revision: Revision, *, native: bool) -> ReferenceView:
    if not isinstance(data.get("itemType"), str) or not data["itemType"]:
        raise SourceUnavailable("Missing Zotero item type")
    textual = set(_FIELDS) | {
        "itemType",
        "date",
        "publicationTitle",
        "bookTitle",
        "proceedingsTitle",
        "archiveID",
        "repository",
    }
    if any(k in data and not isinstance(data[k], str) for k in textual):
        raise SourceUnavailable("Malformed Zotero bibliographic field")
    creators = data.get("creators", [])
    if not isinstance(creators, list) or any(
        not isinstance(p, dict) or not all(isinstance(v, str) for v in p.values()) for p in creators
    ):
        raise SourceUnavailable("Malformed Zotero creators")
    native_type = data.get("itemType", "")
    entry_type = _TYPES.get(native_type)
    fields: dict[str, str] = {}
    issues = []
    if entry_type is None:
        issues.append(f"Unsupported bibliographic type: {native_type}")
    for source, target in _FIELDS.items():
        if isinstance(value := data.get(source), str) and value:
            fields[target] = value
    for source in ("publicationTitle", "bookTitle", "proceedingsTitle"):
        if data.get(source):
            fields["journal" if native_type == "journalArticle" else "booktitle"] = data[source]
    date = data.get("date", "")
    if date:
        fields["date"] = date
        if match := re.match(r"^([0-9]{4})(?:\b|$)", date):
            fields["year"] = match[1]
        else:
            issues.append("Publication date is not an ISO year/date; preserved as date")
    for role in ("author", "editor"):
        people = []
        for person in data.get("creators", []):
            if person.get("creatorType") != role:
                continue
            if "name" in person:
                people.append("{" + person["name"] + "}")
            else:
                family, given = person.get("lastName", ""), person.get("firstName", "")
                people.append(f"{family}, {given}" if given else family)
        if people:
            fields[role] = " and ".join(people)
    other_roles = sorted(
        {p.get("creatorType", "") for p in data.get("creators", [])} - {"author", "editor"}
    )
    if other_roles:
        issues.append("Unmapped creator roles: " + ", ".join(other_roles))
    if native_type == "preprint" and data.get("archiveID"):
        fields["eprint"] = data["archiveID"]
        fields["archiveprefix"] = data.get("repository", "")
    if data.get("extra"):
        issues.append("Extra is retained in native data; not interpreted as citation metadata")
    if data.get("tags"):
        issues.append("Tags are not copied to project citations")
    if data.get("relations"):
        issues.append("Relations are not copied to project citations")
    unmapped = sorted(k for k, v in data.items() if v and k not in _FIELDS and k not in _ADMIN)
    if unmapped:
        issues.append("Unmapped fields: " + ", ".join(unmapped))
    for name, value in list(fields.items()):
        converted = markup_to_latex(value) if name in TITLE_LIKE_FIELDS else value
        if name == "pages":
            converted = normalize_page_numbers(converted)
        if converted != value:
            fields[name] = converted
            issues.append(f"Converted {name} to citation syntax; native value retained at source")
    if any("<" in v and ">" in v for v in fields.values()):
        issues.append("Remaining markup preserved; review before using as BibTeX")
    evidence = evidence_from_entry(BibEntry(key="", type=entry_type or "misc", fields=fields))
    return ReferenceView(
        ref,
        revision,
        native_type,
        entry_type,
        tuple(fields.items()),
        identifiers=tuple((i.kind, i.value) for i in evidence.identifiers.items),
        issues=tuple(issues),
        native_json=json.dumps(data, ensure_ascii=False) if native else None,
    )
