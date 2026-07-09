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

from pynakes._text_utils import strip_jabref_terminator
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _finish_create,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography
from pynakes.filestore import FILES_DIR_KEY
from pynakes.initialize import (
    ProfileEntry,
    apply_overrides,
    collect_profile,
    default_profile,
    render_agents_md,
    render_library,
)
from pynakes.metadata import jabref_projection

# --- init ------------------------------------------------------------------


def _has_pinax_metadata(coll: Bibliography) -> bool:
    """Return True when the bibliography already has a ``files-dir`` set."""
    return any(k.strip().lower() == FILES_DIR_KEY for k in coll.lib.metadata)


def _project_jabref(entries: list[ProfileEntry]) -> list[ProfileEntry]:
    """Append JabRef projections for aliased native keys (for ``init --jabref``).

    Each pynakes-native aliased key (``dialect``, ``key-pattern``…) gains its
    ``jabref-meta`` counterpart (``databaseType``, ``keypatterndefault``…) so the
    library opens JabRef-tracked. Existing JabRef keys are left as-is.
    """
    result = list(entries)
    have = {entry.key.lower() for entry in result}
    for entry in entries:
        if entry.namespace != "pynakes":
            continue
        projection = jabref_projection(entry.key, entry.value)
        if projection is None or projection[0].lower() in have:
            continue
        result.append(ProfileEntry(projection[0], projection[1], "jabref"))
        have.add(projection[0].lower())
    return result


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
    params: RunParams,
    agent_guide: bool,
) -> None:
    """Add Pinax metadata to an existing bibliography and optionally write AGENTS.md."""
    stem = Path(file).stem
    warnings: list[str] = []

    if not _has_pinax_metadata(coll):
        coll.set_metadata("files-dir", f"{stem}.files")
        coll.set_metadata("fetch-policy", "bestpdf")
    else:
        warnings.append("files-dir already set; pinax metadata unchanged")

    store = coll.files
    if store is not None and not params.dry_run:
        store.ensure_root()

    if coll.externally_changed():
        warnings.append("file was modified externally; changes were merged on commit")

    agents_path = _write_agents_guide(file, dry_run=params.dry_run) if agent_guide else None

    extra = {"pinax": True, "files_dir": f"{stem}.files", "agent_guide": agents_path}
    if agents_path:
        warnings.append(f"Wrote agent guide to {agents_path}.")

    _finish_mod(
        file,
        "init",
        coll,
        params,
        [f"Initialized pinax for {file}."] + [f"  {w}" for w in warnings],
        warnings=warnings,
        **extra,
    )


def init(
    file: str | None = typer.Argument(
        None, help="Path to the .bib library (default: auto-detect single .bib in cwd with --pinax)"
    ),
    type_: str | None = typer.Option(
        None, "--type", help="Library dialect: biblatex or bibtex (sets the native 'dialect' key)"
    ),
    key_pattern: str | None = typer.Option(
        None,
        "--key-pattern",
        help="Default citation-key pattern (sets the native 'key-pattern' key)",
    ),
    jabref: bool = typer.Option(
        False,
        "--jabref",
        help="Also emit a JabRef metadata projection (databaseType, keypatterndefault) so the "
        "library opens JabRef-tracked; by default a fresh library is pynakes-native only",
    ),
    from_: str | None = typer.Option(
        None, "--from", help="Copy the metadata profile from an existing .bib library"
    ),
    pinax: bool = typer.Option(False, "--pinax", help="Seed pinax mode (files-dir, fetch-policy)"),
    agent_guide: bool = typer.Option(
        False,
        "--agent-guide",
        help="Write an AGENTS.md guide for LLM agents (requires --pinax)",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite the target file if it already exists"
    ),
    backup: bool = _BACKUP_OPTION,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be written without creating the file"
    ),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff of the new file"),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON", is_eager=True
    ),
) -> None:
    """Create or initialize a .bib library.

    With no options it writes a sensible, pynakes-native default profile (the
    BibLaTeX dialect and pynakes' default citation-key pattern, as the native
    ``dialect``/``key-pattern`` keys in ``pynakes-meta`` — no ``jabref-meta``
    unless requested). ``--type`` / ``--key-pattern`` override individual
    settings; ``--jabref`` also emits the JabRef projection so the library opens
    JabRef-tracked; ``--from`` replaces the defaults with another library's
    maintenance profile (its conventions, not its group tree or TeX-source
    list). ``--pinax`` seeds pinax mode and, when the file already exists,
    converts it in place. ``--agent-guide`` writes AGENTS.md (only meaningful
    alongside ``--pinax``).
    """
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)

    if file is None:
        if pinax:
            file = _resolve_input_bib(None, params.json_output)
        else:
            _emit_error(
                params.json_output,
                "InvalidInput",
                "file argument is required to create a new library; "
                "only --pinax supports auto-detection",
            )

    if type_ is not None and type_ not in {"biblatex", "bibtex"}:
        _emit_error(
            params.json_output,
            "InvalidInput",
            f"Invalid --type {type_!r}; expected biblatex or bibtex",
        )

    exists = Path(file).exists()

    # Pinax conversion: additive metadata update on an existing file.
    if pinax and exists:
        coll = Bibliography.open(file)
        _convert_to_pinax(coll, file, params=params, agent_guide=agent_guide)
        return

    # New file creation: refuse overwrite unless --force.
    if exists and not force:
        _emit_error(
            params.json_output,
            "FileExists",
            f"{file} already exists; pass --force to overwrite it",
        )

    previous_content = Path(file).read_bytes().decode("utf-8", "replace") if exists else ""

    # Base profile: a copied template (authoritative, no defaults injected) or
    # the sensible default profile for a fresh library.
    entries = (
        collect_profile(Bibliography.open(from_).lib) if from_ is not None else default_profile()
    )
    overrides: list[tuple[str, str, str]] = []
    if type_ is not None:
        overrides.append(("dialect", type_, "pynakes"))
    if key_pattern is not None:
        overrides.append(("key-pattern", key_pattern, "pynakes"))
    if pinax:
        stem = Path(file).stem
        overrides.append(("files-dir", f"{stem}.files", "pynakes"))
        overrides.append(("fetch-policy", "bestpdf", "pynakes"))
    entries = apply_overrides(entries, overrides)

    # With --jabref, project the native dialect/key-pattern into their JabRef
    # equivalents so the file opens JabRef-tracked from the start.
    if jabref:
        entries = _project_jabref(entries)

    content = render_library(entries)

    if pinax and not params.dry_run:
        target = Path(file)
        target.with_name(f"{target.stem}.files").mkdir(parents=True, exist_ok=True)

    agents_path = (
        _write_agents_guide(file, dry_run=params.dry_run) if (agent_guide and pinax) else None
    )

    keys = sorted({entry.key for entry in entries})
    effective = next(
        (e.value for e in entries if e.key.lower() in {"dialect", "databasetype"}), None
    )
    effective_type = strip_jabref_terminator(effective).lower() if effective else None

    detail = f" [{effective_type}]" if effective_type else ""
    human = [f"{_verb('create', params)} {file}{detail} with {len(keys)} metadata key(s)."]
    if agents_path:
        human.append(f"Wrote agent guide to {agents_path}.")

    created = not params.dry_run

    _finish_create(
        params=params,
        path=file,
        action="init",
        content=content,
        human=human,
        previous_content=previous_content,
        backup=backup,
        pinax=pinax,
        type=effective_type,
        keys=keys,
        agent_guide=agents_path,
        created=created,
        **{"from": from_},
    )


def register(app: typer.Typer) -> None:
    """Register the ``init`` command."""
    app.command()(_safe(init))
