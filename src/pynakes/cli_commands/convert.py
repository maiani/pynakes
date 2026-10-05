"""CLI command registration for ``convert``.

``convert`` is the single format-conversion command. With a dialect target
(``bibtex``/``biblatex``) it edits the ``.bib`` in place, surgically, with the
usual diff/commit workflow. With an interchange format it reads the library and
*exports* it (``--to csl-json``/``ris``/``mods``/``endnote``/``csv``) or reads a foreign
file and *imports* it to BibTeX (``--from csl-json``/``ris``/``mods``/``endnote``).
"""

import hashlib
from pathlib import Path

import typer

from pynakes.bibtex_writer import write_bib
from pynakes.cli_choices import ConvertTarget, ImportFormat
from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    _FORCE_OPTION,
    RunParams,
    _check_expected_digest,
    _check_expected_sha256,
    _emit,
    _emit_error,
    _entries,
    _finish_mod,
    _refuse_existing_output,
    _refuse_input_as_output,
    _require_written,
    _resolve_input_bib,
    _safe,
    _source_sha256,
    _verb,
)
from pynakes.diff import generate_diff
from pynakes.engine import Bibliography
from pynakes.interchange import export_library, import_library
from pynakes.io import save_plain_text

_DIALECTS = ("biblatex", "bibtex")

# --- convert -----------------------------------------------------


def convert(
    file: str | None = typer.Argument(
        None, help="Path to the input file (default: auto-detect single .bib in cwd)"
    ),
    to: ConvertTarget | None = typer.Option(
        None,
        "--to",
        help="Target: a dialect (converted in place) or an interchange format (exported)",
    ),
    from_format: ImportFormat | None = typer.Option(
        None,
        "--from",
        help="Import the input from this interchange format to BibTeX",
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help="Write export/import output here instead of stdout (- for stdout)",
    ),
    force: bool = _FORCE_OPTION,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without writing"),
    diff: bool = typer.Option(
        False, "--diff", help="Show a unified diff of the library, or of the --out file"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
) -> None:
    """Convert a library between BibTeX/BibLaTeX dialects and interchange formats."""
    _convert(
        _resolve_input_bib(file, json_output),
        to.value if to is not None else None,
        from_format.value if from_format is not None else None,
        out,
        force,
        RunParams(
            dry_run=dry_run,
            diff=diff,
            json_output=json_output,
            backup=backup,
            expect_sha256=expect_sha256,
        ),
    )


def _convert(
    file: str,
    to: str | None,
    from_format: str | None,
    out: str | None,
    force: bool,
    params: RunParams,
) -> None:
    json_output = params.json_output
    if out == "-":
        out = None
    if from_format is not None:
        if to is not None and to not in _DIALECTS:
            _emit_error(
                json_output,
                "UnsupportedConversion",
                f"Importing from {from_format!r} produces BibTeX; --to {to!r} is an "
                "interchange format",
            )
        _check_output(file, out, force, params)
        _convert_import(file, from_format, out, params)
        return

    if to is None:
        _emit_error(
            json_output,
            "MissingConvertTarget",
            "--to is required: biblatex/bibtex (dialect), or an interchange format (export); "
            "or use --from to import",
        )

    if to in _DIALECTS:
        if out is not None:
            _emit_error(
                json_output,
                "InvalidInput",
                "A dialect conversion edits the library in place; --out applies to an "
                "export or an import",
            )
        _convert_dialect(file, to, params)
        return

    _check_output(file, out, force, params)
    _convert_export(file, to, out, params)


def _check_output(file: str, out: str | None, force: bool, params: RunParams) -> None:
    """Refuse an ``--out`` that is the input, or that exists without ``--force``."""
    if out is None:
        return
    _refuse_input_as_output(params.json_output, out, [file])
    _refuse_existing_output(params.json_output, out, force)


def _convert_dialect(file: str, to: str, params: RunParams) -> None:
    coll = Bibliography.open(file)
    _check_expected_sha256(file, coll, params)
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
        to=to,
        out=None,
        written=False,
    )


def _convert_export(file: str, to: str, out: str | None, params: RunParams) -> None:
    coll = Bibliography.open(file)
    _check_expected_sha256(file, coll, params)
    content = export_library(coll.lib, to)
    _emit_conversion(
        file, _source_sha256(coll), "bibtex", to, content, len(coll.lib.entries), out, params
    )


def _convert_import(file: str, from_format: str, out: str | None, params: RunParams) -> None:
    raw = Path(file).read_bytes()
    lib = import_library(raw.decode("utf-8"), from_format)
    content = write_bib(lib)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    _check_expected_digest(file, source_sha256, params)
    _emit_conversion(
        file, source_sha256, from_format, "bibtex", content, len(lib.entries), out, params
    )


def _emit_conversion(
    file: str,
    source_sha256: str | None,
    from_format: str,
    to_format: str,
    content: str,
    entry_count: int,
    out: str | None,
    params: RunParams,
) -> None:
    """Emit the result of an export/import: write to ``out`` or stream to stdout.

    The input is never modified, so ``modified`` is false and ``plan`` empty;
    what the run writes is ``out``, and ``--diff`` describes that file.
    """
    diff_text = ""
    if out and params.diff:
        previous = Path(out).read_text(encoding="utf-8") if Path(out).is_file() else ""
        diff_text = generate_diff(previous, content, out)
    written = False
    if out and not params.dry_run:
        result = save_plain_text(content, out, backup=params.backup)
        _require_written(params.json_output, result, out)
        written = True

    if params.json_output:
        payload = {
            "status": "success",
            "action": "convert",
            "file": file,
            "source_sha256": source_sha256,
            "dry_run": params.dry_run,
            "modified": False,
            "modified_entries": 0,
            "warnings": [],
            "plan": Bibliography.from_text("").change_plan(),
            "from": from_format,
            "to": to_format,
            "entry_count": entry_count,
            "out": out,
            "written": written,
            "content": None if out else content,
        }
        _emit(True, payload, [], diff_text, params.diff)
        return

    if out:
        _emit(
            False,
            {},
            [
                f"{_verb('write', params, 'Wrote')} {entry_count} {_entries(entry_count)} "
                f"as {to_format} to {out} (from {from_format})."
            ],
            diff_text,
            params.diff,
        )
    else:
        typer.echo(content)


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(_safe(convert))
