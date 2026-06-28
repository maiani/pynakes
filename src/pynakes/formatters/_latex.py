"""LaTeX ↔ Unicode ↔ HTML converters."""

import re
import unicodedata
from html import unescape as html_unescape

from pynakes.formatters._latex_tables import (
    _HTML_ACCENT_CODES,
    _HTML_ENTITY_TO_LATEX,
    _HTML_NUMERIC_TO_LATEX,
)

_LATEX_COMMANDS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "i": "ı",
    "L": "Ł",
}
_ACCENT_COMMANDS = {
    '"': "\N{COMBINING DIAERESIS}",
    "'": "\N{COMBINING ACUTE ACCENT}",
    "~": "\N{COMBINING TILDE}",
    "=": "\N{COMBINING MACRON}",
    "c": "\N{COMBINING CEDILLA}",
    "d": "\N{COMBINING DOT BELOW}",
    "k": "\N{COMBINING OGONEK}",
    "v": "\N{COMBINING CARON}",
    "acute": "\N{COMBINING ACUTE ACCENT}",
}
_SUPERSCRIPTS = str.maketrans(
    {
        "0": "⁰",
        "1": "¹",
        "2": "²",
        "3": "³",
        "4": "⁴",
        "5": "⁵",
        "6": "⁶",
        "7": "⁷",
        "8": "⁸",
        "9": "⁹",
        "a": "ᵃ",
        "d": "ᵈ",
        "h": "ʰ",
        "n": "ⁿ",
        "r": "ʳ",
        "s": "ˢ",
        "t": "ᵗ",
    }
)
_ESCAPED_CHARACTERS = {"$", "%", "&", "#", "_", "{", "}", "\\"}
_UNICODE_TO_LATEX = {
    "å": r"{\aa}",
    "ä": r"{\"{a}}",
    "ö": r"{\"{o}}",
    "Å": r"{\AA}",
    "Ä": r"{\"{A}}",
    "Ö": r"{\"{O}}",
    "ı": r"{\i}",
    "ś": r"{{\'{s}}}",
}
_COMBINING_TO_LATEX = {
    "\N{COMBINING ACUTE ACCENT}": "'",
    "\N{COMBINING MACRON}": "=",
    "\N{COMBINING CEDILLA}": "c",
    "\N{COMBINING DOT BELOW}": "d",
    "\N{COMBINING OGONEK}": "k",
    "\N{COMBINING CARON}": "v",
    "\N{COMBINING DIAERESIS}": '"',
}

# --- latex_cleanup helpers ---

_UNESCAPED_DOLLAR = re.compile(r"(^|[^\\$])\$")
_EVERY_OTHER_MARKER = re.compile(r"([^@]*)@@([^@]*)@@")
_NUMBER_LEFT_OF_EQUATION = re.compile(r"([0-9(\.]+ ?[-+/]? ?)@@")
_NUMBER_RIGHT_OF_EQUATION = re.compile(r"@@( ?[-+/]? ?[0-9)\.]+)")
_UNESCAPED_PERCENT = re.compile(r"(^|[^\\%])%")


def _command_argument_before(value: str, closing_brace: int) -> bool:
    """Whether ``closing_brace`` terminates a LaTeX command argument.

    JabRef's variable-length negative lookbehind preserves a boundary such as
    ``\\textbf{VLSI} {DSP}``. Python's regex engine does not support that
    lookbehind, so find the matching opening brace and inspect its prefix
    directly instead.
    """
    depth = 0
    opening_brace = -1
    for index in range(closing_brace, -1, -1):
        char = value[index]
        if char == "}":
            depth += 1
        elif char == "{":
            depth -= 1
            if depth == 0:
                opening_brace = index
                break
    if opening_brace == -1:
        return False
    return bool(re.search(r"\\[A-Za-z]+$", value[:opening_brace]))


def _remove_redundant_brace_boundaries(value: str) -> str:
    """Join adjacent braced terms, preserving LaTeX command arguments."""
    pieces: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "}":
            pieces.append(value[index])
            index += 1
            continue

        separator_end = index + 1
        if separator_end < len(value) and value[separator_end] in "-/ ":
            separator_end += 1
        if (
            separator_end < len(value)
            and value[separator_end] == "{"
            and not _command_argument_before(value, index)
        ):
            pieces.append(value[index + 1 : separator_end])
            index = separator_end + 1
            continue

        pieces.append(value[index])
        index += 1
    return "".join(pieces)


def latex_cleanup(value: str) -> str:
    """Simplify LaTeX syntax (JabRef ``latex_cleanup``).

    This mirrors JabRef v5.15's ``LatexCleanupFormatter``: it joins redundant
    adjacent brace groups, balances equation delimiters while retaining escaped
    dollars, moves neighbouring numeric operators inside math mode, and escapes
    percent signs exactly once.
    """
    cleaned = value.replace("$$", "")
    cleaned = _remove_redundant_brace_boundaries(cleaned)

    # ``@@`` is JabRef's temporary marker for an unescaped math delimiter.
    cleaned = _UNESCAPED_DOLLAR.sub(r"\1@@", cleaned)
    cleaned = _EVERY_OTHER_MARKER.sub(r"\1$\2@@", cleaned)
    cleaned = _NUMBER_LEFT_OF_EQUATION.sub(r"$\1", cleaned)
    cleaned = _NUMBER_RIGHT_OF_EQUATION.sub(r" \1@@", cleaned)
    cleaned = cleaned.replace("@@", "$")
    cleaned = cleaned.replace("  ", " ").replace("$$", "").replace(" )$", ")$")
    return _UNESCAPED_PERCENT.sub(r"\1\\%", cleaned)


# --- LaTeX ↔ Unicode ---


class _LatexParseError(ValueError):
    """Raised when the conservative LaTeX-to-Unicode reader cannot parse input."""


def _braced_content(value: str, opening_brace: int) -> tuple[str, int]:
    """Return the content and first index after a balanced braced group."""
    if opening_brace >= len(value) or value[opening_brace] != "{":
        raise _LatexParseError("expected braced argument")
    depth = 1
    index = opening_brace + 1
    while index < len(value):
        if value[index] == "\\":
            index += 2
            continue
        if value[index] == "{":
            depth += 1
        elif value[index] == "}":
            depth -= 1
            if depth == 0:
                return value[opening_brace + 1 : index], index + 1
        index += 1
    raise _LatexParseError("unbalanced braces")


def _math_italic(value: str) -> str:
    """Render ASCII letters in the Unicode Mathematical Italic alphabet."""
    chars: list[str] = []
    for char in value:
        if "A" <= char <= "Z":
            chars.append(chr(0x1D434 + ord(char) - ord("A")))
        elif "a" <= char <= "z":
            chars.append(chr(0x1D44E + ord(char) - ord("a")))
        else:
            chars.append(char)
    return "".join(chars)


def _latex_to_unicode(value: str) -> str:
    """Convert the supported LaTeX subset, raising on structurally invalid text."""
    output: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "$":
            index += 1  # math-mode delimiters do not appear in Unicode output
            continue
        if char == "~":
            output.append(" ")
            index += 1
            continue
        if char == "_" and index + 1 < len(value) and value[index + 1] == "{":
            content, index = _braced_content(value, index + 1)
            output.append(f"_({_latex_to_unicode(content)})")
            continue
        if char == "{":
            content, index = _braced_content(value, index)
            output.append(_latex_to_unicode(content))
            continue
        if char != "\\":
            output.append(char)
            index += 1
            continue

        command_start = index
        index += 1
        if index >= len(value):
            raise _LatexParseError("trailing escape")
        if value[index] in _ESCAPED_CHARACTERS:
            output.append(value[index])
            index += 1
            continue

        match = re.match(r"[A-Za-z]+", value[index:])
        if match:
            command = match.group(0)
            index += len(command)
        else:
            command = value[index]
            index += 1

        argument_start = index
        while index < len(value) and value[index].isspace():
            index += 1
        has_argument = index < len(value) and value[index] == "{"
        if has_argument:
            raw_argument, argument_end = _braced_content(value, index)
            argument = _latex_to_unicode(raw_argument)
        else:
            raw_argument, argument_end = "", index
            argument = ""

        if command in _LATEX_COMMANDS and not has_argument:
            output.append(_LATEX_COMMANDS[command])
            continue
        if command in _ACCENT_COMMANDS:
            if not has_argument:
                if index >= len(value):
                    raise _LatexParseError("accent without argument")
                raw_argument, argument_end = value[index], index + 1
                argument = _latex_to_unicode(raw_argument)
            output.append(unicodedata.normalize("NFC", argument + _ACCENT_COMMANDS[command]))
            index = argument_end
            continue
        if command == "textit" and has_argument:
            output.append(_math_italic(argument))
            index = argument_end
            continue
        if command == "textsuperscript" and has_argument:
            output.append(argument.translate(_SUPERSCRIPTS))
            index = argument_end
            continue

        # JabRef preserves unknown commands, including their exact braces.
        output.append(value[command_start:argument_start])
        if has_argument:
            output.append(value[argument_start:argument_end])
            index = argument_end
    return "".join(output)


def latex_to_unicode(value: str) -> str:
    """Convert LaTeX text and math mode to Unicode (JabRef ``latex_to_unicode``).

    Unparseable input remains byte-for-byte unchanged, matching JabRef v5.15's
    fail-safe adapter behavior. Known commands and formatting are converted;
    unknown commands are retained rather than discarded.
    """
    try:
        return unicodedata.normalize("NFC", _latex_to_unicode(value))
    except _LatexParseError:
        return value


def unicode_to_latex(value: str) -> str:
    """Convert supported Unicode text to LaTeX (JabRef ``unicode_to_latex``)."""
    normalized = unicodedata.normalize("NFC", value)
    output: list[str] = []
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char in _UNICODE_TO_LATEX:
            output.append(_UNICODE_TO_LATEX[char])
            index += 1
            continue
        decomposed = unicodedata.normalize("NFD", char)
        if len(decomposed) == 2 and decomposed[1] in _COMBINING_TO_LATEX:
            accent = _COMBINING_TO_LATEX[decomposed[1]]
            base = r"\i" if decomposed[0] == "i" else decomposed[0]
            output.append(f"{{\\{accent}{{{base}}}}}")
            index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


# --- HTML ↔ LaTeX / Unicode ---

_HTML_SUPERSCRIPT_TAG = re.compile(r"<[ ]?sup>([^<]+)</sup>")
_HTML_SUBSCRIPT_TAG = re.compile(r"<[ ]?sub>([^<]+)</sub>")
_HTML_TAG = re.compile(r"<[^>]{1,98}>")
_HTML_NAMED_ENTITY = re.compile(r"&(\w+);")
_HTML_NUMERIC_ENTITY = re.compile(r"\\?&#(?:(x)([0-9A-Fa-f]+)|([0-9]+));")
_HTML_COMBINING_ENTITY = re.compile(r"(.)(?:&#(?:(x)([0-9A-Fa-f]+)|([0-9]+));)")


def _html_entity_code(match: re.Match[str]) -> int:
    """Decode one numerical HTML entity matched by the JabRef-compatible patterns."""
    entity = match.group(0)[match.group(0).index("&#") + 2 : -1]
    if entity.startswith("x"):
        return int(entity[1:], 16)
    return int(entity, 10)


def html_to_latex(value: str) -> str:
    """Convert supported HTML markup and entities to LaTeX (JabRef ``html_to_latex``).

    Only entities JabRef v5.15 maps are replaced; unknown entities deliberately
    remain intact. HTML tags are formatting noise except ``sup`` and ``sub``,
    which become their LaTeX text commands.
    """
    result = _HTML_SUPERSCRIPT_TAG.sub(r"\\textsuperscript{\1}", value)
    result = _HTML_SUBSCRIPT_TAG.sub(r"\\textsubscript{\1}", result)
    result = _HTML_TAG.sub("", result)

    result = _HTML_NAMED_ENTITY.sub(
        lambda match: _HTML_ENTITY_TO_LATEX.get(match.group(1), match.group(0)), result
    )

    def replace_combining(match: re.Match[str]) -> str:
        codepoint = _html_entity_code(match)
        accent = _HTML_ACCENT_CODES.get(codepoint)
        if accent is None:
            return match.group(0)
        base = match.group(1)
        if base == "i":
            base = r"\i"
        elif base == "j":
            base = r"\j"
        return f"{{\\{accent}{{{base}}}}}"

    result = _HTML_COMBINING_ENTITY.sub(replace_combining, result)
    return _HTML_NUMERIC_ENTITY.sub(
        lambda match: _HTML_NUMERIC_TO_LATEX.get(_html_entity_code(match), match.group(0)), result
    ).strip()


def html_to_unicode(value: str) -> str:
    """Convert HTML4 entities to Unicode and remove tags (JabRef ``html_to_unicode``)."""
    return re.sub(r"<[^>]*>", "", html_unescape(value))
