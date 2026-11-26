"""Conservative metadata quality checks and attributable PDF review choices."""

from __future__ import annotations

import re

from pynakes.authors import split_name_list
from pynakes.model import BibEntry


def metadata_problems(entry: BibEntry) -> list[str]:
    """Validate bibliographic values, rather than merely their presence."""
    problems = []
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", entry.type):
        problems.append("invalid_entry_type")
    title = entry.fields.get("title", "").strip()
    if len(title) < 8 or title.casefold() in {"untitled", "document", "microsoft word"}:
        problems.append("weak_title")
    creators = entry.fields.get("author") or entry.fields.get("editor", "")
    names = split_name_list(creators)
    if not names or any(
        not any(c.isalpha() for c in n)
        or n.casefold().strip() in {"unknown", "anonymous", "admin", "user"}
        for n in names
    ):
        problems.append("invalid_creators")
    date = entry.fields.get("date") or entry.fields.get("year", "")
    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", date.strip()):
        problems.append("invalid_publication_date")
    elif "-" in date:
        import datetime

        try:
            datetime.date.fromisoformat(date if len(date) == 10 else date + "-01")
        except ValueError:
            problems.append("invalid_publication_date")
    if entry.type in {"book", "mvbook", "inbook"} and not entry.fields.get("publisher"):
        problems.append("book_without_publisher")
    return problems
