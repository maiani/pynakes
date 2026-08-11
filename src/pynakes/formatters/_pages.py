"""Page-number formatters and citation-key page-marker helpers."""

import re

_EM_EN_DASH = re.compile("[–—]")
_DASH_RUN = re.compile(r"[ ]*-+[ ]*")
_DIGIT_RUN = re.compile(r"\d+")
_LEADING_NON_DIGIT = re.compile(r"^\D*")


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


def first_page(value: str) -> str:
    """Return the lowest page number in *value* (JabRef ``firstpage``).

    Scans every digit run in the raw field rather than splitting a single
    range: ``"7,41,73--97"`` returns ``"7"``.
    """
    numbers = [int(match) for match in _DIGIT_RUN.findall(value)]
    return str(min(numbers)) if numbers else ""


def last_page(value: str) -> str:
    """Return the highest page number in *value* (JabRef ``lastpage``)."""
    numbers = [int(match) for match in _DIGIT_RUN.findall(value)]
    return str(max(numbers)) if numbers else ""


def page_prefix(value: str) -> str:
    """Return the non-digit prefix before the first digit (JabRef ``pageprefix``).

    ``"L7"`` returns ``"L"``; a value with no non-digit prefix returns ``""``.
    """
    return _LEADING_NON_DIGIT.match(value).group(0)
