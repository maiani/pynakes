"""Deterministic Library placement rules, evaluated before any write."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pynakes.model import BibEntry
from pynakes.query import Node, parse_query


@dataclass(frozen=True)
class RoutingRule:
    """One named selector and destination; larger priority numbers win."""

    name: str
    where: str
    destination: Path
    priority: int
    predicate: Node

    def to_dict(self) -> dict:
        """Serialize the rule, including the selector explaining its match."""
        return {
            "name": self.name,
            "where": self.where,
            "destination": str(self.destination),
            "priority": self.priority,
        }


@dataclass(frozen=True)
class LibraryRouting:
    """Library-owned placement policy; no bibliography formatting settings."""

    fallback: Path | None = None
    rules: tuple[RoutingRule, ...] = ()

    def validate_members(self, members: tuple[Path, ...]) -> None:
        """Refuse targets outside the declared, non-excluded membership."""
        for path in [self.fallback, *(rule.destination for rule in self.rules)]:
            if path is not None and path not in members:
                raise ValueError(f"Routing destination is not a Library member: {path}")


def _destination(value: object, base: Path) -> Path:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ValueError("Routing destination must be a non-empty relative .bib path")
    path = Path(value)
    if path.is_absolute() or path.suffix.lower() != ".bib":
        raise ValueError("Routing destination must be a relative .bib path")
    return (base / path).resolve()


def parse_routing(data: object, base: Path) -> LibraryRouting:
    """Parse a strict optional TOML routing table using the shared selectors."""
    if not isinstance(data, dict) or data.keys() - {"fallback", "rules"}:
        raise ValueError("Library routing accepts only fallback and rules")
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError("Library routing rules must be an array of tables")
    rules = []
    names = set()
    for row in raw_rules:
        if not isinstance(row, dict) or row.keys() != {"name", "where", "destination", "priority"}:
            raise ValueError("Each routing rule requires name, where, destination and priority")
        for key in ("name", "where"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"Routing rule {key} must be a non-empty string")
        if row["name"] in names:
            raise ValueError(f"Duplicate routing rule name: {row['name']}")
        names.add(row["name"])
        if type(row["priority"]) is not int:
            raise ValueError("Routing rule priority must be an integer")
        rules.append(
            RoutingRule(
                row["name"],
                row["where"],
                _destination(row["destination"], base),
                row["priority"],
                parse_query(row["where"]),
            )
        )
    return LibraryRouting(
        _destination(data["fallback"], base) if "fallback" in data else None, tuple(rules)
    )


@dataclass(frozen=True)
class RoutingDecision:
    """A placement result; only ``routed`` permits a new entry to be staged."""

    status: str
    destination: Path | None
    reason: str
    matched_rules: tuple[RoutingRule, ...] = ()
    candidates: tuple[dict, ...] = ()
    issues: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        """Return reviewable routing evidence for clients."""
        return {
            "status": self.status,
            "destination": str(self.destination) if self.destination is not None else None,
            "reason": self.reason,
            "matched_rules": [rule.to_dict() for rule in self.matched_rules],
            "candidates": list(self.candidates),
            "issues": list(self.issues),
        }


def choose_destination(
    policy: LibraryRouting,
    entry: BibEntry,
    members: tuple[Path, ...],
    base: Path,
    destination: str | Path | None,
) -> RoutingDecision:
    """Choose one home; ties at the highest priority never depend on order."""
    if destination is not None:
        path = Path(destination)
        path = (base / path).resolve()
        if path not in members:
            raise ValueError(f"Destination is not a Library member: {destination}")
        return RoutingDecision("routed", path, "explicit_destination")
    matched = tuple(rule for rule in policy.rules if rule.predicate(entry))
    if matched:
        priority = max(rule.priority for rule in matched)
        winners = tuple(rule for rule in matched if rule.priority == priority)
        destinations = {rule.destination for rule in winners}
        if len(destinations) == 1:
            return RoutingDecision("routed", winners[0].destination, "matching_rule", matched)
        return RoutingDecision("ambiguous", None, "equal_priority_destinations", matched)
    if policy.fallback is not None:
        return RoutingDecision("routed", policy.fallback, "fallback")
    return RoutingDecision("unmatched", None, "no_rule_or_fallback")
