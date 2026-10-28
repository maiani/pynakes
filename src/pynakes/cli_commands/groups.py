"""CLI commands for the ``groups`` family: the hierarchy and its memberships.

``list``, ``show``, ``add``, ``remove``, ``rename`` and ``update`` work on
groups; ``assign`` and ``unassign`` file an entry under a group or take it out.
"""

from collections.abc import Callable

import typer

from pynakes import group_tree as group_tree_ops
from pynakes.cli_choices import GROUP_CONTEXT_CODES, GroupContext
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _emit_conflict,
    _emit_error,
    _emit_json,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
    bib_file_argument,
    deprecated_alias,
)
from pynakes.engine import Bibliography

# --- groups ----------------------------------------------------------------


def groups_list_report(lib) -> dict:
    """Return the ``groups``, ``tree`` and ``undeclared`` keys of ``groups list``."""
    names = group_tree_ops.known_group_names(lib)
    tree = group_tree_ops.list_tree(lib) or []
    declared = {node.name for node in tree}
    return {
        "groups": {name: group_tree_ops.list_direct_members(lib, name) for name in names},
        "tree": [node.to_dict() for node in tree],
        "undeclared": [name for name in names if name not in declared],
    }


def groups_list(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List the group hierarchy with each group's direct members.

    `tree` is the hierarchy the bibliography's metadata declares; `groups` maps
    every group, declared or not, to its direct members; `undeclared` names the
    groups only entries mention. The two can disagree, and the report says so
    rather than reconciling them. `groups show NAME` lists one group's entries,
    descendants included.
    """
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    report = groups_list_report(coll.lib)

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "groups_list",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                **report,
            }
        )
        return

    members = report["groups"]
    tree = group_tree_ops.list_tree(coll.lib) or []
    undeclared = report["undeclared"]
    if not members:
        typer.echo(f"{file}: no groups found.")
        return

    def line(prefix: str, name: str, color: str = "") -> str:
        keys = members.get(name, [])
        listed = f": {', '.join(keys)}" if keys else ""
        return f"{prefix}{name}{color} ({len(keys)}){listed}"

    def show(parent: str, prefix: str, seen: set[str]) -> None:
        for node in tree:
            if node.parent == parent and node.name not in seen:
                seen.add(node.name)
                color = f" [{node.color}]" if node.color else ""
                typer.echo(line(f"{prefix}{'+' if node.expanded else '-'} ", node.name, color))
                show(node.name, prefix + "  ", seen)

    shown: set[str] = set()
    show("", "", shown)
    # A node whose parent is missing or part of a cycle is still listed.
    for node in tree:
        if node.name not in shown:
            shown.add(node.name)
            typer.echo(line("- ", node.name))
    if undeclared:
        typer.echo("Not declared in the hierarchy:")
        for name in undeclared:
            typer.echo(line("  ", name))


def groups_tree(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show the group hierarchy tree."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    tree = group_tree_ops.list_tree(coll.lib)

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "groups_tree",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "tree": [n.to_dict() for n in tree] if tree else [],
            }
        )
        return

    if tree is None:
        typer.echo(f"{file}: no group tree defined.")
        return

    def _show(nodes, prefix="", parent=""):
        lines = []
        for n in nodes:
            if n.parent == parent:
                color = f" [{n.color}]" if n.color else ""
                expanded = "+" if n.expanded else "-"
                lines.append(f"{prefix}{expanded} {n.name}{color}")
                lines.extend(_show(nodes, prefix + "  ", n.name))
        return lines

    for line in _show(tree):
        typer.echo(line)


_CONTEXT_HELP = (
    "How the group's membership relates to its parent's: independent, "
    "refining (intersection), or including (union)"
)


def _require_key(lib, key: str, json_output: bool) -> None:
    if key not in lib.entries:
        _emit_error(json_output, "KeyNotFound", f"No entry with key {key!r} in the bibliography")


def _group_exists(lib, name: str) -> bool:
    return name in group_tree_ops.known_group_names(lib)


def _require_group(lib, name: str, json_output: bool, hint: str = "") -> None:
    """Exit with ``KeyNotFound`` unless *name* is a group the library knows."""
    if not _group_exists(lib, name):
        _emit_error(json_output, "KeyNotFound", f"Group {name!r} not found{hint}", group=name)


def _group_conflict(json_output: bool, name: str) -> None:
    _emit_conflict(
        json_output,
        "GroupConflict",
        f"Group {name!r} already exists",
        group=name,
        options=[{"id": "choose_name", "description": "Retry with a different group name"}],
    )


def _group_mod_entry(
    file: str,
    key: str,
    group: str,
    params: RunParams,
    add: bool,
    create: bool = False,
) -> None:
    """Shared implementation for add-entry and remove-entry."""
    coll = Bibliography.open(file)
    _require_key(coll.lib, key, params.json_output)
    if not (add and create):
        hint = "; create it with groups add, or pass --create" if add else ""
        _require_group(coll.lib, group, params.json_output, hint)
    if add:
        action, count = "groups_assign", coll.add_to_group(key, group)
        msg = (
            f"{_verb('add', params)} {key} to group {group!r} ({count} {_entries(count)} changed)."
        )
    else:
        action, count = "groups_unassign", coll.remove_from_group(key, group)
        msg = f"{_verb('remove', params)} {key} from group {group!r} ({count} {_entries(count)} changed)."
    _finish_mod(file, action, coll, params, [msg], key=key, group=group)


def groups_assign(
    file: str | None = bib_file_argument(),
    key: str = typer.Argument(..., help="Citation key to add"),
    group: str = typer.Argument(..., help="Group name"),
    create: bool = typer.Option(
        False, "--create", help="Create the group if the bibliography does not have it yet"
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add an entry to a group.

    The group must already exist, so a mistyped name is an error rather than a
    new group; `--create` makes a new one.
    """
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    _group_mod_entry(file, key, group, params, add=True, create=create)


def groups_unassign(
    file: str | None = bib_file_argument(),
    key: str = typer.Argument(..., help="Citation key to remove"),
    group: str = typer.Argument(..., help="Group name"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove an entry from a group."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    _group_mod_entry(file, key, group, params, add=False)


def groups_add(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Group name to add"),
    parent: str = typer.Option("", "--parent", help="Parent group name"),
    color: str = typer.Option("", "--color", help="Hex RGBA color (e.g. 8a8a8aff)"),
    context: GroupContext = typer.Option(GroupContext.INCLUDING, "--context", help=_CONTEXT_HELP),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add a group node to the hierarchy tree."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    tree = coll.list_tree() or []
    # The tree refuses a name differing from an existing node only in case, so
    # that is a conflict too, not a failure to add.
    if any(node.name.lower() == name.lower() for node in tree):
        _group_conflict(json_output, name)
    if parent:
        _require_group(coll.lib, parent, json_output)
    ok = coll.add_group_node(name, parent=parent, color=color, context=GROUP_CONTEXT_CODES[context])
    if not ok:
        _emit_error(json_output, "InvalidInput", f"Group {name!r} could not be added to the tree")
    action = "groups_add"
    msg = f"{_verb('add', params)} group {name!r} (parent={parent!r})."
    _finish_mod(file, action, coll, params, [msg], group=name, parent=parent)


def groups_remove(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Group name to remove"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove a group node and all its descendants from the hierarchy."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    before = [node.name for node in coll.list_tree() or []]
    count = coll.remove_group_node(name)
    remaining = {node.name for node in coll.list_tree() or []}
    # Named, in tree order, so a caller confirming the removal can say which
    # descendants go with the group without walking the tree itself.
    removed = [group for group in before if group not in remaining]
    if not count:
        _emit_error(
            json_output,
            "KeyNotFound",
            f"Group {name!r} not found in the tree",
        )
    action = "groups_remove"
    msg = f"{_verb('remove', params)} group {name!r} ({count} nodes removed)."
    _finish_mod(
        file,
        action,
        coll,
        params,
        [msg],
        group=name,
        removed_count=count,
        removed_groups=removed,
    )


def groups_rename(
    file: str | None = bib_file_argument(),
    old: str = typer.Argument(..., help="Current group name"),
    new: str = typer.Argument(..., help="New group name"),
    members: bool = typer.Option(
        False,
        "--members",
        help="Also move the group's members: rewrite OLD to NEW in every entry's "
        "groups field (exact name match)",
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename a group node, updating parent references in child groups.

    Entries filed under OLD keep that membership unless `--members` is given,
    which renames it to NEW in each of them too.
    """
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    tree = coll.list_tree() or []
    if not any(node.name == old for node in tree):
        _emit_error(json_output, "KeyNotFound", f"Group {old!r} not found in the tree", group=old)
    # A case-only rename (``Optics`` to ``OPTICS``) is the node itself, not a
    # clash; another node differing from NEW only in case is one.
    clashes_in_tree = any(node.name.lower() == new.lower() and node.name != old for node in tree)
    if old != new and (clashes_in_tree or _group_exists(coll.lib, new)):
        _group_conflict(json_output, new)
    ok = coll.rename_group_node(old, new)
    if not ok:
        _emit_error(json_output, "InvalidInput", f"Group {old!r} could not be renamed to {new!r}")
    # Named, in file order, so a caller confirming the rename can say which
    # entries move with the group.
    renamed = coll.rename_group_members(old, new) if members else []
    action = "groups_rename"
    moved = f" ({len(renamed)} {_entries(len(renamed))} moved with it)" if members else ""
    msg = f"{_verb('rename', params)} group {old!r} to {new!r}{moved}."
    _finish_mod(
        file,
        action,
        coll,
        params,
        [msg],
        old=old,
        new=new,
        members=members,
        members_renamed=renamed,
    )


def groups_move_group(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Group name to move"),
    parent: str = typer.Option("", "--parent", help="New parent group name"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Move a group node to a new parent (empty string for root-level)."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    tree = coll.list_tree() or []
    if not any(node.name == name for node in tree):
        _emit_error(json_output, "KeyNotFound", f"Group {name!r} not found in the tree", group=name)
    if parent:
        _require_group(coll.lib, parent, json_output)
    ok = coll.move_group_node(name, parent)
    if not ok:
        _emit_error(
            json_output,
            "InvalidInput",
            f"Moving group {name!r} under {parent!r} would create a circular reference",
        )
    action = "groups_move_group"
    msg = f"{_verb('move', params)} group {name!r} to parent {parent!r}."
    _finish_mod(file, action, coll, params, [msg], group=name, parent=parent)


def groups_update(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Group name to update"),
    parent: str | None = typer.Option(
        None, "--parent", help="New parent group name (pass '' to move to root)"
    ),
    color: str | None = typer.Option(
        None, "--color", help="Hex RGBA color (e.g. 8a8a8aff); pass '' to clear"
    ),
    context: GroupContext | None = typer.Option(None, "--context", help=_CONTEXT_HELP),
    expanded: bool | None = typer.Option(None, "--expanded/--collapsed", help="Expanded in the UI"),
    description: str | None = typer.Option(
        None, "--description", help="Group description; pass '' to clear"
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Update properties of a group node in the hierarchy."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        json_output=json_output,
        backup=backup,
        expect_sha256=expect_sha256,
    )
    coll = Bibliography.open(file)
    kwargs: dict = {}
    if parent is not None:
        kwargs["parent"] = parent
    if color is not None:
        kwargs["color"] = color
    if context is not None:
        kwargs["context"] = GROUP_CONTEXT_CODES[context]
    if expanded is not None:
        kwargs["expanded"] = expanded
    if description is not None:
        kwargs["description"] = description

    tree = coll.list_tree()
    exists = tree is not None and any(n.name.lower() == name.lower() for n in tree)
    if parent:
        _require_group(coll.lib, parent, json_output)
    if not kwargs:
        if not exists:
            _emit_error(
                json_output,
                "KeyNotFound",
                f"Group {name!r} not found in the tree",
            )
        action = "groups_update"
        msg = f"No properties given for group {name!r}; nothing to update."
        _finish_mod(file, action, coll, params, [msg], group=name)
        return

    ok = coll.update_group_node(name, **kwargs)
    if not ok:
        _emit_error(
            json_output,
            "KeyNotFound",
            f"Group {name!r} not found in the tree",
        )
    action = "groups_update"
    changed = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    msg = f"{_verb('update', params)} group {name!r} ({changed})."
    _finish_mod(file, action, coll, params, [msg], group=name, **kwargs)


def groups_show(
    file: str | None = bib_file_argument(),
    name: str = typer.Argument(..., help="Group name"),
    exact: bool = typer.Option(
        False, "--exact", help="Exact group match only (default: include descendants)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List entries belonging to a group (with descendant propagation by default)."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    lib = coll.lib
    known = group_tree_ops.known_group_names(lib)
    if not any(n.lower() == name.lower() for n in known):
        _emit_error(json_output, "KeyNotFound", f"Group {name!r} not found")
    entries = group_tree_ops.list_entries_in_group_tree(lib, name, exact=exact)

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "groups_show",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "group": name,
                "exact": exact,
                "entries": entries,
            }
        )
        return

    desc = " (exact)" if exact else " (with descendants)"
    typer.echo(f"{name}{desc}: {', '.join(entries) if entries else '(no entries)'}")


#: Forms deprecated in 0.9.0 and removed in 0.10.0: (old name, callback, new
#: form, the action the old form keeps emitting). Hidden from ``--help``.
_DEPRECATED: tuple[tuple[str, Callable[..., None], str, str], ...] = (
    ("tree", groups_tree, "groups list", "groups_tree"),
    ("list-entries", groups_show, "groups show", "groups_list_entries"),
    ("add-entry", groups_assign, "groups assign", "groups_add_entry"),
    ("remove-entry", groups_unassign, "groups unassign", "groups_remove_entry"),
    ("add-group", groups_add, "groups add", "groups_add_group"),
    ("remove-group", groups_remove, "groups remove", "groups_remove_group"),
    ("rename-group", groups_rename, "groups rename", "groups_rename_group"),
    ("move-group", groups_move_group, "groups update --parent", "groups_move_group"),
    ("update-group", groups_update, "groups update", "groups_update_group"),
)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(groups_list))
    app.command("show")(_safe(groups_show))
    app.command("add")(_safe(groups_add))
    app.command("remove")(_safe(groups_remove))
    app.command("rename")(_safe(groups_rename))
    app.command("update")(_safe(groups_update))
    app.command("assign")(_safe(groups_assign))
    app.command("unassign")(_safe(groups_unassign))
    for old, fn, new, action in _DEPRECATED:
        alias = deprecated_alias(fn, old=f"groups {old}", new=new, action=action, removal="0.10.0")
        app.command(old, hidden=True)(_safe(alias))
