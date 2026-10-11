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

| Module | Outstanding diagnostics | Rule families |
| --- | ---: | --- |
| `_engine_helpers.py` | 8 | `invalid-argument-type`, `unresolved-attribute` |
| `_integrity_published.py` | 2 | `invalid-argument-type`, `not-iterable` |
| `bibtex_writer.py` | 10 | `invalid-argument-type`, `unresolved-attribute` |
| `canonical.py` | 5 | `invalid-argument-type` |
| `cli.py` | 3 | `invalid-argument-type`, `invalid-assignment` |
| `cli_commands/dedupe.py` | 1 | `invalid-argument-type` |
| `cli_commands/fetch.py` | 10 | `invalid-argument-type` |
| `cli_commands/fields.py` | 1 | `call-non-callable` |
| `cli_commands/format.py` | 3 | `invalid-argument-type`, `unresolved-attribute` |
| `cli_commands/import_ref.py` | 2 | `invalid-argument-type` |
| `cli_commands/init.py` | 2 | `invalid-argument-type` |
| `cli_commands/inspect.py` | 1 | `invalid-argument-type` |
| `cli_commands/integrity.py` | 7 | `invalid-argument-type` |
| `cli_commands/keys.py` | 1 | `invalid-argument-type` |
| `cli_commands/remove.py` | 2 | `invalid-argument-type` |
| `cli_commands/search.py` | 1 | `unresolved-attribute` |
| `cli_commands/setops.py` | 1 | `invalid-argument-type` |
| `cli_commands/show.py` | 2 | `invalid-argument-type`, `unresolved-attribute` |
| `cli_common.py` | 5 | `invalid-assignment`, `invalid-return-type`, `invalid-type-form` |
| `cli_discovery.py` | 31 | `invalid-argument-type`, `invalid-assignment`, `invalid-attribute-access`, `invalid-method-override`, `unresolved-attribute` |
| `cli_surface.py` | 1 | `invalid-assignment` |
| `fetch.py` | 1 | `invalid-argument-type` |
| `filestore.py` | 2 | `invalid-assignment`, `invalid-attribute-override` |
| `formatters/_pages.py` | 1 | `unresolved-attribute` |
| `interchange/_shared.py` | 1 | `unsupported-operator` |
| `interchange/ris.py` | 4 | `invalid-argument-type`, `invalid-assignment` |
| `model.py` | 3 | `invalid-argument-type`, `no-matching-overload` |
| `providers/_http.py` | 2 | `invalid-context-manager` |
| `providers/registry.py` | 1 | `unresolved-attribute` |
| `query.py` | 4 | `invalid-assignment`, `unresolved-attribute` |
