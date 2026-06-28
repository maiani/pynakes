"""Units and ordinal formatters: units_to_latex, ordinals_to_superscript."""

import re

_ORDINAL = re.compile(r"\b(\d+)(st|nd|rd|th)\b", re.IGNORECASE)


def ordinals_to_superscript(value: str) -> str:
    """Convert ordinal suffixes to LaTeX superscripts (JabRef ``ordinals_to_superscript``)."""
    return _ORDINAL.sub(r"\1\\textsuperscript{\2}", value)


_UNITS = (
    "A Ah B Bq C F Gy H Hz J K N $\\Omega$ Pa S Sa Sv T V VA W Wb Wh bar b cd dB dBm dBc "
    "eV inch kat lm lx m mol rad s sr"
).split()
_UNIT_PREFIXES = (
    "y",
    "z",
    "a",
    "f",
    "p",
    "n",
    "$\\mu$",
    "u",
    "m",
    "c",
    "d",
    "",
    "da",
    "h",
    "k",
    "M",
    "G",
    "T",
    "P",
    "E",
    "Z",
    "Y",
)
_UNIT_ALTERNATIVES = sorted(
    {f"{prefix}{unit}" for unit in _UNITS for prefix in _UNIT_PREFIXES}, key=len, reverse=True
)
_UNIT_PATTERN = "|".join(re.escape(unit) for unit in _UNIT_ALTERNATIVES)


def units_to_latex(value: str) -> str:
    """Protect SI-style units and spacing in LaTeX (JabRef ``units_to_latex``)."""
    result = re.sub(r"([0-9,.]+)-([Bb][Ii][Tt])", r"\1\\mbox{-}\2", value)
    result = re.sub(r"([0-9,.]+) ([Bb][Ii][Tt])", r"\1~\2", result)
    result = re.sub(rf"([0-9])({_UNIT_PATTERN})", r"\1{\2}", result)
    result = re.sub(rf"([0-9])-({_UNIT_PATTERN})", r"\1\\mbox{-}{\2}", result)
    return re.sub(rf"([0-9]) ({_UNIT_PATTERN})", r"\1~{\2}", result)
