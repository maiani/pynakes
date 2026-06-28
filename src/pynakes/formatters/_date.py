"""Month/date formatters and month data tables."""

import re

_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_FULL = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_MONTH_TO_NUM = {name: i + 1 for i, name in enumerate(_MONTH_ABBR)}
_MONTH_TO_NUM.update({name: i + 1 for i, name in enumerate(_MONTH_FULL)})


def _month_number(token: str) -> int | None:
    """Return 1–12 for a month name/abbreviation, or ``None``."""
    return _MONTH_TO_NUM.get(token.strip().lower().rstrip("."))


# Two-digit month string → BibTeX-idiomatic three-letter abbreviation.
# Used by BibLaTeX→BibTeX date splitting in convert.py.
_MONTH_NUM_TO_ABBR: dict[str, str] = {f"{i + 1:02d}": abbr for i, abbr in enumerate(_MONTH_ABBR)}

# ISO date: year, optional month, optional day.
_ISO_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def month_number_str(value: str) -> str | None:
    """Return ``MM`` (two-digit string) for a recognized month name/number, else ``None``.

    Accepts month names, abbreviations (with or without trailing period), and
    numeric values 1–12. Used by :mod:`pynakes.convert` to fold month names into
    ISO dates.
    """
    token = value.strip().strip("{}").strip().lower()
    n = _MONTH_TO_NUM.get(token)
    if n is not None:
        return f"{n:02d}"
    if token.isdigit() and 1 <= int(token) <= 12:
        return f"{int(token):02d}"
    return None


def _iso(year: str | int, month: str | int, day: str | int | None) -> str | None:
    """Build ``yyyy-mm`` / ``yyyy-mm-dd``, or ``None`` if out of range."""
    m = int(month)
    if not 1 <= m <= 12:
        return None
    if day is None:
        return f"{int(year):04d}-{m:02d}"
    d = int(day)
    if not 1 <= d <= 31:
        return None
    return f"{int(year):04d}-{m:02d}-{d:02d}"


def normalize_date(value: str) -> str:
    """Normalize a date to ``yyyy-mm-dd`` / ``yyyy-mm`` (JabRef ``normalize_date``).

    Recognizes ``yyyy-m-d``, ``yyyy-m``, ``M/yy``, ``M/yyyy``, ``MMMM d, yyyy``,
    ``MMMM, yyyy``, and ``d.M.yyyy``; keeps a ``yyyy/yyyy`` range and anything
    unrecognized unchanged. (Two-digit years map to ``20yy`` deterministically —
    pynakes core takes no dependency on the current date.)
    """
    v = value.strip()
    if re.fullmatch(r"\d{4}/\d{4}", v):  # year range — keep
        return v

    candidates: list[str | None] = []
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v):
        candidates.append(_iso(m.group(1), m.group(2), m.group(3)))
    elif m := re.fullmatch(r"(\d{4})-(\d{1,2})", v):
        candidates.append(_iso(m.group(1), m.group(2), None))
    elif m := re.fullmatch(r"(\d{1,2})/(\d{2})", v):
        candidates.append(_iso(2000 + int(m.group(2)), m.group(1), None))
    elif m := re.fullmatch(r"(\d{1,2})/(\d{4})", v):
        candidates.append(_iso(m.group(2), m.group(1), None))
    elif m := re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", v):
        if (mon := _month_number(m.group(1))) is not None:
            candidates.append(_iso(m.group(3), mon, m.group(2)))
    elif m := re.fullmatch(r"([A-Za-z]+),\s*(\d{4})", v):
        if (mon := _month_number(m.group(1))) is not None:
            candidates.append(_iso(m.group(2), mon, None))
    elif m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", v):
        candidates.append(_iso(m.group(3), m.group(2), m.group(1)))

    for iso in candidates:
        if iso is not None:
            return iso
    return value


def normalize_month(value: str) -> str:
    """Normalize a month to the BibTeX ``#mmm#`` macro (JabRef ``normalize_month``).

    Accepts a 1–12 number, a full month name, a 3-letter abbreviation, or an
    existing ``#mmm#`` macro; keeps anything unrecognized unchanged.
    """
    token = value.strip().strip("#").strip().rstrip(".").lower()
    if token.isdigit():
        n = int(token)
        if 1 <= n <= 12:
            return f"#{_MONTH_ABBR[n - 1]}#"
        return value
    num = _month_number(token)
    return f"#{_MONTH_ABBR[num - 1]}#" if num is not None else value
