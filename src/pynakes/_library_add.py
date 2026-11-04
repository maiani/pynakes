"""Single-destination Library additions through the Bibliography transaction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes._library_routing import RoutingDecision, choose_destination
from pynakes.engine import Bibliography
from pynakes.fields import check_field_value
from pynakes.identity import compare_work_evidence, evidence_from_entry, identity_class
from pynakes.keys import validate_key
from pynakes.model import BibEntry

if TYPE_CHECKING:
    from pynakes.library import Library


class LibraryRoutingError(ValueError):
    """An addition requires a placement or existing-work decision."""

    def __init__(self, decision: RoutingDecision) -> None:
        self.decision = decision
        super().__init__(f"Library addition refused: {decision.reason}")


@dataclass(frozen=True)
class LibraryAddition:
    """A routed addition staged in one bibliography, ready for preview/commit.

    ``bibliography.commit()`` rechecks Library membership, rules and source
    bytes before writing. Reopen the Library after commit. Nothing is saved by
    constructing this object; reset discards the staged addition and its guard.
    """

    bibliography: Bibliography
    decision: RoutingDecision
    library_sha256: str


def route(library: Library, entry: BibEntry, destination: str | Path | None) -> RoutingDecision:
    """Check existing works first, then select a home using the held view."""
    validate_key(entry.key)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", entry.type):
        raise ValueError("Invalid entry type")
    for name, value in entry.fields.items():
        check_field_value(name, value)
    if library.issues:
        return RoutingDecision(
            "incomplete",
            None,
            "incomplete_library",
            issues=tuple(issue.to_dict() for issue in library.issues),
        )
    candidates: list[dict] = []
    candidate = evidence_from_entry(entry)
    for member in library._loaded:
        for index, existing in enumerate(member.bib.entries.values()):
            evidence = evidence_from_entry(existing)
            match = compare_work_evidence(candidate, evidence)
            shared = set(candidate.identifiers.items) & set(evidence.identifiers.items)
            if (
                existing.key == entry.key
                or match.is_match
                or (match.status == "conflict" and shared)
            ):
                version_conflict = {identity_class(entry), identity_class(existing)} == {
                    "preprint",
                    "published",
                }
                candidates.append(
                    {
                        "file": str(member.path),
                        "key": existing.key,
                        "entry_index": index,
                        "match": match.to_dict(),
                        "same_key": existing.key == entry.key,
                        "version_conflict": version_conflict,
                    }
                )
    if candidates:
        exact = (
            len(candidates) == 1
            and candidates[0]["match"]["status"] == "exact"
            and not candidates[0]["version_conflict"]
        )
        return RoutingDecision(
            "existing" if exact else "conflict",
            Path(candidates[0]["file"]) if exact else None,
            "existing_work" if exact else "existing_work_or_key_candidates",
            candidates=tuple(candidates),
        )
    base = library.manifest.parent if library.manifest else Path.cwd()
    return choose_destination(library.routing, entry, library.members, base, destination)


def stage_entry(
    library: Library,
    entry: BibEntry,
    destination: str | Path | None,
) -> LibraryAddition:
    """Stage only a uniquely routed new reference, guarding the full read set."""
    library._assert_current()
    decision = route(library, entry, destination)
    if decision.status != "routed":
        raise LibraryRoutingError(decision)
    assert decision.destination is not None
    coll = Bibliography.open(decision.destination)
    # Opening the target must not introduce a different snapshot than routing.
    library._assert_current()
    assert coll.source_fingerprint is not None
    if coll.source_fingerprint.sha256 != next(
        member.sha256 for member in library._loaded if member.path == decision.destination
    ):
        from pynakes.engine import ExternalModificationError

        raise ExternalModificationError(decision.destination)
    coll.add_entry(entry.type, entry.key, entry.fields)
    coll._commit_guards.append(library._assert_current)
    return LibraryAddition(coll, decision, library.source_sha256)
