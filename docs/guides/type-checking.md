# Type checking

Run `ty check` locally; the same command gates CI and runs in pre-commit.
Astral describes ty as [beta](https://github.com/astral-sh/ty); the development
extra pins the evaluated version. Ty replaces mypy throughout this repository.

The 2026-10-11 trial used ty 0.0.86, Python 3.12 as the type target, and all
supported platforms. The initial run reported 134 diagnostics. Correcting the
source-layout tag casts and the normalization warning annotation, and selecting
all platforms, reduced that to 122 diagnostics. Removing an unreachable import fallback,
accepting read-only manifest rows as mappings, and defaulting an optional
provider DOI to an empty string reduced the final baseline to 118 diagnostics. These are existing
annotation debt in CLI envelopes, callbacks, provider protocols and heterogeneous
source-layout/model structures, rather than observed runtime failures.

`pyproject.toml` records a provisional baseline per module and rule family;
other rules and other modules remain checked. Remove exemptions as annotations
are repaired; do not add exemptions for new code. The previous mypy baseline exempted entire modules; the ty baseline
exempts only the recorded rule families. The conditional `importlib_resources` fallback was removed because supported
Python versions supply `importlib.resources`. Cross-platform ctypes names are
handled by checking all platforms, rather than adding an exemption.

Moving to ty 0.0.93 on 2026-10-28 added no diagnostics. Repairing annotations
then shrank the baseline to 59 diagnostics in 12 modules. What remains is
mostly CLI glue: `**details` envelopes passed to `_finish_mod`, Click
subclasses typed against the click that typer vendors, and monkey-patched
Typer hooks. The rest is the loosely typed source-layout segments and the
injectable URL opener. None is an observed runtime failure.

| Module | Outstanding diagnostics | Rule families |
| --- | ---: | --- |
| `bibtex_writer.py` | 10 | `invalid-argument-type`, `unresolved-attribute` |
| `cli.py` | 2 | `invalid-assignment` |
| `cli_commands/dedupe.py` | 1 | `invalid-argument-type` |
| `cli_commands/import_ref.py` | 2 | `invalid-argument-type` |
| `cli_commands/init.py` | 2 | `invalid-argument-type` |
| `cli_commands/integrity.py` | 4 | `invalid-argument-type` |
| `cli_commands/keys.py` | 1 | `invalid-argument-type` |
| `cli_commands/remove.py` | 2 | `invalid-argument-type` |
| `cli_commands/setops.py` | 1 | `invalid-argument-type` |
| `cli_discovery.py` | 31 | `invalid-argument-type`, `invalid-assignment`, `invalid-attribute-access`, `invalid-method-override`, `unresolved-attribute` |
| `cli_surface.py` | 1 | `invalid-assignment` |
| `providers/_http.py` | 2 | `invalid-context-manager` |
