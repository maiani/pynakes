# Public API and compatibility

This page describes the intended public surface for pynakes, but v0.5 is still
an alpha release. Until 1.0, pynakes does **not** guarantee backward
compatibility for the Python API, CLI syntax, or JSON envelopes. Breaking
changes may ship in any `0.x` release, and consumers that need reproducibility
should pin exact versions.

The project still treats these surfaces seriously: intentional incompatibilities
should be documented in `CHANGELOG.md`, and the 1.0 release is expected to
freeze the public contract described below.

The CLI and its JSON envelopes are a co-equal public API. Their command syntax,
exit codes, and response shapes are defined in the [LLM & automation integration
guide](llm-integration.md).

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

The following modules are the intended public Python surface. During the alpha
period, non-underscore classes, functions, exceptions, and constants in these
modules are the supported way to integrate with pynakes, but they are not yet
covered by a backward-compatibility guarantee.

| Area | Stable modules |
| --- | --- |
| Data and lifecycle | `pynakes`, `pynakes.model`, `pynakes.io`, `pynakes.engine`, `pynakes.bibtex_parser`, `pynakes.bibtex_writer`, `pynakes.diff` |
| Bibliography operations | `pynakes.authors`, `pynakes.convert`, `pynakes.importer`, `pynakes.fields`, `pynakes.groups`, `pynakes.journals`, `pynakes.keys`, `pynakes.normalize` |
| Whole-file formatting | `pynakes.canonical` |
| Work-matching evidence | `pynakes.identity` |
| Analysis and maintenance | `pynakes.dedupe`, `pynakes.files`, `pynakes.integrity`, `pynakes.lint`, `pynakes.metadata`, `pynakes.usage` |
| Selection and search | `pynakes.query`, `pynakes.search` |
| Set operations (projections) | `pynakes.setops` |
| Composition | `pynakes.batch` |
| Introspection | `pynakes.capabilities` and `pynakes.__version__` |

The [API reference](../api/index.md) documents the data model, return objects,
exceptions, and typical operation calls. The most important entry points are
available directly as `pynakes.Bibliography`, `pynakes.BibEntry`,
`pynakes.BibFile`, and `pynakes.EntryStore`.

All operation functions mutate a supplied `BibFile` in place unless their
documentation explicitly says otherwise. They return a count, a report, or a
specific result; they do not replace the supplied library. Field/key mutations
continue to use the surgical editing path, preserving untouched entry text.

The `pynakes.setops` projections are the documented exception: `merge_libraries`
and `partition_library` read their inputs read-only and return **new**
`BibFile` objects (a combined library and a label-to-library mapping,
respectively) rather than mutating in place.

## Metadata names

The generic names below are settled before the API freeze because both
`jabref-meta` and `pynakes-meta` use the same structures:

- `model.MetadataBlock`
- `metadata.MetadataUpdate`
- `metadata.DuplicateMetadataError`

The earlier `JabRefMetadata*` names are not part of the public API. Code should
use the generic names above.

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

## Semantic-versioning policy

Starting with 1.0.0:

- Patch releases fix bugs and documentation only; they do not remove or change
  the behavior of the public Python API or CLI/JSON contract.
- Minor releases may add backward-compatible commands, fields, functions,
  options, and report data.
- Major releases are required to remove or rename a supported symbol, alter a
  documented operation result, change a CLI command/option/exit-code meaning,
  or make an incompatible JSON-envelope change.

The `capabilities --json` schema and the documented command envelopes follow
the same policy starting at 1.0.0. Before 1.0, pin exact versions and include
`pynakes.__version__` or `capabilities.VERSION` in diagnostics.
