"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

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
)
from pynakes.engine import Bibliography

# --- groups ----------------------------------------------------------------


def groups_list(
    file: str | None = bib_file_argument(),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all groups and their members."""
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    lib = coll.lib
    names = group_tree_ops.known_group_names(lib)
    members = {g: group_tree_ops.list_direct_members(lib, g) for g in names}

    if json_output:
        _emit_json(
            {
                "status": "success",
                "action": "groups_list",
                "file": file,
                "source_sha256": _source_sha256(coll),
                "warnings": [],
                "groups": members,
            }
        )
        return

    if not names:
        typer.echo(f"{file}: no groups found.")
        return
    for name in names:
        typer.echo(f"{name} ({len(members[name])}): {', '.join(members[name])}")


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
        _emit_error(json_output, "KeyNotFound", f"No entry with key {key!r} in the library")


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
        hint = "; create it with groups add-group, or pass --create" if add else ""
        _require_group(coll.lib, group, params.json_output, hint)
    if add:
        action, count = "groups_add_entry", coll.add_to_group(key, group)
        msg = (
            f"{_verb('add', params)} {key} to group {group!r} ({count} {_entries(count)} changed)."
        )
    else:
        action, count = "groups_remove_entry", coll.remove_from_group(key, group)
        msg = f"{_verb('remove', params)} {key} from group {group!r} ({count} {_entries(count)} changed)."
    _finish_mod(file, action, coll, params, [msg], key=key, group=group)


def groups_add_entry(
    file: str | None = bib_file_argument(),
    key: str = typer.Argument(..., help="Citation key to add"),
    group: str = typer.Argument(..., help="Group name"),
    create: bool = typer.Option(
        False, "--create", help="Create the group if the library does not have it yet"
    ),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add an entry to a group.

    The group must already exist, so a mistyped name is an error rather than a
    new group; ``--create`` makes a new one.
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


def groups_remove_entry(
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


def groups_add_group(
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
    if any(node.name == name for node in tree):
        _group_conflict(json_output, name)
    if parent:
        _require_group(coll.lib, parent, json_output)
    ok = coll.add_group_node(name, parent=parent, color=color, context=GROUP_CONTEXT_CODES[context])
    if not ok:
        _emit_error(json_output, "InvalidInput", f"Group {name!r} could not be added to the tree")
    action = "groups_add_group"
    msg = f"{_verb('add', params)} group {name!r} (parent={parent!r})."
    _finish_mod(file, action, coll, params, [msg], group=name, parent=parent)


def groups_remove_group(
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
    count = coll.remove_group_node(name)
    if not count:
        _emit_error(
            json_output,
            "KeyNotFound",
            f"Group {name!r} not found in the tree",
        )
    action = "groups_remove_group"
    msg = f"{_verb('remove', params)} group {name!r} ({count} nodes removed)."
    _finish_mod(file, action, coll, params, [msg], group=name, removed_count=count)


def groups_rename_group(
    file: str | None = bib_file_argument(),
    old: str = typer.Argument(..., help="Current group name"),
    new: str = typer.Argument(..., help="New group name"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename a group node, updating parent references in child groups."""
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
    if old != new and _group_exists(coll.lib, new):
        _group_conflict(json_output, new)
    ok = coll.rename_group_node(old, new)
    if not ok:
        _emit_error(json_output, "InvalidInput", f"Group {old!r} could not be renamed to {new!r}")
    action = "groups_rename_group"
    msg = f"{_verb('rename', params)} group {old!r} to {new!r}."
    _finish_mod(file, action, coll, params, [msg], old=old, new=new)


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


def groups_update_group(
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
        action = "groups_update_group"
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
    action = "groups_update_group"
    changed = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    msg = f"{_verb('update', params)} group {name!r} ({changed})."
    _finish_mod(file, action, coll, params, [msg], group=name, **kwargs)


def groups_list_entries(
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
                "action": "groups_list_entries",
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


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command("list")(_safe(groups_list))
    app.command("list-entries")(_safe(groups_list_entries))
    app.command("add-entry")(_safe(groups_add_entry))
    app.command("remove-entry")(_safe(groups_remove_entry))
    app.command("tree")(_safe(groups_tree))
    app.command("add-group")(_safe(groups_add_group))
    app.command("remove-group")(_safe(groups_remove_group))
    app.command("rename-group")(_safe(groups_rename_group))
    app.command("move-group")(_safe(groups_move_group))
    app.command("update-group")(_safe(groups_update_group))
