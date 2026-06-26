"""CLI command registration for ``convert``.

``convert`` is the single format-conversion command. With a dialect target
(``bibtex``/``biblatex``) it edits the ``.bib`` in place, surgically, with the
usual diff/commit workflow. With an interchange format it reads the library and
*exports* it (``--to csl-json``/``ris``) or reads a foreign file and *imports*
it to BibTeX (``--from csl-json``/``ris``).
"""

import json as _json
from pathlib import Path
from typing import Optional

import typer

from pynakes.bibtex_writer import write_bib
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _emit_error,
    _entries,
    _finish_mod,
    _safe,
)
from pynakes.engine import Collection
from pynakes.interchange import FORMATS, export_library, import_library
from pynakes.io import load_bib, save_plain_text

_DIALECTS = ("biblatex", "bibtex")

# --- convert -----------------------------------------------------


def convert(
    file: str = typer.Argument(..., help="Path to the input file"),
    to: Optional[str] = typer.Option(
        None,
        "--to",
        help="Target: biblatex, bibtex (in-place dialect), or csl-json, ris (export)",
    ),
    from_format: Optional[str] = typer.Option(
        None,
        "--from",
        help="Import the input from this interchange format (csl-json, ris) to BibTeX",
    ),
    out: Optional[str] = typer.Option(
        None, "--out", help="Write export/import output here instead of stdout"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff (dialect conversion)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Convert a library between BibTeX/BibLaTeX dialects and interchange formats."""
    if from_format is not None:
        _convert_import(file, from_format, to, out, dry_run, json_output, backup)
        return

    if to is None:
        _emit_error(
            json_output,
            "MissingConvertTarget",
            "--to is required: biblatex/bibtex (dialect), or csl-json/ris (export); "
            "or use --from to import",
        )

    if to in _DIALECTS:
        _convert_dialect(file, to, dry_run, diff, json_output, backup)
        return

    if to in FORMATS:
        _convert_export(file, to, out, dry_run, json_output, backup)
        return

    _emit_error(
        json_output,
        "UnknownConvertTarget",
        f"Unknown target {to!r}; choose biblatex, bibtex, {', or '.join(FORMATS)}",
    )


def _convert_dialect(
    file: str, to: str, dry_run: bool, diff: bool, json_output: bool, backup: bool
) -> None:
    coll = Collection.open(file)
    report = coll.convert(to)  # raises ValueError on an unknown target

    verb = "Would convert" if dry_run else "Converted"
    human = [
        f"{verb} {report.entries} {_entries(report.entries)} to {report.target}.",
        "  "
        f"fields_renamed={report.fields_renamed}, "
        f"types_changed={report.types_changed}, dates_changed={report.dates_changed}",
    ]
    if report.warnings:
        human.append(f"  {len(report.warnings)} warning(s).")

    _finish_mod(
        file,
        "convert",
        coll,
        dry_run,
        diff,
        json_output,
        human,
        warnings=report.warnings,
        operations=report.operations,
        backup=backup,
    )


def _convert_export(
    file: str, to: str, out: Optional[str], dry_run: bool, json_output: bool, backup: bool
) -> None:
    lib = load_bib(file)
    content = export_library(lib, to)
    _emit_conversion(
        file, "bibtex", to, content, len(lib.entries), out, dry_run, json_output, backup
    )


def _convert_import(
    file: str,
    from_format: str,
    to: Optional[str],
    out: Optional[str],
    dry_run: bool,
    json_output: bool,
    backup: bool,
) -> None:
    if from_format not in FORMATS:
        _emit_error(
            json_output,
            "UnknownConvertSource",
            f"Unknown --from format {from_format!r}; choose {' or '.join(FORMATS)}",
        )
    if to is not None and to not in _DIALECTS:
        _emit_error(
            json_output,
            "UnsupportedConversion",
            f"Importing from {from_format!r} produces BibTeX; foreign --to {to!r} is unsupported",
        )

    text = Path(file).read_text(encoding="utf-8")
    lib = import_library(text, from_format)
    content = write_bib(lib)
    _emit_conversion(
        file, from_format, "bibtex", content, len(lib.entries), out, dry_run, json_output, backup
    )


def _emit_conversion(
    file: str,
    from_format: str,
    to_format: str,
    content: str,
    entry_count: int,
    out: Optional[str],
    dry_run: bool,
    json_output: bool,
    backup: bool,
) -> None:
    """Emit the result of an export/import: write to ``out`` or stream to stdout."""
    written = False
    if out and not dry_run:
        save_plain_text(content, out, backup=backup)
        written = True

    if json_output:
        result = {
            "status": "success",
            "action": "convert",
            "file": file,
            "from": from_format,
            "to": to_format,
            "entry_count": entry_count,
            "dry_run": dry_run,
            "out": out,
            "written": written,
            "content": None if out else content,
        }
        typer.echo(_json.dumps(result, indent=2))
        return

    if out:
        verb = "Would write" if dry_run else "Wrote"
        typer.echo(
            f"{verb} {entry_count} {_entries(entry_count)} as {to_format} to {out} "
            f"(from {from_format})."
        )
    else:
        typer.echo(content)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(convert))
