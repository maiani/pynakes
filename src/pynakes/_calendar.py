"""Canonical month name/number tables shared across pynakes.

Consolidates month-related data that was previously defined independently in
:mod:`pynakes.model`, :mod:`pynakes.interchange._shared`, and
:mod:`pynakes.formatters._date`.  All three now import from this module,
guaranteeing a single source of truth.
"""

# Three-letter BibTeX month macros (lowercase) mapped to full month names.
# This is the same dict historically exposed as ``COMMON_STRINGS`` in model.py.
MONTH_ABBR_TO_NAME: dict[str, str] = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "may": "May",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}

MONTH_ABBRS: list[str] = list(MONTH_ABBR_TO_NAME)

MONTH_NAMES: list[str] = [name.lower() for name in MONTH_ABBR_TO_NAME.values()]

# Three-letter macro → month number string (1-12, BibTeX-compatible).
# This is the same dict historically exposed as ``MONTH_NUMBERS`` in
# :mod:`pynakes.interchange._shared`.
MONTH_ABBR_TO_NUM: dict[str, str] = {
    "jan": "1",
    "feb": "2",
    "mar": "3",
    "apr": "4",
    "may": "5",
    "jun": "6",
    "jul": "7",
    "aug": "8",
    "sep": "9",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}

# Any month name (three-letter abbreviation or full lowercase) → 1-based int.
_MONTH_TO_NUM: dict[str, int] = {name: i + 1 for i, name in enumerate(MONTH_ABBRS)}
_MONTH_TO_NUM.update({name: i + 1 for i, name in enumerate(MONTH_NAMES)})

# Two-digit month number string → three-letter abbreviation.
MONTH_NUM_TO_ABBR: dict[str, str] = {f"{i + 1:02d}": abbr for i, abbr in enumerate(MONTH_ABBRS)}


def month_name_to_int(token: str) -> int | None:
    """Return 1-12 for a month name/abbreviation, or ``None``."""
    return _MONTH_TO_NUM.get(token.strip().lower().rstrip("."))
