"""The shared ``--where`` selector grammar.

One grammar, one parser, one predicate object, used by every entry-addressable
surface: ``fields --where``, ``search --where``, ``format --where``, and the
corpus operations (``corpus combine --where``, ``corpus split --to`` rules).
Keeping the grammar in one module — rather than re-deriving a filter per
command — is what makes a selector written for one command valid for the rest.

Grammar::

    expression := or
    or         := and { "or" and }
    and        := unary { "and" unary }
    unary      := "not" unary | "(" expression ")" | predicate
    predicate  := "*" | "used" | "unused" | "group" VALUE
                | FIELD ("exists" | "missing")
                | FIELD ["not"] "in" "[" VALUE { "," VALUE } "]"
                | FIELD OP VALUE
    OP         := "contains" | "matches" | "~" | "=" | "==" | "!="
                | ">" | ">=" | "<" | "<="
    VALUE      := '"' text '"' | "'" text "'" | bare-token

``and`` binds tighter than ``or``; parentheses group explicitly. Comparisons are
case-insensitive. ``>``/``>=``/``<``/``<=`` compare numerically when both sides
are numbers, as partial dates (``YYYY[-MM[-DD]]``) when both sides are dates,
and as text otherwise, so ``year >= 2025`` and ``date >= 2020-06`` mean what a
reader expects. A comparison against a field an entry does not have is false —
except ``!=`` and ``missing``, which are true.

The special fields are ``key`` (citation key), ``type`` (entry type), ``year``
(falls back to the year inside ``date``), and ``date`` (falls back to a date
composed from ``year``/``month``/``day``). ``group "Name"`` tests JabRef group
membership; the stored field is reachable as ``groups``.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from pynakes._calendar import month_name_to_int
from pynakes._text_utils import _normalize_text, entry_year
from pynakes.groups import entry_groups
from pynakes.model import BibEntry

__all__ = [
    "FUZZY_THRESHOLD",
    "WHERE_GRAMMAR",
    "All",
    "And",
    "Comparison",
    "Group",
    "InSet",
    "Node",
    "Not",
    "Or",
    "Used",
    "field_value",
    "fuzzy_score",
    "parse_query",
]

#: Minimum similarity for a fuzzy (``~``) match, on a 0–1 scale.
FUZZY_THRESHOLD = 0.8

#: Fuzzy matching of very short needles is noise, so they must match exactly.
_MIN_FUZZY_LENGTH = 4

_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_YEAR_RE = re.compile(r"\d{4}")

_ORDER_OPS: dict[str, Callable[[object, object], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}
_TEXT_OPS = ("contains", "matches", "fuzzy")
_WORD_OPERATORS = frozenset({"contains", "matches", "fuzzy", "exists", "missing", "in", "not"})


# --- value access ----------------------------------------------------------


def _stored_value(entry: BibEntry, name: str) -> str | None:
    """Return a stored field value, matched case-insensitively."""
    value = entry.fields.get(name)
    if value is not None:
        return value
    for stored, candidate in entry.fields.items():
        if stored.lower() == name:
            return candidate
    return None


def _derived_date(entry: BibEntry) -> str | None:
    """Compose ``YYYY[-MM[-DD]]`` from ``year``/``month``/``day``, when possible."""
    year_match = _YEAR_RE.search(_stored_value(entry, "year") or "")
    if year_match is None:
        return None
    parts = [year_match.group(0)]
    month = _month_number(_stored_value(entry, "month") or "")
    if month is not None:
        parts.append(f"{month:02d}")
        day = (_stored_value(entry, "day") or "").strip()
        if day.isdigit():
            parts.append(f"{int(day):02d}")
    return "-".join(parts)


def _month_number(value: str) -> int | None:
    token = value.strip().strip("{}").strip()
    if token.isdigit() and 1 <= int(token) <= 12:
        return int(token)
    return month_name_to_int(token)


def field_value(entry: BibEntry, name: str) -> str | None:
    """Return the selector value of field ``name``, or ``None`` when absent.

    ``name`` is expected lower-case. Besides stored fields this resolves the
    special fields documented for the grammar: ``key``, ``type``, ``year``, and
    ``date``.
    """
    if name == "key":
        return entry.key
    if name in ("type", "entrytype"):
        return entry.type
    stored = _stored_value(entry, name)
    if stored is not None:
        return stored
    if name == "year":
        return entry_year(entry) or None
    if name == "date":
        return _derived_date(entry)
    return None


# --- fuzzy matching --------------------------------------------------------


def fuzzy_score(haystack: str, needle: str) -> float:
    """Return how strongly ``needle`` occurs in ``haystack``, from 0 to 1.

    Both sides are normalized first (the shared dedupe/journal normalization:
    case-folded, brace- and punctuation-free), so LaTeX protection and
    punctuation never decide a match. A normalized substring scores 1.0;
    otherwise the score is the best of whole-string similarity, per-word
    similarity, and same-length word-window similarity, which is what lets
    ``"quantom computting"`` still find *Quantum Computing*.
    """
    left = _normalize_text(needle)
    right = _normalize_text(haystack)
    if not left or not right:
        return 0.0
    if left in right:
        return 1.0
    if len(left) < _MIN_FUZZY_LENGTH:
        return 0.0

    needles = left.split()
    tokens = right.split()
    scores = [SequenceMatcher(None, left, right).ratio()]
    if needles and tokens:
        scores.append(
            sum(
                max(SequenceMatcher(None, word, token).ratio() for token in tokens)
                for word in needles
            )
            / len(needles)
        )
        size = len(needles)
        if size > 1:
            for start in range(0, max(0, len(tokens) - size) + 1):
                window = " ".join(tokens[start : start + size])
                scores.append(SequenceMatcher(None, left, window).ratio())
    return max(scores)


# --- predicate nodes -------------------------------------------------------


class Node:
    """A compiled ``--where`` expression.

    Nodes are callable, so any node is usable directly as the ``where``
    predicate of the operations in :mod:`pynakes.fields` and
    :mod:`pynakes.search`. :meth:`to_dict` renders the parsed structure for
    machine-readable output.
    """

    def matches(self, entry: BibEntry) -> bool:
        """Return whether ``entry`` satisfies this expression."""
        raise NotImplementedError

    def __call__(self, entry: BibEntry) -> bool:
        """Evaluate the expression against ``entry`` (see :meth:`matches`)."""
        return self.matches(entry)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly description of the parsed expression."""
        raise NotImplementedError


@dataclass(frozen=True)
class All(Node):
    """The catch-all ``*`` predicate."""

    def matches(self, entry: BibEntry) -> bool:
        """Return ``True`` for every entry."""
        return True

    def to_dict(self) -> dict[str, object]:
        """Describe the catch-all predicate."""
        return {"predicate": "*"}


@dataclass(frozen=True)
class Used(Node):
    """The ``used`` / ``unused`` predicate over a set of cited keys."""

    keys: frozenset[str]
    negate: bool = False

    def matches(self, entry: BibEntry) -> bool:
        """Return whether the entry's key is (or is not) cited."""
        return (entry.key in self.keys) != self.negate

    def to_dict(self) -> dict[str, object]:
        """Describe the cited-key predicate."""
        return {"predicate": "unused" if self.negate else "used"}


@dataclass(frozen=True)
class Group(Node):
    """The ``group "Name"`` JabRef group-membership predicate."""

    name: str

    def matches(self, entry: BibEntry) -> bool:
        """Return whether the entry belongs to the named group."""
        return self.name in entry_groups(entry)

    def to_dict(self) -> dict[str, object]:
        """Describe the group predicate."""
        return {"predicate": "group", "name": self.name}


@dataclass(frozen=True)
class Comparison(Node):
    """One field predicate: an operator applied to a field and (usually) a value."""

    field: str
    op: str
    value: str | None = None

    def __post_init__(self) -> None:
        """Precompile the pattern of a ``matches`` predicate."""
        if self.op == "matches":
            try:
                pattern = re.compile(self.value or "", re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Invalid regular expression {self.value!r}: {exc}") from exc
            object.__setattr__(self, "_pattern", pattern)

    def matches(self, entry: BibEntry) -> bool:
        """Evaluate this field predicate against ``entry``."""
        value = field_value(entry, self.field)
        if self.op == "exists":
            return value is not None
        if self.op == "missing":
            return value is None or not value.strip()
        if value is None:
            # An absent field satisfies only the negative comparison.
            return self.op == "!="
        needle = self.value or ""
        if self.op == "contains":
            return needle.casefold() in value.casefold()
        if self.op == "matches":
            return bool(self._pattern.search(value))  # type: ignore[attr-defined]
        if self.op == "fuzzy":
            return fuzzy_score(value, needle) >= FUZZY_THRESHOLD
        if self.op in ("=", "=="):
            return value.casefold() == needle.casefold()
        if self.op == "!=":
            return value.casefold() != needle.casefold()
        return _ordered_compare(self.op, value, needle)

    def to_dict(self) -> dict[str, object]:
        """Describe this field predicate."""
        described: dict[str, object] = {"field": self.field, "op": self.op}
        if self.op not in ("exists", "missing"):
            described["value"] = self.value
        return described


@dataclass(frozen=True)
class InSet(Node):
    """The ``FIELD in [a, b, …]`` membership predicate."""

    field: str
    values: tuple[str, ...]
    negate: bool = False

    def matches(self, entry: BibEntry) -> bool:
        """Return whether the field value is (or is not) one of the listed values."""
        value = field_value(entry, self.field)
        if value is None:
            return self.negate
        folded = value.casefold()
        present = any(folded == candidate.casefold() for candidate in self.values)
        return present != self.negate

    def to_dict(self) -> dict[str, object]:
        """Describe the membership predicate."""
        return {
            "field": self.field,
            "op": "not in" if self.negate else "in",
            "values": list(self.values),
        }


@dataclass(frozen=True)
class Not(Node):
    """Logical negation of one expression."""

    child: Node

    def matches(self, entry: BibEntry) -> bool:
        """Return the negation of the child expression."""
        return not self.child.matches(entry)

    def to_dict(self) -> dict[str, object]:
        """Describe the negation."""
        return {"not": self.child.to_dict()}


@dataclass(frozen=True)
class And(Node):
    """Conjunction of two or more expressions."""

    children: tuple[Node, ...]

    def matches(self, entry: BibEntry) -> bool:
        """Return whether every child expression matches."""
        return all(child.matches(entry) for child in self.children)

    def to_dict(self) -> dict[str, object]:
        """Describe the conjunction."""
        return {"and": [child.to_dict() for child in self.children]}


@dataclass(frozen=True)
class Or(Node):
    """Disjunction of two or more expressions."""

    children: tuple[Node, ...]

    def matches(self, entry: BibEntry) -> bool:
        """Return whether any child expression matches."""
        return any(child.matches(entry) for child in self.children)

    def to_dict(self) -> dict[str, object]:
        """Describe the disjunction."""
        return {"or": [child.to_dict() for child in self.children]}


def _ordered_compare(op: str, left: str, right: str) -> bool:
    """Compare two values numerically, then as dates, then as text."""
    compare = _ORDER_OPS[op]
    numbers = _as_numbers(left, right)
    if numbers is not None:
        return compare(*numbers)
    dates = _as_dates(left, right)
    if dates is not None:
        return compare(*dates)
    return compare(left.casefold(), right.casefold())


def _as_numbers(left: str, right: str) -> tuple[float, float] | None:
    if _NUMBER_RE.match(left.strip()) and _NUMBER_RE.match(right.strip()):
        return float(left.strip()), float(right.strip())
    return None


def _as_dates(left: str, right: str) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    first = _as_date(left)
    second = _as_date(right)
    if first is None or second is None:
        return None
    return first, second


def _as_date(value: str) -> tuple[int, int, int] | None:
    # BibLaTeX date ranges (``2020-01/2020-03``) compare by their start.
    match = _DATE_RE.match(value.strip().split("/")[0].strip())
    if match is None:
        return None
    year, month, day = match.groups()
    return int(year), int(month or 0), int(day or 0)


# --- tokenizer -------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    kind: str  # "word" | "string" | "op" | punctuation
    value: str


_OP_TOKENS = ("==", "!=", ">=", "<=", "=", ">", "<", "~")
_PUNCTUATION = frozenset("()[],")
_BARE_TERMINATORS = frozenset("()[],\"'=!<>~")


def _tokenize(expr: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    while index < len(expr):
        char = expr[index]
        if char.isspace():
            index += 1
            continue
        if char in _PUNCTUATION:
            tokens.append(_Token(char, char))
            index += 1
            continue
        if char in "\"'":
            end = expr.find(char, index + 1)
            if end == -1:
                raise ValueError(f"unterminated {char} quote")
            tokens.append(_Token("string", expr[index + 1 : end]))
            index = end + 1
            continue
        symbol = next((op for op in _OP_TOKENS if expr.startswith(op, index)), None)
        if symbol is not None:
            tokens.append(_Token("op", symbol))
            index += len(symbol)
            continue
        end = index
        while end < len(expr) and not expr[end].isspace() and expr[end] not in _BARE_TERMINATORS:
            end += 1
        if end == index:
            raise ValueError(f"unexpected character {char!r}")
        tokens.append(_Token("word", expr[index:end]))
        index = end
    return tokens


# --- parser ----------------------------------------------------------------


class _Parser:
    """Recursive-descent parser for one selector expression."""

    def __init__(self, expr: str, tokens: list[_Token], cited_keys: Iterable[str] | None) -> None:
        self.expr = expr
        self.tokens = tokens
        self.position = 0
        self.cited_keys = None if cited_keys is None else frozenset(cited_keys)

    # --- token helpers ---

    def _peek(self, offset: int = 0) -> _Token | None:
        index = self.position + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def _advance(self, expected: str) -> _Token:
        token = self._peek()
        if token is None:
            raise ValueError(f"expected {expected} at end of expression")
        self.position += 1
        return token

    def _match_keyword(self, keyword: str) -> bool:
        token = self._peek()
        if token is not None and token.kind == "word" and token.value.lower() == keyword:
            self.position += 1
            return True
        return False

    def _expect(self, kind: str) -> _Token:
        token = self._advance(f"{kind!r}")
        if token.kind != kind:
            raise ValueError(f"expected {kind!r} but found {token.value!r}")
        return token

    def _value(self, expected: str) -> str:
        token = self._advance(expected)
        if token.kind not in ("word", "string"):
            raise ValueError(f"expected {expected} but found {token.value!r}")
        return token.value

    def _operator_follows(self) -> bool:
        token = self._peek()
        if token is None:
            return False
        if token.kind == "op":
            return True
        return token.kind == "word" and token.value.lower() in _WORD_OPERATORS

    # --- grammar ---

    def parse(self) -> Node:
        """Parse the whole expression, rejecting trailing tokens."""
        node = self._or()
        trailing = self._peek()
        if trailing is not None:
            raise ValueError(f"unexpected {trailing.value!r}")
        return node

    def _or(self) -> Node:
        nodes = [self._and()]
        while self._match_keyword("or"):
            nodes.append(self._and())
        return nodes[0] if len(nodes) == 1 else Or(tuple(nodes))

    def _and(self) -> Node:
        nodes = [self._unary()]
        while self._match_keyword("and"):
            nodes.append(self._unary())
        return nodes[0] if len(nodes) == 1 else And(tuple(nodes))

    def _unary(self) -> Node:
        if self._match_keyword("not"):
            return Not(self._unary())
        token = self._peek()
        if token is not None and token.kind == "(":
            self.position += 1
            node = self._or()
            self._expect(")")
            return node
        return self._predicate()

    def _predicate(self) -> Node:
        token = self._advance("a predicate")
        if token.kind != "word":
            raise ValueError(f"expected a field name but found {token.value!r}")
        text = token.value
        lowered = text.lower()

        if text == "*":
            return All()
        if lowered in ("used", "unused") and not self._operator_follows():
            if self.cited_keys is None:
                raise ValueError(
                    f"predicate {lowered!r} needs cited keys; pass --tex/--aux sources"
                )
            return Used(self.cited_keys, negate=lowered == "unused")
        if lowered == "group":
            return self._group()
        return self._field_predicate(lowered)

    def _group(self) -> Node:
        token = self._peek()
        if token is not None and token.kind == "op" and token.value in ("=", "=="):
            self.position += 1
        name = self._value("a group name")
        if not name:
            raise ValueError("predicate 'group' needs a group name")
        return Group(name)

    def _field_predicate(self, field: str) -> Node:
        token = self._advance(f"an operator after {field!r}")
        if token.kind == "op":
            op = "fuzzy" if token.value == "~" else token.value
            return Comparison(field, op, self._value(f"a value after {token.value!r}"))
        if token.kind != "word":
            raise ValueError(f"expected an operator after {field!r} but found {token.value!r}")

        word = token.value.lower()
        if word in ("exists", "missing"):
            return Comparison(field, word)
        if word == "in":
            return self._in_set(field, negate=False)
        if word == "not" and self._match_keyword("in"):
            return self._in_set(field, negate=True)
        if word in _TEXT_OPS:
            return Comparison(field, word, self._value(f"a value after {word!r}"))
        raise ValueError(f"unknown operator {token.value!r}")

    def _in_set(self, field: str, *, negate: bool) -> Node:
        self._expect("[")
        values: list[str] = []
        if self._peek() is not None and self._peek().kind != "]":  # type: ignore[union-attr]
            values.append(self._value("a value"))
            while self._peek() is not None and self._peek().kind == ",":  # type: ignore[union-attr]
                self.position += 1
                values.append(self._value("a value"))
        self._expect("]")
        if not values:
            raise ValueError(f"{field!r} in [] needs at least one value")
        return InSet(field, tuple(values), negate=negate)


def parse_query(expr: str, *, cited_keys: Iterable[str] | None = None) -> Node:
    """Compile a ``--where`` expression into a callable predicate.

    Examples::

        title contains "digital currency"
        type in [article, inproceedings] and year >= 2025
        doi missing and not group "Reviewed"
        key in [Newton1687, Euler1748]
        date >= 1900-06 or *

    ``cited_keys`` supplies the key set the ``used`` / ``unused`` predicates
    test against; without it those predicates raise, since a bare cited-key
    question has no answer.

    Raises:
        ValueError: if the expression cannot be parsed.
    """
    try:
        tokens = _tokenize(expr)
        if not tokens:
            raise ValueError("expression is empty")
        return _Parser(expr, tokens, cited_keys).parse()
    except ValueError as exc:
        # Every failure names the whole expression: a caller sees the selector it
        # sent back, not just the fragment that stopped the parser.
        raise ValueError(f"Invalid query expression {expr!r}: {exc}") from exc


#: Machine-readable description of this grammar, surfaced by ``capabilities``.
WHERE_GRAMMAR: dict[str, object] = {
    "boolean": (
        "Combine predicates with 'and', 'or', and 'not'; 'and' binds tighter "
        "than 'or', and parentheses group explicitly."
    ),
    "field_operators": {
        "contains": "case-insensitive substring",
        "=": "case-insensitive equality (also '==')",
        "!=": "case-insensitive inequality (true when the field is absent)",
        ">, >=, <, <=": (
            "ordered comparison: numeric when both sides are numbers, partial "
            "date (YYYY[-MM[-DD]]) when both are dates, text otherwise"
        ),
        "in [a, b]": "membership in a list of values ('not in' negates it)",
        "matches": "case-insensitive regular-expression search",
        "~": f"fuzzy match, normalized similarity >= {FUZZY_THRESHOLD}",
        "exists": "the field is present",
        "missing": "the field is absent or empty",
    },
    "special_fields": {
        "key": "the citation key",
        "type": "the entry type",
        "year": "the year field, falling back to the year inside date",
        "date": "the date field, falling back to year/month/day",
    },
    "bucket_predicates": {
        "*": "matches every entry (catch-all / rest bucket)",
        "used": "citation key appears in the --tex/--aux sources",
        "unused": "citation key does not appear in the sources",
        'group "Name"': "entry belongs to the named group",
    },
    "values": (
        "Quote values containing spaces or punctuation with single or double "
        "quotes; bare tokens may not contain whitespace, brackets, commas, or "
        "comparison characters."
    ),
    "absent_fields": (
        "A comparison against a field the entry does not have is false, except "
        "'!=' and 'missing', which are true."
    ),
    "examples": [
        'title contains "digital currency"',
        "type = article",
        "doi exists",
        "abstract missing",
        "year >= 2025 and type in [article, inproceedings]",
        'not (group "Reviewed" or keywords contains draft)',
        "key in [Newton1687, Euler1748]",
        'title ~ "quantum computing"',
        'journal matches "^Phys\\. Rev\\."',
        "date >= 1900-06",
        "used",
        "*",
    ],
}
