"""Case formatters: title_case, sentence_case, capitalize, lower_case, upper_case."""

import re

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


def sentence_case(value: str) -> str:
    """Convert prose to sentence case (JabRef ``sentence_case``)."""
    if not _has_balanced_braces(value):
        return value
    return " ".join(
        _capitalize_first_unprotected_word(lower_case(part)) for part in _sentence_parts(value)
    )


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
