"""Declarative URL-to-identifier resolver primitives."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

IdentifierExtractor = Callable[[re.Match[str]], str | None]
IdentifierNormalizer = Callable[[str], str | None]


@dataclass(frozen=True)
class ResolvedURL:
    """A canonical identifier extracted from a supported URL."""

    kind: str
    identifier: str
    source: str


@dataclass(frozen=True)
class URLRule:
    """One ordered URL recognition rule."""

    source: str
    kind: str
    pattern: re.Pattern[str]
    extract: IdentifierExtractor
    normalize: IdentifierNormalizer

    def resolve(self, value: str) -> ResolvedURL | None:
        """Resolve ``value`` when it matches this rule."""
        match = self.pattern.match(value.strip())
        if match is None:
            return None
        extracted = self.extract(match)
        if extracted is None:
            return None
        try:
            identifier = self.normalize(extracted)
        except ValueError:
            return None
        if identifier is None:
            return None
        return ResolvedURL(self.kind, identifier, self.source)


def resolve_url(value: str, rules: Iterable[URLRule]) -> ResolvedURL | None:
    """Return the first canonical identifier produced by ordered ``rules``."""
    for rule in rules:
        resolved = rule.resolve(value)
        if resolved is not None:
            return resolved
    return None
