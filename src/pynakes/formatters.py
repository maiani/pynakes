"""BibTeX field formatters with JabRef-compatible behavior.

These mirror JabRef's ``saveActions`` field formatters so a JabRef-configured
library normalizes the same way under pynakes (a 1.0 feature-parity goal). Each
formatter is a pure ``str -> str`` transform and keeps the input unchanged when
it does not recognize the value — matching JabRef's "keep if it doesn't match"
behavior.

Algorithms are derived from JabRef (MIT License),
``jablib/src/main/java/org/jabref/logic/formatter/bibtexfields/``:
``NormalizeDateFormatter``, ``NormalizeMonthFormatter``,
``NormalizePagesFormatter``, ``LatexCleanupFormatter``, and
``HtmlToLatexFormatter`` / ``HtmlToUnicodeFormatter``. Parity is asserted
in ``tests/test_jabref_parity.py`` against vectors lifted from JabRef's own
tests.
"""

import re
import unicodedata
from html import unescape as html_unescape
from html.entities import name2codepoint
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


_UNESCAPED_DOLLAR = re.compile(r"(^|[^\\$])\$")
_EVERY_OTHER_MARKER = re.compile(r"([^@]*)@@([^@]*)@@")
_NUMBER_LEFT_OF_EQUATION = re.compile(r"([0-9(\.]+ ?[-+/]? ?)@@")
_NUMBER_RIGHT_OF_EQUATION = re.compile(r"@@( ?[-+/]? ?[0-9)\.]+)")
_UNESCAPED_PERCENT = re.compile(r"(^|[^\\%])%")


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
_HTML_ENTITY_TO_LATEX = {
    "amp": "&",
    "apos": "'",
    "quot": '"',
    "lt": "<",
    "gt": ">",
    "nbsp": "{~}",
    "copy": r"{\copyright}",
    "reg": r"{\textregistered}",
    "trade": r"{\texttrademark}",
    "pound": r"{\pounds}",
    "euro": r"{\euro}",
    "sect": r"{{\S}}",
    "para": r"{{\P}}",
    "laquo": r"{\guillemotleft}",
    "raquo": r"{\guillemotright}",
    "ndash": "--",
    "mdash": "---",
    "hellip": r"\ldots",
    "times": r"$\times$",
    "divide": r"$\div$",
    "plusmn": r"$\pm$",
    "deg": r"{$^{\circ}$}",
    "micro": r"$\mu$",
    "mu": r"$\mu$",
    "aring": r"{{\aa}}",
    "Aring": r"{{\AA}}",
    "aelig": r"{\ae}",
    "AElig": r"{{\AE}}",
    "oslash": r"{\o}",
    "Oslash": r"{{\O}}",
    "szlig": r"{\ss}",
    "thorn": r"{\th}",
    "THORN": r"{{\TH}}",
    "eth": r"{\dh}",
    "ETH": r"{{\DH}}",
    "alpha": r"$\alpha$",
    "beta": r"$\beta$",
    "gamma": r"$\gamma$",
    "delta": r"$\delta$",
    "epsilon": r"$\epsilon$",
    "Epsilon": r"{{$\Epsilon$}}",
    "Gamma": r"{{$\Gamma$}}",
    "Delta": r"{{$\Delta$}}",
    "Theta": r"{{$\Theta$}}",
    "Lambda": r"{{$\Lambda$}}",
    "Xi": r"{{$\Xi$}}",
    "Pi": r"{{$\Pi$}}",
    "Sigma": r"{{$\Sigma$}}",
    "Upsilon": r"{{$\Upsilon$}}",
    "Phi": r"{{$\Phi$}}",
    "Psi": r"{{$\Psi$}}",
    "Omega": r"{{$\Omega$}}",
}
_HTML_NUMERIC_TO_LATEX = {
    160: r"{~}",
    169: r"{\copyright}",
    174: r"{\textregistered}",
    177: r"$\pm$",
    181: r"$\mu$",
    215: r"$\times$",
    247: r"$\div$",
    8211: "--",
    8212: "---",
    8230: r"\ldots",
}
_HTML_ACCENT_CODES = {
    768: "`",
    769: "'",
    770: "^",
    771: "~",
    772: "=",
    774: "u",
    775: ".",
    776: '"',
    778: "r",
    780: "v",
    803: "d",
    807: "c",
    808: "k",
}

# JabRef maps each of these Latin characters to this spelling, rather than
# through a generic Unicode encoder (which deliberately has fewer braces).
for _letter, _latex in {
    "à": r"{\`{a}}",
    "á": r"{\'{a}}",
    "â": r"{\^{a}}",
    "ã": r"{\~{a}}",
    "ä": r"{\"{a}}",
    "å": r"{{\aa}}",
    "ç": r"{\c{c}}",
    "è": r"{\`{e}}",
    "é": r"{\'{e}}",
    "ê": r"{\^{e}}",
    "ë": r"{\"{e}}",
    "ì": r"{\`{i}}",
    "í": r"{\'{i}}",
    "î": r"{\^{i}}",
    "ï": r"{\"{i}}",
    "ñ": r"{\~{n}}",
    "ò": r"{\`{o}}",
    "ó": r"{\'{o}}",
    "ô": r"{\^{o}}",
    "õ": r"{\~{o}}",
    "ö": r"{\"{o}}",
    "ù": r"{\`{u}}",
    "ú": r"{\'{u}}",
    "û": r"{\^{u}}",
    "ü": r"{\"{u}}",
    "ý": r"{\'{y}}",
    "ÿ": r"{\"{y}}",
    "À": r"{{\`{A}}}",
    "Á": r"{{\'{A}}}",
    "Â": r"{{\^{A}}}",
    "Ã": r"{{\~{A}}}",
    "Ä": r"{{\"{A}}}",
    "Å": r"{{\AA}}",
    "Ç": r"{{\c{C}}}",
    "È": r"{{\`{E}}}",
    "É": r"{{\'{E}}}",
    "Ê": r"{{\^{E}}}",
    "Ë": r"{{\"{E}}}",
    "Ì": r"{{\`{I}}}",
    "Í": r"{{\'{I}}}",
    "Î": r"{{\^{I}}}",
    "Ï": r"{{\"{I}}}",
    "Ñ": r"{{\~{N}}}",
    "Ò": r"{{\`{O}}}",
    "Ó": r"{{\'{O}}}",
    "Ô": r"{{\^{O}}}",
    "Õ": r"{{\~{O}}}",
    "Ö": r"{{\"{O}}}",
    "Ù": r"{{\`{U}}}",
    "Ú": r"{{\'{U}}}",
    "Û": r"{{\^{U}}}",
    "Ü": r"{{\"{U}}}",
    "Ý": r"{{\'{Y}}}",
}.items():
    _HTML_NUMERIC_TO_LATEX[ord(_letter)] = _latex

for _name, _latex in _HTML_ENTITY_TO_LATEX.items():
    if _name in name2codepoint:
        _HTML_NUMERIC_TO_LATEX.setdefault(name2codepoint[_name], _latex)
for _name, _codepoint in name2codepoint.items():
    if _codepoint in _HTML_NUMERIC_TO_LATEX:
        _HTML_ENTITY_TO_LATEX.setdefault(_name, _HTML_NUMERIC_TO_LATEX[_codepoint])


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
    result = _HTML_NUMERIC_ENTITY.sub(
        lambda match: _HTML_NUMERIC_TO_LATEX.get(_html_entity_code(match), match.group(0)), result
    )
    return result.replace("$$", "").strip()


def html_to_unicode(value: str) -> str:
    """Convert HTML4 entities to Unicode and remove tags (JabRef ``html_to_unicode``)."""
    return re.sub(r"<[^>]*>", "", html_unescape(value))


def _has_balanced_braces(value: str) -> bool:
    """Return whether LaTeX brace protection is structurally balanced."""
    depth = 0
    for char in value:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def capitalize(value: str) -> str:
    """Capitalize unprotected words (JabRef ``capitalize``).

    LaTeX brace groups are case-protected verbatim. A malformed brace sequence
    is returned unchanged, matching JabRef's title parser fail-safe behavior.
    """
    if not _has_balanced_braces(value):
        return value

    output: list[str] = []
    protected_depth = 0
    word_start = True
    for char in value:
        if char == "{":
            protected_depth += 1
            if word_start:
                word_start = False
            output.append(char)
        elif char == "}":
            protected_depth -= 1
            output.append(char)
        elif protected_depth:
            output.append(char)
        elif char.isalpha():
            output.append(char.upper() if word_start else char.lower())
            word_start = False
        else:
            output.append(char)
            if char.isspace() or char == "-":
                word_start = True
    return "".join(output)


def lower_case(value: str) -> str:
    """Lowercase unprotected text (JabRef ``lower_case``)."""
    if not _has_balanced_braces(value):
        return value

    output: list[str] = []
    protected_depth = 0
    for char in value:
        if char == "{":
            protected_depth += 1
        elif char == "}":
            protected_depth -= 1
        output.append(char if protected_depth else char.lower())
    return "".join(output)


def upper_case(value: str) -> str:
    """Uppercase unprotected text (JabRef ``upper_case``)."""
    if not _has_balanced_braces(value):
        return value

    output: list[str] = []
    protected_depth = 0
    for char in value:
        if char == "{":
            protected_depth += 1
        elif char == "}":
            protected_depth -= 1
        output.append(char if protected_depth else char.upper())
    return "".join(output)


_SENTENCE_ABBREVIATIONS = {"dr", "mr", "mrs", "ms", "prof", "sr", "jr", "vs", "etc"}
_TITLE_SMALL_WORDS = {
    "a",
    "an",
    "the",
    "above",
    "about",
    "across",
    "against",
    "along",
    "among",
    "around",
    "at",
    "before",
    "behind",
    "below",
    "beneath",
    "beside",
    "between",
    "beyond",
    "by",
    "down",
    "during",
    "except",
    "for",
    "from",
    "in",
    "inside",
    "into",
    "like",
    "near",
    "of",
    "off",
    "on",
    "onto",
    "since",
    "to",
    "toward",
    "through",
    "under",
    "until",
    "up",
    "upon",
    "with",
    "within",
    "without",
    "and",
    "but",
    "nor",
    "or",
    "so",
    "yet",
}
_TITLE_CONJUNCTIONS = {"and", "but", "for", "nor", "or", "so", "yet"}
_TITLE_DASHES = set("-~⸗〰᐀֊־‐‑‒–—―⁓⁻₋−⸺⸻〜゠︱︲﹘﹣－")


def _sentence_parts(value: str) -> list[str]:
    """Split the sentence boundaries used by JabRef's case formatter."""
    parts: list[str] = []
    start = 0
    for index, char in enumerate(value):
        if char not in ".?;" or index + 1 == len(value) or not value[index + 1].isspace():
            continue
        preceding = re.search(r"([A-Za-z]+)$", value[start:index])
        if char == "." and preceding and preceding.group(1).lower() in _SENTENCE_ABBREVIATIONS:
            continue
        part = value[start : index + 1].strip()
        if part:
            parts.append(part)
        start = index + 1
    final_part = value[start:].strip()
    if final_part:
        parts.append(final_part)
    return parts


def _capitalize_first_unprotected_word(value: str) -> str:
    """Uppercase the first letter of the first non-brace-protected word."""
    if value.lstrip().startswith("{"):
        return value
    depth = 0
    for index, char in enumerate(value):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0 and char.isalpha():
            return f"{value[:index]}{char.upper()}{value[index + 1 :]}"
    return value


def sentence_case(value: str) -> str:
    """Convert prose to sentence case (JabRef ``sentence_case``)."""
    if not _has_balanced_braces(value):
        return value
    return " ".join(
        _capitalize_first_unprotected_word(lower_case(part)) for part in _sentence_parts(value)
    )


def _protected_characters(word: str) -> list[bool]:
    depth = 0
    protected: list[bool] = []
    for char in word:
        protected.append(depth > 0)
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return protected


def _title_word_core(word: str, force: bool = False) -> str:
    """Core title-case logic shared by _title_first and _title_word.

    If ``force`` is True (like _title_first), always apply title-case rules.
    If ``force`` is False (like _title_word), first check if the word is a
    small word and lowercase it entirely if so.
    """
    protected = _protected_characters(word)
    chars = list(word)

    if not force and word.replace(":", "").lower() in _TITLE_SMALL_WORDS:
        for index, char in enumerate(chars):
            if not protected[index]:
                chars[index] = char.lower()
        return "".join(chars)

    for index, char in enumerate(chars):
        if protected[index]:
            continue
        next_dash = next(
            (i for i in range(index, len(chars)) if chars[i] in _TITLE_DASHES), len(chars)
        )
        suffix_is_not_conjunction = (
            "".join(chars[index:next_dash]).lower() not in _TITLE_CONJUNCTIONS
        )
        chars[index] = (
            char.upper()
            if index == 0
            or (index > 0 and chars[index - 1] in _TITLE_DASHES and suffix_is_not_conjunction)
            else char.lower()
        )
    return "".join(chars)


def _title_first(word: str) -> str:
    """Capitalize the first letter of the first non-brace-protected word."""
    return _title_word_core(word, force=True)


def _title_word(word: str) -> str:
    """Apply title-case rules with small-word handling."""
    return _title_word_core(word, force=False)


def title_case(value: str) -> str:
    """Convert prose to title case using JabRef's small-word and dash rules."""
    if not _has_balanced_braces(value):
        return value
    sentences: list[str] = []
    for sentence in _sentence_parts(value):
        words = [_title_word(word) for word in sentence.split()]
        if words:
            words[0] = _title_first(words[0])
            words[-1] = _title_first(words[-1])
            for index in range(max(0, len(words) - 2)):
                if words[index].endswith(":"):
                    words[index + 1] = _title_first(words[index + 1])
        sentences.append(" ".join(words))
    return " ".join(sentences)


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


# JabRef saveActions formatter key -> pynakes formatter. Author-name
# normalization (``normalize_names``) is handled via the author-style path and
# DOI cleanup via the DOI normalizer, so they are intentionally absent here.
FIELD_FORMATTERS: dict[str, Callable[[str], str]] = {
    "capitalize": capitalize,
    "html_to_latex": html_to_latex,
    "html_to_unicode": html_to_unicode,
    "latex_cleanup": latex_cleanup,
    "latex_to_unicode": latex_to_unicode,
    "lower_case": lower_case,
    "normalize_date": normalize_date,
    "normalize_month": normalize_month,
    "normalize_page_numbers": normalize_page_numbers,
    "ordinals_to_superscript": ordinals_to_superscript,
    "sentence_case": sentence_case,
    "title_case": title_case,
    "unicode_to_latex": unicode_to_latex,
    "upper_case": upper_case,
    "units_to_latex": units_to_latex,
}
