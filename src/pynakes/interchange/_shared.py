"""Shared helpers for bibliography interchange codecs."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pynakes._calendar import MONTH_ABBR_TO_NUM as MONTH_NUMBERS
from pynakes.authors import split_name_list
from pynakes.keys import generate_key, unique_key
from pynakes.model import BibEntry, BibFile, EntryStore

# Bib entry types whose container is a book/proceedings, so an incoming
# "container-title" (CSL) or T2 (RIS) maps to ``booktitle`` rather than ``journal``.
BOOKTITLE_TYPES = {"incollection", "inbook", "inproceedings", "conference"}


def split_person(person: str) -> dict[str, str]:
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


def person_to_bibtex(name: dict[str, str]) -> str:
    if name.get("literal"):
        return str(name["literal"])
    family = (name.get("family") or "").strip()
    given = (name.get("given") or "").strip()
    return f"{family}, {given}" if given else family


def names_to_bibtex(names: list[dict[str, str]]) -> str:
    return " and ".join(person_to_bibtex(n) for n in names if isinstance(n, dict))


def split_pages(value: str) -> tuple[str, str]:
    """Return ``(start, end)`` from a BibTeX page range, end empty if single."""
    text = value.replace("--", "-").strip()
    if "-" in text:
        start, _, end = text.partition("-")
        return start.strip(), end.strip()
    return text, ""


def year_of(fields: dict[str, str]) -> str:
    date = fields.get("date") or fields.get("year") or ""
    digits = date.strip()
    return digits[:4] if digits[:4].isdigit() else ""


def assign_container(fields: dict[str, str], bib_type: str, value: str) -> None:
    """Place an incoming container title into journal or booktitle by type."""
    if not value:
        return
    fields["booktitle" if bib_type in BOOKTITLE_TYPES else "journal"] = value


def month_number(value: str) -> str:
    token = value.strip().strip("{}").lower()[:3]
    if token in MONTH_NUMBERS:
        return MONTH_NUMBERS[token]
    digits = value.strip()
    return digits if digits.isdigit() and 1 <= int(digits) <= 12 else ""


def date_part(date: str, index: int) -> str:
    parts = date.strip().split("-")
    return parts[index] if len(parts) > index and parts[index].isdigit() else ""


def split_keywords(value: str) -> list[str]:
    separator = ";" if ";" in value else ","
    return [part.strip() for part in value.split(separator) if part.strip()]


def entry_people(entry: BibEntry, field: str) -> list[dict[str, str]]:
    return [split_person(person) for person in split_name_list(entry.fields.get(field, ""))]


def assign_key(entry: BibEntry, taken: set[str], raw_id: str | None = None) -> None:
    """Assign a unique citation key to *entry*, updating *taken* in place."""
    key = raw_id if raw_id and raw_id.isidentifier() else generate_key(entry)
    entry.key = unique_key(key, taken)
    taken.add(entry.key)


def build_bibfile(records: Iterable[object], converter: Callable[..., BibEntry | None]) -> BibFile:
    """Build a :class:`BibFile` by applying *converter* to each record.

    *converter* must accept ``(record, taken: set[str])`` and return a
    :class:`BibEntry` or ``None`` (skipped entries).
    """
    store = EntryStore()
    taken: set[str] = set()
    for record in records:
        entry = converter(record, taken)
        if entry is not None:
            store.add(entry)
    return BibFile(entries=store)


@dataclass(frozen=True)
class _EntryFormatSpec:
    """Format parameters for serialising one BibEntry to a tagged-line codec."""

    type_map: dict[str, str]
    default_type: str
    type_fmt: str
    export_key: bool
    key_fmt: str | None
    author_fmt: str
    editor_fmt: str
    field_map: dict[str, str]
    field_line_fmt: str
    journal_fmt: str
    booktitle_fmt: str
    isbn_fmt: str
    pages_fn: Callable[[str, str], list[str]]
    year_fmt: str
    keyword_fmt: str
    terminator: str | None


def _common_entry_to_format(entry: BibEntry, spec: _EntryFormatSpec) -> list[str]:
    """Serialize *entry* to a list of tagged lines using *spec*."""
    fields = entry.fields
    lines = [spec.type_fmt % spec.type_map.get(entry.type.lower(), spec.default_type)]
    if spec.export_key and entry.key.strip():
        lines.append(spec.key_fmt % entry.key)
    for person in split_name_list(fields.get("author", "")):
        lines.append(spec.author_fmt % person_to_bibtex(split_person(person)))
    for person in split_name_list(fields.get("editor", "")):
        lines.append(spec.editor_fmt % person_to_bibtex(split_person(person)))
    for name, value in fields.items():
        if not value or not value.strip():
            continue
        tag = spec.field_map.get(name)
        if tag:
            lines.append(spec.field_line_fmt % (tag, value))
    container = fields.get("journal") or fields.get("journaltitle")
    if container:
        lines.append(spec.journal_fmt % container)
    if fields.get("booktitle"):
        lines.append(spec.booktitle_fmt % fields["booktitle"])
    if fields.get("isbn"):
        lines.append(spec.isbn_fmt % fields["isbn"])
    elif fields.get("issn"):
        lines.append(spec.isbn_fmt % fields["issn"])
    if fields.get("pages"):
        start, end = split_pages(fields["pages"])
        lines.extend(spec.pages_fn(start, end))
    year = year_of(fields)
    if year:
        lines.append(spec.year_fmt % year)
    for keyword in split_keywords(fields.get("keywords", "")):
        lines.append(spec.keyword_fmt % keyword)
    if spec.terminator:
        lines.append(spec.terminator)
    return lines


def _export_records(lib: BibFile, entry_to_lines: Callable[[BibEntry], list[str]]) -> str:
    """Serialize *lib* by converting each entry to lines and joining with blank lines."""
    records = [
        "\n".join(entry_to_lines(entry)) for entry in lib.entries.values() if entry.key.strip()
    ]
    return "\n\n".join(records) + ("\n" if records else "")


@dataclass(frozen=True)
class _ImportFormatSpec:
    """Format parameters for parsing one tagged-line record into a BibEntry."""

    type_map: dict[str, str]
    default_type: str
    type_tag: str
    type_value_transform: Callable[[str], str]
    author_tags: frozenset[str]
    editor_tags: frozenset[str]
    container_tags: frozenset[str]
    journal_tag: str | None
    pages_start_tag: str | None
    pages_end_tag: str | None
    pages_tag: str | None
    pages_fn: Callable[[str], str] | None
    pages_join: Callable[[str, str], str | None] | None
    year_tags: frozenset[str]
    keyword_tag: str
    field_map: dict[str, str]
    preserve_key: bool
    key_tag: str | None


def _common_record_to_entry(
    record: list[tuple[str, str]], taken: set[str], spec: _ImportFormatSpec
) -> BibEntry:
    """Parse one tagged-line *record* into a BibEntry using *spec*."""
    bib_type = spec.default_type
    fields: dict[str, str] = {}
    authors: list[str] = []
    editors: list[str] = []
    keywords: list[str] = []
    raw_key = ""
    container = start = end = ""
    for tag, value in record:
        if tag == spec.type_tag:
            bib_type = spec.type_map.get(spec.type_value_transform(value), spec.default_type)
        elif tag in spec.author_tags:
            authors.append(value)
        elif tag in spec.editor_tags:
            editors.append(value)
        elif tag in spec.container_tags:
            container = value
        elif spec.journal_tag and tag == spec.journal_tag:
            fields.setdefault("journal", value)
        elif spec.pages_start_tag and tag == spec.pages_start_tag:
            start = value
        elif spec.pages_end_tag and tag == spec.pages_end_tag:
            end = value
        elif spec.pages_tag and tag == spec.pages_tag:
            result = spec.pages_fn(value) if spec.pages_fn else value
            fields["pages"] = result
        elif tag in spec.year_tags:
            year = value.strip()[:4]
            if year.isdigit():
                fields["year"] = year
        elif tag == spec.keyword_tag:
            keywords.append(value)
        elif spec.key_tag and tag == spec.key_tag:
            raw_key = value.strip()
        elif tag in spec.field_map:
            fields.setdefault(spec.field_map[tag], value)
    if authors:
        fields["author"] = " and ".join(authors)
    if editors:
        fields["editor"] = " and ".join(editors)
    if container:
        assign_container(fields, bib_type, container)
    if spec.pages_join and start:
        pages = spec.pages_join(start, end)
        if pages:
            fields["pages"] = pages
    if keywords:
        fields["keywords"] = ", ".join(keywords)
    entry = BibEntry(key="", type=bib_type, fields=fields)
    assign_key(entry, taken, raw_key if spec.preserve_key else None)
    return entry
