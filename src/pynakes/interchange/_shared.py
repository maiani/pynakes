"""Shared helpers for bibliography interchange codecs."""

from pynakes.authors import split_name_list
from pynakes.model import BibEntry

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


def person_to_bibtex(name: dict) -> str:
    if name.get("literal"):
        return str(name["literal"])
    family = (name.get("family") or "").strip()
    given = (name.get("given") or "").strip()
    return f"{family}, {given}" if given else family


def names_to_bibtex(names: list) -> str:
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


MONTH_NUMBERS = {
    "jan": "1", "feb": "2", "mar": "3", "apr": "4", "may": "5", "jun": "6",
    "jul": "7", "aug": "8", "sep": "9", "oct": "10", "nov": "11", "dec": "12",
}  # fmt: skip


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
