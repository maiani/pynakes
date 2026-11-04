"""Conservative proper-name protection in sentence-case titles."""

import re

# Case classification is intentionally language-agnostic except for this small
# English stopword list. It is a heuristic, enabled explicitly by the caller.
_STOPWORDS = frozenset("a an and as at by for from in into of on or the to with".split())
_WORD = re.compile(r"[^\W\d_]+(?:[’'][^\W\d_]+)*")
_OPAQUE = re.compile(r"\$[^$]*\$|\\(?:[A-Za-z]+|.)|(?:https?|ftp)://[^\s{}]+")


def protect_sentence_names(value: str) -> str:
    """Protect internal capitalized words when most content words are lowercase.

    The first word must be capitalized. Sentence/subtitle starts after ``: . ? !``
    are excluded, as are existing brace groups, commands, URLs and inline math.
    Braced words still count toward casing so repeated runs remain stable.
    """
    visible = _OPAQUE.sub(lambda match: " " * len(match.group()), value)
    words = list(_WORD.finditer(visible))
    if not words or not words[0].group()[0].isupper():
        return value
    content = [word.group() for word in words[1:] if word.group().lower() not in _STOPWORDS]
    if not content or sum(word.islower() for word in content) <= len(content) / 2:
        return value
    depth = 0
    depths = []
    for index, char in enumerate(value):
        depths.append(depth)
        if char == "{" and (index == 0 or value[index - 1] != "\\"):
            depth += 1
        elif char == "}" and (index == 0 or value[index - 1] != "\\"):
            depth = max(0, depth - 1)
    edits = []
    for previous, word in zip(words, words[1:]):
        token = word.group()
        if (
            token.istitle()
            and token.lower() not in _STOPWORDS
            and depths[word.start()] == 0
            and not re.search(r"[:.?!]", visible[previous.end() : word.start()])
            # Do not protect just the prefix of a word containing a TeX accent.
            and value[word.end() : word.end() + 1] not in ("{", "\\")
            and value[word.start() - 1 : word.start()] not in ("}", "\\")
        ):
            edits.append((word.start(), word.end()))
    for start, end in reversed(edits):
        value = value[:start] + "{" + value[start:end] + "}" + value[end:]
    return value
