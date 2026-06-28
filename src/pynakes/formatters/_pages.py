"""Page-number formatters."""

import re

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
