"""CLI command for creating a new library: ``init``.

``init`` scaffolds a new ``.bib`` file, optionally seeded with a metadata profile
(``--type``, ``--key-pattern``, or a profile copied from an existing library via
``--from``). It refuses to overwrite an existing file unless ``--force``, and —
like ``combine``/``split`` — reports the file it creates rather than using the
single-file modify envelope.

When ``--pinax`` is passed with an existing ``.bib`` file, the file is converted
to a Pinax by adding the ``files-dir`` and fetch-policy metadata (no ``--force``
needed — the conversion is additive). ``--agent-guide`` writes an ``AGENTS.md``
template for LLM agents.
"""

from pathlib import Path

import typer

from pynakes.cli_common import _emit, _emit_error, _safe, _verb
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography
from pynakes.filestore import FILES_DIR_KEY
from pynakes.initialize import (
    apply_overrides,
    collect_profile,
    default_profile,
    render_agents_md,
    render_library,
)
from pynakes.io import save_text

# --- init ------------------------------------------------------------------


def _has_pinax_metadata(coll: Bibliography) -> bool:
    """Return True when the bibliography already has a ``files-dir`` set."""
    return any(k.strip().lower() == FILES_DIR_KEY for k in coll.lib.metadata)


def _write_agents_guide(file: str, *, dry_run: bool) -> str | None:
    """Write ``AGENTS.md`` beside ``file``, returning the path or ``None``."""
    if dry_run:
        return None
    agents_path = Path(file).with_name("AGENTS.md")
    agents_path.write_text(render_agents_md(Path(file).stem))
    return str(agents_path)


def _convert_to_pinax(
    coll: Bibliography,
    file: str,
    *,
    dry_run: bool,
    diff: bool,
    json_output: bool,
    agent_guide: bool,
) -> None:
    """Add Pinax metadata to an existing bibliography and optionally write AGENTS.md."""
    stem = Path(file).stem
    warnings: list[str] = []

    if not _has_pinax_metadata(coll):
        coll.set_metadata("files-dir", f"{stem}.files")
        coll.set_metadata("fetch-preprint", "true")
        coll.set_metadata("fetch-source", "true")
        coll.set_metadata("fetch-published", "false")
    else:
        warnings.append("files-dir already set; pinax metadata unchanged")

    store = coll.files
    if store is not None and not dry_run:
        store.ensure_root()

    modified = coll.is_modified
    diff_text = coll.diff() if diff else ""

    if not dry_run and modified:
        coll.commit(backup=True)

    if coll.externally_changed():
        warnings.append("file was modified externally; changes were merged on commit")

    agents_path = _write_agents_guide(file, dry_run=dry_run) if agent_guide else None

    human = [f"Initialized pinax for {file}."]
    if agents_path:
        human.append(f"Wrote agent guide to {agents_path}.")
    if warnings:
        human.extend(warnings)
    payload = {
        "status": "success",
        "action": "init",
        "file": file,
        "dry_run": dry_run,
        "pinax": True,
        "files_dir": f"{stem}.files",
        "modified": modified,
        "agent_guide": agents_path,
        "warnings": warnings,
    }
    _emit(json_output, payload, human, diff_text, diff)


def init(
    file: str = typer.Argument(..., help="Path to the .bib library to create or convert"),
    type_: str | None = typer.Option(
        None, "--type", help="Library dialect: biblatex or bibtex (sets databaseType)"
    ),
    key_pattern: str | None = typer.Option(
        None, "--key-pattern", help="Default citation-key pattern (sets keypatterndefault)"
    ),
    from_: str | None = typer.Option(
        None, "--from", help="Copy the metadata profile from an existing .bib library"
    ),
    pinax: bool = typer.Option(
        False, "--pinax", help="Seed pinax mode (files-dir, fetch-preprint, fetch-source)"
    ),
    agent_guide: bool = typer.Option(
        False,
        "--agent-guide",
        help="Write an AGENTS.md guide for LLM agents (requires --pinax)",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite the target file if it already exists (writes a .bak)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be written without creating the file"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of the new file"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Create or initialize a .bib library.

    With no options it writes a sensible default profile (the BibLaTeX dialect
    and pynakes' default citation-key pattern). ``--type`` / ``--key-pattern``
    override individual settings; ``--from`` replaces the defaults with another
    library's maintenance profile (its conventions, not its group tree or
    TeX-source list). ``--pinax`` seeds pinax mode and, when the file already
    exists, converts it in place. ``--agent-guide`` writes AGENTS.md (only
    meaningful alongside ``--pinax``).
    """
    if type_ is not None and type_ not in {"biblatex", "bibtex"}:
        _emit_error(
            json_output, "InvalidInput", f"Invalid --type {type_!r}; expected biblatex or bibtex"
        )

    exists = Path(file).exists()

    # Pinax conversion: additive metadata update on an existing file.
    if pinax and exists:
        coll = Bibliography.open(file)
        _convert_to_pinax(
            coll, file, dry_run=dry_run, diff=diff, json_output=json_output, agent_guide=agent_guide
        )
        return

    # New file creation: refuse overwrite unless --force.
    if exists and not force:
        _emit_error(
            json_output, "FileExists", f"{file} already exists; pass --force to overwrite it"
        )

    # Base profile: a copied template (authoritative, no defaults injected) or
    # the sensible default profile for a fresh library.
    entries = (
        collect_profile(Bibliography.open(from_).lib) if from_ is not None else default_profile()
    )
    overrides: list[tuple[str, str, str]] = []
    if type_ is not None:
        overrides.append(("databaseType", type_, "jabref"))
    if key_pattern is not None:
        overrides.append(("keypatterndefault", key_pattern, "jabref"))
    if pinax:
        stem = Path(file).stem
        overrides.append(("files-dir", f"{stem}.files", "pynakes"))
        overrides.append(("fetch-preprint", "true", "pynakes"))
        overrides.append(("fetch-source", "true", "pynakes"))
        overrides.append(("fetch-published", "false", "pynakes"))
    entries = apply_overrides(entries, overrides)

    content = render_library(entries)

    original = Path(file).read_bytes().decode("utf-8", "replace") if exists else ""
    diff_text = generate_diff(original, content, file) if diff else ""

    created = False
    if not dry_run:
        result = save_text(content, file, backup=(exists and force))
        if not result.success:
            _emit_error(json_output, "IOError", result.error or "Failed to write the new library")
        created = True

    if pinax and not dry_run:
        coll = Bibliography.open(file)
        store = coll.files
        if store is not None:
            store.ensure_root()

    agents_path = _write_agents_guide(file, dry_run=dry_run) if (agent_guide and pinax) else None

    keys = sorted({entry.key for entry in entries})
    effective = next((e.value for e in entries if e.key.lower() == "databasetype"), None)
    effective_type = effective.strip().rstrip(";").strip().lower() if effective else None

    detail = f" [{effective_type}]" if effective_type else ""
    human = [f"{_verb('create', dry_run)} {file}{detail} with {len(keys)} metadata key(s)."]
    if agents_path:
        human.append(f"Wrote agent guide to {agents_path}.")
    payload = {
        "status": "success",
        "action": "init",
        "file": file,
        "dry_run": dry_run,
        "created": created,
        "pinax": pinax,
        "type": effective_type,
        "from": from_,
        "keys": keys,
        "agent_guide": agents_path,
        "warnings": [],
    }
    _emit(json_output, payload, human, diff_text, diff)


def register(app: typer.Typer) -> None:
    """Register the ``init`` command."""
    app.command()(_safe(init))
