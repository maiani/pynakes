"""Conservative text encoding for stored fields, distinct from display rendering.

Math spans, unknown commands, and grouping/capitalization braces are retained.
Only supported text accents and named text characters are translated.
"""

import re
import unicodedata

_ACCENTS = {
    "'": "\u0301",
    "`": "\u0300",
    "^": "\u0302",
    '"': "\u0308",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "c": "\u0327",
    "k": "\u0328",
    "r": "\u030a",
    "d": "\u0323",
    "b": "\u0331",
}
_SYMBOLS = {
    "aa": "å",
    "AA": "Å",
    "ae": "æ",
    "AE": "Æ",
    "oe": "œ",
    "OE": "Œ",
    "o": "ø",
    "O": "Ø",
    "l": "ł",
    "L": "Ł",
    "ss": "ß",
    "textendash": "–",
    "textemdash": "—",
    "textellipsis": "…",
    "textquoteleft": "‘",
    "textquoteright": "’",
    "textquotedblleft": "“",
    "textquotedblright": "”",
    "textdegree": "°",
    "textcopyright": "©",
    "textregistered": "®",
    "texttrademark": "™",
    "i": "ı",
    "j": "ȷ",
}
_REVERSE_ACCENTS = {mark: command for command, mark in _ACCENTS.items()}
_REVERSE_SYMBOLS = {char: command for command, char in _SYMBOLS.items()}

_TEXT_COMMANDS = {
    "textbf",
    "textit",
    "textrm",
    "textsf",
    "texttt",
    "textsc",
    "textnormal",
    "textup",
    "textsl",
    "emph",
}
_COMMAND = re.compile(r"\\([A-Za-z]+|.)", re.DOTALL)
_ACCENT_ARG = re.compile(r"\s*(?:\{(\\[ij]|[A-Za-zıȷ])\}|(\\[ij](?![A-Za-z])|[A-Za-zıȷ]))")


def _math_end(value: str, start: int) -> int | None:
    for opening, closing in (("$$", "$$"), ("$", "$"), (r"\(", r"\)"), (r"\[", r"\]")):
        if not value.startswith(opening, start):
            continue
        pos = start + len(opening)
        while pos < len(value):
            if value.startswith(closing, pos):
                return pos + len(closing)
            pos += 2 if value[pos] == "\\" else 1
        return len(value)  # An incomplete expression is left intact too.
    return None


def _latex_character(token: str) -> tuple[str, list[str]]:
    """Encode one normalized character cluster, retaining unsupported text."""
    decomposed = unicodedata.normalize("NFD", token)
    if token in _REVERSE_SYMBOLS:
        return "{\\" + _REVERSE_SYMBOLS[token] + "}", []
    if len(decomposed) == 2 and decomposed[0].isascii() and decomposed[1] in _REVERSE_ACCENTS:
        return "{\\" + _REVERSE_ACCENTS[decomposed[1]] + "{" + decomposed[0] + "}}", []
    return token, ["character " + token]


def encode_text(value: str, target: str) -> tuple[str, list[str]]:
    """Convert supported text while returning descriptions of retained constructs."""
    if target not in {"latex", "unicode"}:
        raise ValueError("Field encoding must be latex or unicode")
    output: list[str] = []
    retained: set[str] = set()
    pos = 0
    while pos < len(value):
        end = _math_end(value, pos)
        if end is not None:
            output.append(value[pos:end])
            pos = end
            continue
        command = _COMMAND.match(value, pos)
        if command:
            name = command[1]
            end = command.end()
            if target == "unicode" and name in _ACCENTS:
                argument = _ACCENT_ARG.match(value, end)
                if argument:
                    base = (
                        (argument[1] or argument[2])
                        .replace(r"\i", "i")
                        .replace(r"\j", "j")
                        .replace("ı", "i")
                        .replace("ȷ", "j")
                    )
                    output.append(unicodedata.normalize("NFC", base + _ACCENTS[name]))
                    pos = argument.end()
                    continue
            if target == "unicode" and name in _SYMBOLS:
                output.append(_SYMBOLS[name])
                if value.startswith("{}", end):
                    pos = end + 2
                else:
                    pos = end
                    # TeX consumes whitespace after a bare control word.
                    while pos < len(value) and value[pos].isspace():
                        pos += 1
                continue
            if target == "unicode" and name.isalpha() and name not in _TEXT_COMMANDS:
                retained.add("command \\" + name)
            argument_start = end
            while argument_start < len(value) and value[argument_start].isspace():
                argument_start += 1
            if (
                name.isalpha()
                and name not in _TEXT_COMMANDS
                and argument_start < len(value)
                and value[argument_start] == "{"
            ):
                depth = 1
                cursor = argument_start + 1
                while cursor < len(value) and depth:
                    if value[cursor] == "\\":
                        cursor += 2
                        continue
                    depth += (value[cursor] == "{") - (value[cursor] == "}")
                    cursor += 1
                end = cursor
            output.append(value[pos:end])
            pos = end
            continue
        char = value[pos]
        if target == "latex" and ord(char) > 127:
            # Include decomposed combining accents before normalization.
            end = pos + 1
            while end < len(value) and unicodedata.combining(value[end]):
                end += 1
            token = unicodedata.normalize("NFC", value[pos:end])
            converted, warnings = _latex_character(token)
            output.append(value[pos:end] if warnings else converted)
            retained.update(warnings)
            pos = end
            continue
        # A decomposed ASCII base with a combining accent is handled as a token.
        if target == "latex" and pos + 1 < len(value) and unicodedata.combining(value[pos + 1]):
            end = pos + 2
            while end < len(value) and unicodedata.combining(value[end]):
                end += 1
            token = unicodedata.normalize("NFC", value[pos:end])
            if token != value[pos:end]:
                converted, warnings = encode_text(token, target)
                output.append(converted)
                retained.update(warnings)
                pos = end
                continue
        output.append(char)
        pos += 1
    return "".join(output), sorted(retained)
