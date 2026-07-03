"""CLI command registration for ``convert``.

``convert`` is the single format-conversion command. With a dialect target
(``bibtex``/``biblatex``) it edits the ``.bib`` in place, surgically, with the
usual diff/commit workflow. With an interchange format it reads the library and
*exports* it (``--to csl-json``/``ris``/``mods``/``endnote``/``csv``) or reads a foreign
file and *imports* it to BibTeX (``--from csl-json``/``ris``/``mods``/``endnote``).
"""

import json
from pathlib import Path

import typer

from pynakes.bibtex_writer import write_bib
from pynakes.cli_common import (
    _BACKUP_OPTION,
    RunParams,
    _emit_error,
    _entries,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    _verb,
)
from pynakes.engine import Bibliography
from pynakes.interchange import EXPORT_FORMATS, IMPORT_FORMATS, export_library, import_library
from pynakes.io import save_plain_text

_DIALECTS = ("biblatex", "bibtex")

# --- convert -----------------------------------------------------


def convert(
    file: str | None = typer.Argument(
        None, help="Path to the input file (default: auto-detect single .bib in cwd)"
    ),
    to: str | None = typer.Option(
        None,
        "--to",
        help="Target: biblatex, bibtex (in-place dialect), or interchange format (export)",
    ),
    from_format: str | None = typer.Option(
        None,
        "--from",
        help="Import the input from this interchange format to BibTeX",
    ),
    out: str | None = typer.Option(
        None, "--out", help="Write export/import output here instead of stdout"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(False, "--diff", help="Show a unified diff (dialect conversion)"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
) -> None:
    """Convert a library between BibTeX/BibLaTeX dialects and interchange formats."""
    file = _resolve_input_bib(file, json_output)
    params = RunParams(dry_run=dry_run, diff=diff, json_output=json_output, backup=backup)
    if from_format is not None:
        _convert_import(file, from_format, to, out, params)
        return

    if to is None:
        _emit_error(
            json_output,
            "MissingConvertTarget",
            "--to is required: biblatex/bibtex (dialect), or an interchange format (export); "
            "or use --from to import",
        )

    if to in _DIALECTS:
        _convert_dialect(file, to, params)
        return

    if to in EXPORT_FORMATS:
        _convert_export(file, to, out, params)
        return

    _emit_error(
        json_output,
        "UnknownConvertTarget",
        f"Unknown target {to!r}; choose biblatex, bibtex, {', or '.join(EXPORT_FORMATS)}",
    )


def _convert_dialect(file: str, to: str, params: RunParams) -> None:
    coll = Bibliography.open(file)
    report = coll.convert(to)  # raises ValueError on an unknown target

    human = [
        f"{_verb('convert', params)} {report.entries} {_entries(report.entries)} to {report.target}.",
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
        params,
        human,
        warnings=report.warnings,
        operations=report.operations,
    )


def _convert_export(file: str, to: str, out: str | None, params: RunParams) -> None:
    lib = Bibliography.open(file).lib
    content = export_library(lib, to)
    _emit_conversion(file, "bibtex", to, content, len(lib.entries), out, params)


def _convert_import(
    file: str,
    from_format: str,
    to: str | None,
    out: str | None,
    params: RunParams,
) -> None:
    if from_format not in IMPORT_FORMATS:
        _emit_error(
            params.json_output,
            "UnknownConvertSource",
            f"Unknown --from format {from_format!r}; choose {' or '.join(IMPORT_FORMATS)}",
        )
    if to is not None and to not in _DIALECTS:
        _emit_error(
            params.json_output,
            "UnsupportedConversion",
            f"Importing from {from_format!r} produces BibTeX; foreign --to {to!r} is unsupported",
        )

    text = Path(file).read_text(encoding="utf-8")
    lib = import_library(text, from_format)
    content = write_bib(lib)
    _emit_conversion(file, from_format, "bibtex", content, len(lib.entries), out, params)


def _emit_conversion(
    file: str,
    from_format: str,
    to_format: str,
    content: str,
    entry_count: int,
    out: str | None,
    params: RunParams,
) -> None:
    """Emit the result of an export/import: write to ``out`` or stream to stdout."""
    written = False
    if out and not params.dry_run:
        save_plain_text(content, out, backup=params.backup)
        written = True

    if params.json_output:
        result = {
            "status": "success",
            "action": "convert",
            "file": file,
            "from": from_format,
            "to": to_format,
            "entry_count": entry_count,
            "dry_run": params.dry_run,
            "out": out,
            "written": written,
            "content": None if out else content,
        }
        typer.echo(json.dumps(result, indent=2))
        return

    if out:
        typer.echo(
            f"{_verb('write', params, 'Wrote')} {entry_count} {_entries(entry_count)} as {to_format} to {out} "
            f"(from {from_format})."
        )
    else:
        typer.echo(content)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(convert))
