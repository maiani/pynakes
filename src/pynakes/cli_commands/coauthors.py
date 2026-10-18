"""CLI command registration for ``pynakes coauthors``."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from pynakes.cli_choices import CoauthorFormat
from pynakes.cli_commands.analyze import _MAX_AUTHORS_HELP
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _FORCE_OPTION,
    InvalidInputError,
    _emit,
    _emit_error,
    _refuse_existing_output,
    _refuse_input_as_output,
    _require_written,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    bib_file_argument,
    bind_where_filter,
    key_option,
    parse_key_selector,
    where_option,
)
from pynakes.coauthors import (
    CoauthorNetwork,
    UnknownAuthorError,
    coauthor_network,
    library_max_authors,
)
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography
from pynakes.io import _decode_bytes, save_plain_text

#: How many items each list shows in the plain-text summary.
_SHOWN = 10


def coauthors(
    file: str | None = bib_file_argument(),
    focus: list[str] = typer.Option(
        [],
        "--focus",
        help="Show one person's co-authors and the pairs among them (repeatable: several "
        "names form one view, e.g. two spellings of the same person). Written like an "
        "author field: 'Isaac Newton' finds 'Newton, Isaac'",
    ),
    where: str | None = where_option(),
    key: list[str] | None = key_option(),
    max_authors: int | None = typer.Option(None, "--max-authors", help=_MAX_AUTHORS_HELP),
    to: CoauthorFormat | None = typer.Option(
        None,
        "--to",
        help="Render the network as a document: json (the documented schema), graphml, or markdown",
    ),
    out: str | None = typer.Option(
        None, "--out", help="Write the --to document here instead of stdout (- for stdout)"
    ),
    force: bool = _FORCE_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what --out would write without writing it"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of the --out file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Map who has written with whom: co-author pairs, components, and name variants.

    Offline and descriptive, from the `author` field of the selected entries
    (`--where`/`--key`; all entries by default, so `--where 'year >= 2020'`
    slices by time). People are compared as `analyze`'s `authors` section
    compares them, so the counts reconcile with it; names that may be one
    person (`Smith, J.` and `Smith, John`) are listed as candidates, never
    merged. `--focus` restricts the network to one person's co-authors and the
    pairs among them. Entries listing more than `--max-authors` people
    (default 100) count their authors but are not linked. `--to json|graphml|markdown` renders a document, written
    with `--out`.
    """
    file = _resolve_input_bib(file, json_output)
    if max_authors is not None and max_authors < 0:
        raise InvalidInputError("--max-authors must not be negative")
    if out == "-":
        out = None
    if out is not None and to is None:
        raise InvalidInputError("--out writes a document; name its format with --to")
    if out is not None:
        _refuse_input_as_output(json_output, out, [file])
        _refuse_existing_output(json_output, out, force)
    coll = Bibliography.open(file)
    warnings: list[dict] = []
    selector = bind_where_filter(coll, where, keys=key, warnings=warnings)
    selected_keys = parse_key_selector(key)
    missing = [name for name in selected_keys if name not in coll.lib.entries]
    if missing:
        _emit_error(
            json_output,
            "KeyNotFound",
            f"No reference with key {', '.join(map(repr, missing))}",
            action="coauthors",
        )
    entries = [entry for entry in coll.lib.entries.values() if selector is None or selector(entry)]
    try:
        limit = library_max_authors(coll.lib) if max_authors is None else max_authors
        network = coauthor_network(entries, focus=focus, max_authors=limit)
    except UnknownAuthorError as exc:
        _emit_error(
            json_output,
            "InvalidInput",
            str(exc),
            action="coauthors",
            name=exc.name,
            candidates=exc.candidates,
        )
    warnings.extend(network.warnings)
    selection = {"where": where, "keys": selected_keys or None, "entries": len(entries)}
    payload: dict[str, object] = {
        "status": "success",
        "action": "coauthors",
        "file": file,
        "source_sha256": _source_sha256(coll),
        "warnings": warnings,
        "selection": selection,
    }
    if to is None:
        if json_output:
            _emit(True, {**payload, "network": network.to_dict()}, [])
        else:
            _emit(False, payload, _summary(file, network))
        return

    source = {"file": file, "sha256": payload["source_sha256"], **selection}
    content = _render(network, to, source, file)
    diff_text = ""
    if out is not None and diff:
        path = Path(out)
        previous = _decode_bytes(path.read_bytes(), path)[0] if path.is_file() else ""
        diff_text = generate_diff(previous, content, out)
    written = False
    if out is not None and not dry_run:
        result = save_plain_text(content, out, backup=backup)
        _require_written(json_output, result, out)
        written = True
    if json_output:
        payload.update(
            to=to.value,
            out=out,
            dry_run=dry_run,
            written=written,
            content=None if out else content,
        )
        _emit(True, payload, [], diff_text, diff)
    elif out is not None:
        verb = "Would write" if dry_run else "Wrote"
        summary = network.summary
        line = (
            f"{verb} the co-author network ({summary['authors']} authors, "
            f"{summary['pairs']} pairs) as {to.value} to {out}."
        )
        _emit(False, payload, [line], diff_text, diff)
    else:
        typer.echo(content.rstrip("\n"))
        for warning in warnings:
            typer.echo(f"warning: {warning.get('message', warning['type'])}", err=True)


def _render(network: CoauthorNetwork, to: CoauthorFormat, source: dict, file: str) -> str:
    """Return the network as the ``--to`` document."""
    if to is CoauthorFormat.GRAPHML:
        return network.to_graphml()
    if to is CoauthorFormat.MARKDOWN:
        return network.to_markdown(f"Co-author network of {Path(file).name}", source=source)
    return json.dumps(network.to_dict(source=source), indent=2, ensure_ascii=False) + "\n"


def _summary(file: str, network: CoauthorNetwork) -> list[str]:
    """Return the plain-text summary: counts, then the head of each list."""
    entries, summary = network.entries, network.summary
    lines = [
        f"{file}: {entries['total']} entries ({entries['coauthored']} co-authored, "
        f"{entries['with_others']} with 'others'), {summary['authors']} authors, "
        f"{summary['pairs']} pairs, {summary['components']} components "
        f"(largest {summary['largest_component']})"
    ]
    if network.focus is not None:
        lines.append("focus: " + "; ".join(item["name"] for item in network.focus))
        collaborators = [a for a in network.authors if not a["focus"]]
        collaborators.sort(key=lambda a: (-a["with_focus"], str(a["name"]).casefold()))
        lines += _listing(
            "co-authors",
            [f"{a['name']}: {a['with_focus']} shared" for a in collaborators],
        )
    lines += _listing(
        "pairs",
        [f"{' — '.join(p['authors'])}: {p['entries']}" for p in network.pairs],
    )
    lines += _listing(
        "name-variant candidates",
        [f"{' / '.join(v['names'])} ({', '.join(v['reasons'])})" for v in network.variants],
    )
    return lines


def _listing(title: str, items: list[str]) -> list[str]:
    if not items:
        return [f"{title}: (none)"]
    lines = [f"{title}:"] + [f"  {item}" for item in items[:_SHOWN]]
    if len(items) > _SHOWN:
        lines.append(f"  ... {len(items) - _SHOWN} more (--json or --to for all)")
    return lines


def register(app: typer.Typer) -> None:
    """Register this command on its Typer application."""
    app.command()(_safe(coauthors))
