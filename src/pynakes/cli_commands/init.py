"""CLI command for creating a new library: ``init``.

``init`` scaffolds a new ``.bib`` file, optionally seeded with a metadata profile
(``--type``, ``--key-pattern``, or a profile copied from an existing library via
``--from``). It refuses to overwrite an existing file unless ``--force``, and —
like ``combine``/``split`` — reports the file it creates rather than using the
single-file modify envelope.
"""

from pathlib import Path
from typing import Optional

import typer

from pynakes.cli_common import _emit, _emit_error, _safe
from pynakes.diff import generate_diff
from pynakes.initialize import (
    apply_overrides,
    collect_profile,
    default_profile,
    render_library,
)
from pynakes.io import load_bib, save_text

# --- init ------------------------------------------------------------------


def init(
    file: str = typer.Argument(..., help="Path to the new .bib library to create"),
    type_: Optional[str] = typer.Option(
        None, "--type", help="Library dialect: biblatex or bibtex (sets databaseType)"
    ),
    key_pattern: Optional[str] = typer.Option(
        None, "--key-pattern", help="Default citation-key pattern (sets keypatterndefault)"
    ),
    from_: Optional[str] = typer.Option(
        None, "--from", help="Copy the metadata profile from an existing .bib library"
    ),
    pinax: bool = typer.Option(
        False, "--pinax", help="Seed pinax mode (files-dir, fetch-preprint, fetch-source)"
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
    """Create a new .bib library, seeded with a metadata profile.

    With no options it writes a sensible default profile (the BibLaTeX dialect
    and pynakes' default citation-key pattern). ``--type`` / ``--key-pattern``
    override individual settings; ``--from`` replaces the defaults with another
    library's maintenance profile (its conventions, not its group tree or
    TeX-source list). ``--pinax`` also seeds pinax mode (files-dir,
    fetch-preprint, fetch-source).
    """
    if type_ is not None and type_ not in {"biblatex", "bibtex"}:
        _emit_error(
            json_output, "InvalidInput", f"Invalid --type {type_!r}; expected biblatex or bibtex"
        )

    exists = Path(file).exists()
    if exists and not force:
        _emit_error(
            json_output, "FileExists", f"{file} already exists; pass --force to overwrite it"
        )

    # Base profile: a copied template (authoritative, no defaults injected) or
    # the sensible default profile for a fresh library.
    entries = collect_profile(load_bib(from_)) if from_ is not None else default_profile()
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

    keys = sorted({entry.key for entry in entries})
    effective = next((e.value for e in entries if e.key.lower() == "databasetype"), None)
    effective_type = effective.strip().rstrip(";").strip().lower() if effective else None

    verb = "Would create" if dry_run else "Created"
    detail = f" [{effective_type}]" if effective_type else ""
    human = [f"{verb} {file}{detail} with {len(keys)} metadata key(s)."]
    payload = {
        "status": "success",
        "action": "init",
        "file": file,
        "dry_run": dry_run,
        "created": created,
        "type": effective_type,
        "from": from_,
        "keys": keys,
        "warnings": [],
    }
    _emit(json_output, payload, human, diff_text, diff)


def register(app: typer.Typer) -> None:
    """Register the ``init`` command."""
    app.command()(_safe(init))
