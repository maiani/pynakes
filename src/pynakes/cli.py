"""Command-line interface for pynakes."""

import json as _json
from pathlib import Path
from typing import Optional

import typer

from pynakes import fields as fields_ops
from pynakes import groups as groups_ops
from pynakes import keys as keys_ops
from pynakes.bibtex_writer import write_bib
from pynakes.diff import generate_diff
from pynakes.editing import splice_into_text
from pynakes.io import load_bib, save_bib, save_text
from pynakes.lint import lint as lint_lib
from pynakes.usage import (
    analyze_usage,
    collect_cited_keys,
    subset_library,
    tag_with_group,
    tag_with_keyword,
)

app = typer.Typer(help="Agent-friendly BibTeX library management tool")
groups_app = typer.Typer(help="Manage entry groups")
keys_app = typer.Typer(help="Generate and check citation keys")
fields_app = typer.Typer(help="Edit fields (rename, move, append, clear)")
app.add_typer(groups_app, name="groups")
app.add_typer(keys_app, name="keys")
app.add_typer(fields_app, name="fields")


# --- shared helpers --------------------------------------------------------


def _snapshot(lib) -> dict[int, Optional[str]]:
    """Capture each entry's raw text so edits can be diffed against it."""
    return {id(e): e.raw_content for e in lib.entries.values()}


def _commit(
    bib_file: str, lib, pre_raw: dict[int, Optional[str]], dry_run: bool
) -> tuple[int, str, bool]:
    """Splice surgical edits back into the original file and (unless dry-run) write.

    Returns ``(changed_entries, diff_text, modified)``. Entries whose
    ``raw_content`` differs from the pre-edit snapshot are spliced into the
    original text for a minimal diff; if any block can't be located we fall back
    to full re-serialization.
    """
    original_text = Path(bib_file).read_text(encoding=lib.encoding, errors="replace")
    edits: list[tuple[str, str]] = []
    for entry in lib.entries.values():
        before = pre_raw.get(id(entry))
        if before is not None and entry.raw_content is not None and entry.raw_content != before:
            edits.append((before, entry.raw_content))

    if edits:
        new_text = splice_into_text(original_text, edits)
        if new_text is None:
            new_text = write_bib(lib)
    else:
        new_text = original_text

    modified = new_text != original_text
    diff_text = generate_diff(original_text, new_text, Path(bib_file).name) if modified else ""
    if modified and not dry_run:
        save_text(new_text, bib_file, encoding=lib.encoding)
    return len(edits), diff_text, modified


def _emit(
    json_output: bool,
    result: dict,
    human: list[str],
    diff_text: str = "",
    show_diff: bool = False,
) -> None:
    if json_output:
        if show_diff and diff_text:
            result["diff"] = diff_text
        typer.echo(_json.dumps(result, indent=2))
        return
    for line in human:
        typer.echo(line)
    if show_diff and diff_text:
        typer.echo("")
        typer.echo(diff_text)


def _entries(count: int) -> str:
    return "entry" if count == 1 else "entries"


# --- inspect ---------------------------------------------------------------


@app.command()
def inspect(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Inspect a .bib file structure."""
    lib = load_bib(file)
    issues = lint_lib(lib)
    duplicates = lib.entries.duplicate_keys()

    if json_output:
        result = {
            "status": "success",
            "action": "inspect",
            "file": file,
            "encoding": lib.encoding,
            "line_ending": "crlf" if lib.line_ending == "\r\n" else "lf",
            "entry_count": len(lib.entries),
            "entries": [
                {"key": e.key, "type": e.type, "fields": dict(e.fields)}
                for e in lib.entries.values()
            ],
            "duplicate_keys": duplicates,
            "issues": [i.to_dict() for i in issues],
        }
        typer.echo(_json.dumps(result, indent=2))
        return

    le = "CRLF" if lib.line_ending == "\r\n" else "LF"
    typer.echo(f"{file}: {len(lib.entries)} {_entries(len(lib.entries))} ({lib.encoding}, {le})")
    for entry in lib.entries.values():
        typer.echo(f"  @{entry.type}{{{entry.key}}}  ({len(entry.fields)} fields)")
    if duplicates:
        typer.echo(f"Duplicate keys: {', '.join(f'{k} ×{n}' for k, n in duplicates.items())}")
    typer.echo(f"Issues: {len(issues)}")


# --- lint ------------------------------------------------------------------


@app.command()
def lint(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Validate entries and report issues."""
    lib = load_bib(file)
    issues = lint_lib(lib)
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")

    if json_output:
        result = {
            "status": "success",
            "action": "lint",
            "file": file,
            "issue_count": len(issues),
            "errors": errors,
            "warnings": warnings,
            "issues": [i.to_dict() for i in issues],
        }
        typer.echo(_json.dumps(result, indent=2))
        return

    if not issues:
        typer.echo(f"{file}: no issues found.")
        return
    for issue in issues:
        loc = f"{issue.key}: " if issue.key else ""
        typer.echo(f"  [{issue.severity}] {loc}{issue.message}")
    typer.echo(f"{len(issues)} issue(s): {errors} error(s), {warnings} warning(s).")


# --- groups ----------------------------------------------------------------


@groups_app.command("list")
def groups_list(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """List all groups and their members."""
    lib = load_bib(file)
    names = groups_ops.list_groups(lib)
    members = {g: groups_ops.list_entries_in_group(lib, g) for g in names}

    if json_output:
        typer.echo(_json.dumps(
            {"status": "success", "action": "groups_list", "file": file, "groups": members},
            indent=2,
        ))
        return

    if not names:
        typer.echo(f"{file}: no groups found.")
        return
    for name in names:
        typer.echo(f"{name} ({len(members[name])}): {', '.join(members[name])}")


def _require_key(lib, key: str) -> None:
    if key not in lib.entries:
        typer.echo(_json.dumps({
            "status": "error",
            "error": "KeyNotFound",
            "message": f"No entry with key {key!r} in the library",
        }, indent=2))
        raise typer.Exit(code=1)


@groups_app.command("add-entry")
def groups_add_entry(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Citation key to add"),
    group: str = typer.Argument(..., help="Group name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Add an entry to a group."""
    lib = load_bib(file)
    _require_key(lib, key)
    pre = _snapshot(lib)
    count = groups_ops.add_to_group(lib, key, group)
    changed, diff_text, modified = _commit(file, lib, pre, dry_run)

    verb = "Would add" if dry_run else "Added"
    _emit(
        json_output,
        {"status": "success", "action": "groups_add_entry", "file": file,
         "dry_run": dry_run, "modified": modified, "modified_entries": changed,
         "key": key, "group": group},
        [f"{verb} {key} to group {group!r} ({count} {_entries(count)} changed)."],
        diff_text, diff,
    )


@groups_app.command("remove-entry")
def groups_remove_entry(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    key: str = typer.Argument(..., help="Citation key to remove"),
    group: str = typer.Argument(..., help="Group name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Remove an entry from a group."""
    lib = load_bib(file)
    _require_key(lib, key)
    pre = _snapshot(lib)
    count = groups_ops.remove_from_group(lib, key, group)
    changed, diff_text, modified = _commit(file, lib, pre, dry_run)

    verb = "Would remove" if dry_run else "Removed"
    _emit(
        json_output,
        {"status": "success", "action": "groups_remove_entry", "file": file,
         "dry_run": dry_run, "modified": modified, "modified_entries": changed,
         "key": key, "group": group},
        [f"{verb} {key} from group {group!r} ({count} {_entries(count)} changed)."],
        diff_text, diff,
    )


# --- keys ------------------------------------------------------------------


@keys_app.command("check")
def keys_check(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report duplicate citation keys."""
    lib = load_bib(file)
    duplicates = keys_ops.duplicate_key_counts(lib)

    if json_output:
        typer.echo(_json.dumps(
            {"status": "success", "action": "keys_check", "file": file,
             "has_duplicates": bool(duplicates), "duplicate_keys": duplicates},
            indent=2,
        ))
        return

    if not duplicates:
        typer.echo(f"{file}: all citation keys are unique.")
        return
    for key, count in duplicates.items():
        typer.echo(f"  {key}: appears {count} times")
    typer.echo(f"{len(duplicates)} duplicated key(s).")


@keys_app.command("generate")
def keys_generate(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Regenerate all citation keys from entry metadata (AuthorYearTitle)."""
    lib = load_bib(file)
    pre = _snapshot(lib)
    renames = keys_ops.regenerate_keys(lib)
    changed, diff_text, modified = _commit(file, lib, pre, dry_run)

    verb = "Would rename" if dry_run else "Renamed"
    human = [f"{verb} {len(renames)} {_entries(len(renames))}."]
    human += [f"  {old} -> {new}" for old, new in renames]
    _emit(
        json_output,
        {"status": "success", "action": "keys_generate", "file": file,
         "dry_run": dry_run, "modified": modified, "modified_entries": changed,
         "renames": [{"old": o, "new": n} for o, n in renames]},
        human, diff_text, diff,
    )


@keys_app.command("repair")
def keys_repair(
    file: str = typer.Argument(..., help="Path to the .bib file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Rename duplicate citation keys so every key is unique."""
    lib = load_bib(file)
    pre = _snapshot(lib)
    renames = keys_ops.repair_duplicate_keys(lib)
    changed, diff_text, modified = _commit(file, lib, pre, dry_run)

    verb = "Would repair" if dry_run else "Repaired"
    human = [f"{verb} {len(renames)} duplicate key(s)."]
    human += [f"  {old} -> {new}" for old, new in renames]
    _emit(
        json_output,
        {"status": "success", "action": "keys_repair", "file": file,
         "dry_run": dry_run, "modified": modified, "modified_entries": changed,
         "renames": [{"old": o, "new": n} for o, n in renames]},
        human, diff_text, diff,
    )


# --- fields ----------------------------------------------------------------


def _build_filter(where: Optional[str]):
    if where is None:
        return None
    try:
        return fields_ops.parse_query(where)
    except ValueError as exc:
        typer.echo(_json.dumps(
            {"status": "error", "error": "InvalidQuery", "message": str(exc)}, indent=2
        ))
        raise typer.Exit(code=1) from exc


def _run_field_op(file, action, op, dry_run, diff, json_output, details, verb):
    lib = load_bib(file)
    pre = _snapshot(lib)
    count = op(lib)
    changed, diff_text, modified = _commit(file, lib, pre, dry_run)
    _emit(
        json_output,
        {"status": "success", "action": action, "file": file, "dry_run": dry_run,
         "modified": modified, "modified_entries": changed, **details},
        [f"{verb} ({count} {_entries(count)} changed)."],
        diff_text, diff,
    )


@fields_app.command("rename")
def fields_rename(
    file: str = typer.Argument(...),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="New field name"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a field across entries."""
    flt = _build_filter(where)
    _run_field_op(
        file, "fields_rename",
        lambda lib: fields_ops.rename_field(lib, old, new, flt),
        dry_run, diff, json_output,
        {"old": old, "new": new, "where": where},
        f"{'Would rename' if dry_run else 'Renamed'} field {old!r} to {new!r}",
    )


@fields_app.command("move")
def fields_move(
    file: str = typer.Argument(...),
    old: str = typer.Argument(..., help="Existing field name"),
    new: str = typer.Argument(..., help="Target field name"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Move a field to a new name, skipping entries that already have the target."""
    flt = _build_filter(where)
    _run_field_op(
        file, "fields_move",
        lambda lib: fields_ops.move_field(lib, old, new, flt),
        dry_run, diff, json_output,
        {"old": old, "new": new, "where": where},
        f"{'Would move' if dry_run else 'Moved'} field {old!r} to {new!r}",
    )


@fields_app.command("append")
def fields_append(
    file: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Field name"),
    value: str = typer.Argument(..., help="Value to append"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Append a value to a (comma-delimited) field across entries."""
    flt = _build_filter(where)
    _run_field_op(
        file, "fields_append",
        lambda lib: fields_ops.append_field(lib, field, value, flt),
        dry_run, diff, json_output,
        {"field": field, "value": value, "where": where},
        f"{'Would append' if dry_run else 'Appended'} {value!r} to field {field!r}",
    )


@fields_app.command("clear")
def fields_clear(
    file: str = typer.Argument(...),
    field: str = typer.Argument(..., help="Field name to remove"),
    where: Optional[str] = typer.Option(None, "--where", help="Filter expression"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove a field from entries."""
    flt = _build_filter(where)
    _run_field_op(
        file, "fields_clear",
        lambda lib: fields_ops.clear_field(lib, field, flt),
        dry_run, diff, json_output,
        {"field": field, "where": where},
        f"{'Would clear' if dry_run else 'Cleared'} field {field!r}",
    )


# --- capabilities (Phase 3) ------------------------------------------------


@app.command()
def capabilities() -> None:
    """Show tool capabilities."""
    typer.echo("capabilities")


# --- used ------------------------------------------------------------------


@app.command()
def used(
    bib_file: str = typer.Argument(..., help="Path to the .bib library"),
    sources: list[str] = typer.Argument(
        ..., help="One or more .tex/.aux files or directories to scan"
    ),
    out: Optional[str] = typer.Option(
        None, "--out", help="Write a subset .bib containing only the used entries"
    ),
    group: Optional[str] = typer.Option(
        None, "--group", help="Tag used entries into this JabRef group"
    ),
    keyword: Optional[str] = typer.Option(
        None, "--keyword", help="Tag used entries with this keyword"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change without writing"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of changes"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Report which entries are used in LaTeX sources; optionally tag or export them."""
    lib = load_bib(bib_file)
    cited, include_all, scanned = collect_cited_keys(sources)
    report = analyze_usage(lib, cited, include_all=include_all, sources=scanned)

    pre = _snapshot(lib)

    tagged = 0
    tag_field = None
    if group:
        tagged = tag_with_group(lib, report.used, group)
        tag_field = "groups"
    elif keyword:
        tagged = tag_with_keyword(lib, report.used, keyword)
        tag_field = "keywords"

    bib_diff = ""
    if tag_field:
        _, bib_diff, _ = _commit(bib_file, lib, pre, dry_run)

    out_written = False
    if out:
        sub = subset_library(lib, report.used)
        if not dry_run:
            save_bib(sub, out, backup=False)
            out_written = True

    if json_output:
        result = {
            "status": "success",
            "action": "used",
            "input_path": bib_file,
            "dry_run": dry_run,
            "report": report.to_dict(),
            "tagged": {"field": tag_field, "value": group or keyword, "count": tagged}
            if tag_field
            else None,
            "exported": {"path": out, "written": out_written, "count": len(report.used)}
            if out
            else None,
            "would_modify_file": bool(tag_field) and dry_run,
        }
        if diff and bib_diff:
            result["diff"] = bib_diff
        typer.echo(_json.dumps(result, indent=2))
        return

    # Human-readable output
    typer.echo(f"Scanned {len(scanned)} source file(s); {report.cited_count} cited key(s).")
    if report.include_all:
        typer.echo(r"\nocite{*} found — all entries counted as used.")
    typer.echo(f"Used:    {len(report.used)}")
    typer.echo(f"Unused:  {len(report.unused)}")
    typer.echo(f"Missing: {len(report.missing)}")
    if report.missing:
        for key in report.missing:
            typer.echo(f"  - {key}  (cited but not in library)")

    if tag_field:
        verb = "Would tag" if dry_run else "Tagged"
        typer.echo(f'{verb} {tagged} entr{"y" if tagged == 1 else "ies"} '
                   f'with {tag_field} = "{group or keyword}".')
    if out:
        verb = "Would write" if dry_run else "Wrote"
        typer.echo(f"{verb} {len(report.used)} entr"
                   f'{"y" if len(report.used) == 1 else "ies"} to {out}.')
    if diff and bib_diff:
        typer.echo("")
        typer.echo(bib_diff)


if __name__ == "__main__":
    app()
