# Public API and compatibility

This page describes the public surface of the reference management engine
and the compatibility promise attached to each part.

- **The CLI and its JSON envelopes** are a beta contract: commands, options,
  envelope keys, `action` values, exit codes and error codes change
  incompatibly only after a deprecation period (see
  [Compatibility policy](#compatibility-policy)). Their syntax, exit codes and
  response shapes are defined in the
  [LLM & automation integration guide](llm-integration.md).
- **The Python API** is experimental until 1.0. Its changes are documented in
  `CHANGELOG.md` but do not require deprecation. Consumers that need
  reproducibility should pin exact versions.

## Supported Python modules

The package root is a curated convenience API for the common application
workflow:

```python
from pynakes import Bibliography, CanonicalLayout
```

It exports the lifecycle facade, core models, parser/writer and file I/O entry
points, their result types, and the exceptions callers commonly need to handle.
`pynakes.__all__` is the authoritative list. Domain-specific operations remain
in the modules below instead of being duplicated wholesale at package level.

The following modules are the public Python surface. Until 1.0, non-underscore classes, functions, exceptions, and constants in these
modules are the supported way to integrate with pynakes, but they are not yet
covered by a backward-compatibility guarantee.

| Area | Public modules (experimental until 1.0) |
| --- | --- |
| Data and lifecycle | `pynakes`, `pynakes.model`, `pynakes.io`, `pynakes.engine`, `pynakes.bibtex_parser`, `pynakes.bibtex_writer`, `pynakes.diff` |
| Bibliography operations | `pynakes.authors`, `pynakes.convert`, `pynakes.importer`, `pynakes.fields`, `pynakes.groups`, `pynakes.journals`, `pynakes.keys`, `pynakes.normalize` |
| Whole-file formatting | `pynakes.canonical` |
| Work-matching evidence | `pynakes.identity` |
| Analysis and maintenance | `pynakes.dedupe`, `pynakes.files`, `pynakes.integrity`, `pynakes.lint`, `pynakes.metadata`, `pynakes.scrub`, `pynakes.usage` |
| Selection and search | `pynakes.query`, `pynakes.search`, `pynakes.saved_queries` |
| Research reads and analysis | `pynakes.bounded`, `pynakes.entry_reader`, `pynakes.analysis` |
| Set operations (projections) | `pynakes.setops` |
| Composition | `pynakes.batch` |
| Introspection | `pynakes.capabilities` and `pynakes.__version__` |

The [API reference](../api/index.md) documents the data model, return objects,
exceptions, and typical operation calls. The most important entry points are
available directly as `pynakes.Bibliography`, `pynakes.BibEntry`,
`pynakes.BibFile`, and `pynakes.EntryStore`.

Bibliography analysis has one public home: import `analyze`, `AnalysisReport`,
`coauthor_network` and `CoauthorNetwork` from `pynakes.analysis`. The same
module exports `UnknownAuthorError`, `DEFAULT_MAX_AUTHORS`,
`MAX_AUTHORS_SETTING`, `library_max_authors` and `COAUTHOR_SCHEMA`. The
`analyze` and `coauthors` CLI commands both consume this API; graph construction,
variant detection and rendering are private implementation modules.

All operation functions mutate a supplied `BibFile` in place unless their
documentation explicitly says otherwise. They return a count, a report, or a
specific result; they do not replace the supplied `BibFile`. Field/key mutations
use the surgical editing path, preserving untouched entry text.

The `pynakes.setops` projections are the documented exception: `merge_libraries`
and `partition_library` read their inputs read-only and return **new**
`BibFile` objects (a combined bibliography and a label-to-bibliography mapping,
respectively) rather than mutating in place.

## Metadata names

Both `jabref-meta` and `pynakes-meta` use the same structures, under generic
names:

- `model.MetadataBlock`
- `metadata.MetadataUpdate`
- `metadata.DuplicateMetadataError`

`MetadataBlock.value` preserves the parsed metadata payload, including JabRef's
trailing semicolon when the source had one. Use
`MetadataBlock.normalized_value` for display and semantic comparisons, and
`MetadataBlock.raw` when exact source text matters.

## Private implementation surface

A name beginning with `_` is private. Private names, private helpers, and
implementation modules not listed above (`editing`, `formatters`, `cli`,
`cli_common`, and `cli_commands`) may change in any release. Consumers should
not import them or rely on their current behavior.

This rule lets the public modules expose ordinary, readable operation names
without turning parser details, raw-text splicing, or CLI plumbing into a
compatibility burden.

## Compatibility policy

The CLI contract covers command syntax, options, envelope keys, `action`
values, exit codes and error codes. Removing or renaming any of them requires
one minor release in which the old form still works and emits a structured
deprecation warning: an entry in the envelope's `warnings` with
`type: deprecated`, `old`, `new`, and the `removal` release (on stderr outside
`--json`). Deprecated forms are hidden from `--help`; `capabilities` lists every
form currently in its deprecation period under `deprecations`. Minor releases
may add compatible commands, options and report data; patch releases fix bugs
and documentation only. Include the version (`pynakes --version`,
`pynakes.__version__`, or `version` in `capabilities --json`) in diagnostics.

From 1.0.0 the Python API joins the CLI under semantic versioning:

- Patch releases fix bugs and documentation only; they do not remove or change
  the behavior of the public Python API or CLI/JSON contract.
- Minor releases may add backward-compatible commands, fields, functions,
  options, and report data.
- Major releases are required to remove or rename a supported symbol, alter a
  documented operation result, change a CLI command/option/exit-code meaning,
  or make an incompatible JSON-envelope change.

## Stability markers

`capabilities.command_schemas` marks each command `stable` or `experimental`,
and the generated command reference shows the same marker. Every current
command, including the Pinax operations and `combine`/`split`, is stable. An
experimental addition must be explicitly marked before it ships; it has no
compatibility guarantee.

## Release requirements

No known data-loss bugs or uncaught tracebacks are acceptable release
regressions, and the advertised platform and dependency matrix and the
generated documentation must be tested.

Use **Breaking changes** in CHANGELOG for incompatible behavior and
**Deprecated** for old forms entering their deprecation period. Each deprecation
entry identifies the replacement, warning and earliest removal release; each
breaking entry states the migration. Python API changes before 1.0 belong under
Breaking changes even though they do not require a deprecation period.
