# Public API & stability

This page is the authoritative Python API contract for pynakes 1.0. The API is
available in 0.3.0 so consumers can adopt and test it before the 1.0 release.
Until 1.0, any intentional incompatibility will be called out in the changelog;
from 1.0 onward, the semantic-versioning policy below applies.

The CLI and its JSON envelopes are a co-equal public API. Their command syntax,
exit codes, and response shapes are defined in the [LLM & automation integration
guide](llm-integration.md).

## Supported Python modules

Every non-underscore class, function, exception, and constant in the following
modules is public and stable. New names may be added in a minor release;
removing a name or changing its documented behavior is a breaking change.

| Area | Stable modules |
| --- | --- |
| Data and lifecycle | `pynakes.model`, `pynakes.io`, `pynakes.engine`, `pynakes.bibtex_parser`, `pynakes.bibtex_writer`, `pynakes.diff` |
| Bibliography operations | `pynakes.authors`, `pynakes.convert`, `pynakes.doi`, `pynakes.fields`, `pynakes.groups`, `pynakes.journals`, `pynakes.keys`, `pynakes.normalize` |
| Analysis and maintenance | `pynakes.dedupe`, `pynakes.files`, `pynakes.integrity`, `pynakes.lint`, `pynakes.metadata`, `pynakes.usage` |
| Set operations (projections) | `pynakes.setops` |
| Composition | `pynakes.batch` |
| Introspection | `pynakes.capabilities` and `pynakes.__version__` |

The [API reference](../api/index.md) documents the data model, return objects,
exceptions, and typical operation calls. The most important stable entry points
are `model.BibEntry`, `model.BibFile`, `model.EntryStore`, and
`engine.Collection`.

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
the same policy. Consumers that need reproducibility should pin a compatible
major version and use `pynakes.__version__` or `capabilities.VERSION` in their
own diagnostics.
