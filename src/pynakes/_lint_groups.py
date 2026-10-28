"""Diagnose group memberships and the declared group hierarchy."""

from pynakes._lint_issue import LintIssue
from pynakes.group_tree import GroupNode, library_group_tree
from pynakes.groups import library_groups_separator
from pynakes.model import BibFile


def lint_groups(lib: BibFile) -> list[LintIssue]:
    """Report malformed memberships and hierarchy cycles without stopping lint."""
    return [*_membership_issues(lib), *_cycle_issues(library_group_tree(lib) or [])]


def _cycle_issues(tree: list[GroupNode]) -> list[LintIssue]:
    """Report each set of groups whose parents lead back to themselves, once.

    A cycle has no root, so neither JabRef nor a tree view can place its groups;
    the commands that edit the hierarchy refuse to make one, but a hand-edited
    ``group-tree`` can still hold one.
    """
    parents = {node.name: node.parent for node in tree}
    issues: list[LintIssue] = []
    reported: set[str] = set()
    for start in parents:
        chain: list[str] = []
        name = start
        while name in parents and name not in chain and name not in reported:
            chain.append(name)
            name = parents[name]
        if name not in chain:
            continue  # reached the top level, a missing parent, or a known cycle
        cycle = chain[chain.index(name) :]
        reported.update(cycle)
        path = " -> ".join(repr(group) for group in [*cycle, name])
        issues.append(
            LintIssue(
                "group_cycle",
                "error",
                f"Groups form a cycle in the hierarchy, each under the next: {path}; give one "
                "of them another parent with groups update --parent",
                key=cycle[0],
            )
        )
    return issues


def _membership_issues(lib: BibFile) -> list[LintIssue]:
    """Report an ambiguous separator or empty memberships."""
    try:
        delimiter = library_groups_separator(lib)
    except ValueError as exc:
        return [LintIssue("malformed_groups", "warning", str(exc), field="groups")]
    return [
        LintIssue(
            "malformed_groups",
            "warning",
            f"Entry {entry.key!r} has a malformed groups field: {value!r}",
            key=entry.key,
            field="groups",
        )
        for entry in lib.entries.values()
        if (value := entry.fields.get("groups"))
        and value.strip()
        and any(not part.strip() for part in value.split(delimiter))
    ]
