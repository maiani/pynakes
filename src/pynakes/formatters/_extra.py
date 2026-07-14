"""Additional JabRef-compatible field formatters.

These complete the JabRef v5.15 ``saveActions`` formatter suite.  Each
formatter is a pure ``str -> str`` transform.  Algorithms are derived from
JabRef (MIT License).
"""

from __future__ import annotations

import re

from pynakes._identifiers import normalize_doi
from pynakes.authors import is_fully_braced, split_name_list


def clear(value: str) -> str:
    """Clear the field value entirely.

    JabRef's ``ClearFormatter`` replaces the value with an empty string.
    """
    return ""


_ESCAPE_UNDERSCORES_RE = re.compile(r"(?<!\\)_")
_ESCAPE_AMPERSANDS_RE = re.compile(r"(?<!\\)&")


def escape_underscores(value: str) -> str:
    """Escape unprotected underscores with a backslash.

    BibTeX treats ``_`` as a subscript operator in math mode.  Protects
    literal underscores that are not already escaped.
    """
    return _ESCAPE_UNDERSCORES_RE.sub(r"\\_", value)


def escape_ampersands(value: str) -> str:
    """Escape unprotected ampersands with a backslash.

    BibTeX treats ``&`` as a column separator in tabular environments.
    Protects literal ampersands that are not already escaped.
    """
    return _ESCAPE_AMPERSANDS_RE.sub(r"\\&", value)


def cleanup_url(value: str) -> str:
    """Clean up a URL value.

    Strips surrounding whitespace and angle brackets, removes trailing
    periods or commas, and normalizes the scheme to lowercase.  Returns
    the value unchanged when it does not look like a URL.
    """
    cleaned = value.strip()
    # Strip surrounding angle brackets or braces.
    if (cleaned.startswith("<") and cleaned.endswith(">")) or (
        cleaned.startswith("{") and cleaned.endswith("}")
    ):
        cleaned = cleaned[1:-1].strip()
    scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", cleaned)
    if scheme is None:
        return value
    # Remove trailing punctuation that is not part of the URL.
    while cleaned and cleaned[-1] in ".,;:":
        cleaned = cleaned[:-1]
    if not cleaned:
        return value
    # Normalize scheme to lowercase.
    cleaned = scheme.group(1).lower() + cleaned[scheme.end(1) :]
    return cleaned


def remove_braces(value: str) -> str:
    """Remove outermost brace groups from a field value.

    Strips one level of ``{...}`` wrapping when the entire value is enclosed
    in braces.  Does not touch inner braces (e.g. ``{DNA}`` in title
    protection) or concatenated values (``#``).
    """
    stripped = value.strip()
    return stripped[1:-1] if is_fully_braced(stripped) else value


def unprotect_terms(value: str) -> str:
    """Remove term-protection braces from a field value.

    JabRef wraps terms in ``{...}`` to prevent case change.  This
    formatter strips those protection braces, leaving the inner text.
    Only removes braces that surround an entire whitespace-delimited
    token or the entire value.
    """
    # Remove braces around the entire value.
    result = remove_braces(value)
    if result != value:
        return result
    # Remove braces around individual tokens.
    tokens = value.split()
    changed = False
    new_tokens: list[str] = []
    for token in tokens:
        stripped = token.strip()
        if len(stripped) >= 2 and stripped[0] == "{" and stripped[-1] == "}":
            inner = stripped[1:-1]
            if "{" not in inner and "}" not in inner:
                new_tokens.append(inner)
                changed = True
                continue
        new_tokens.append(token)
    return " ".join(new_tokens) if changed else value


def minify_name_list(value: str) -> str:
    """Minify an author/editor name list.

    Collapses multiple consecutive separators (``and``) into single ones,
    strips leading/trailing separators, and normalizes whitespace.
    """
    return " and ".join(part.strip() for part in split_name_list(value) if part.strip())


def clean_up_doi(value: str) -> str:
    """Clean up a DOI value.

    Strips the ``doi:`` prefix, URL wrapper (``http://dx.doi.org/``,
    ``https://doi.org/``), angle brackets, and surrounding whitespace.
    Returns the value unchanged when it does not look like a DOI.
    """
    try:
        return normalize_doi(value)
    except ValueError:
        return value
