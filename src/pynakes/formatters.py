"""BibTeX field formatters with JabRef-compatible behavior.

These mirror JabRef's ``saveActions`` field formatters so a JabRef-configured
library normalizes the same way under pynakes (a 1.0 feature-parity goal). Each
formatter is a pure ``str -> str`` transform and keeps the input unchanged when
it does not recognize the value — matching JabRef's "keep if it doesn't match"
behavior.

Algorithms are derived from JabRef (MIT License),
``jablib/src/main/java/org/jabref/logic/formatter/bibtexfields/``:
``NormalizeDateFormatter``, ``NormalizeMonthFormatter``,
``NormalizePagesFormatter``. Parity is asserted in ``tests/test_jabref_parity.py``
against vectors lifted from JabRef's own tests.
"""

import re
from typing import Callable

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


_EM_EN_DASH = re.compile("[–—]")
_DASH_RUN = re.compile(r"[ ]*-+[ ]*")


def normalize_page_numbers(value: str) -> str:
    """Normalize page ranges to ``start--end`` (JabRef ``normalize_page_numbers``).

    Strips ``p.``/``pp.`` prefixes, converts en/em dashes, and rewrites a single
    dash run to ``--``. A value with two or more dash runs is left unchanged
    (it is not a simple range), matching JabRef.
    """
    if not value:
        return value
    v = value.strip()
    v = v.replace("pp.", "").replace("p.", "").strip()
    v = _EM_EN_DASH.sub("--", v)

    matches = list(_DASH_RUN.finditer(v))
    if not matches:
        return v
    if len(matches) >= 2:
        # Multiple dash runs → not a simple range; leave unchanged.
        return v
    m = matches[0]
    fixed = f"{v[: m.start()]}--{v[m.end() :]}"
    # JabRef applies UnprotectTermsFormatter; for page values that means
    # dropping brace protection (e.g. "{1}--{2}" -> "1--2").
    return fixed.replace("{", "").replace("}", "")


# JabRef saveActions formatter key -> pynakes formatter. Author-name
# normalization (``normalize_names``) is handled via the author-style path and
# DOI cleanup via the DOI normalizer, so they are intentionally absent here.
FIELD_FORMATTERS: dict[str, Callable[[str], str]] = {
    "normalize_date": normalize_date,
    "normalize_month": normalize_month,
    "normalize_page_numbers": normalize_page_numbers,
}
