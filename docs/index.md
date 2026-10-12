# pynakes

**pynakes is a reference management engine for BibTeX and BibLaTeX bibliographies and their research materials.**

Its Python API and CLI help researchers and automation acquire references,
curate BibTeX and BibLaTeX bibliographies, compare and enrich records, track
citations, and optionally manage PDFs and source materials with provenance.
Previewed edits, explicit conflicts and source preservation keep the work
reviewable. JabRef compatibility supports existing libraries and workflows.

The ambition is a research library that stays usable across projects and tools.
The current engine works with individual bibliographies and explicit operations
across files; `Library`, `Catalogue` and broader client integrations are planned
in the [roadmap](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md).

> **Development status.** This checkout targets v0.7.0, with a beta CLI contract
> and a separately versioned experimental VS Code client. The
> Python API is intended to stabilize at 1.0; from 0.7.0 the CLI contract requires
> deprecation before incompatible changes. Pin versions for reproducible use.

## Overview

`pynakes` exposes bounded commands for making reviewable changes to `.bib`
files:

- **Previews**: modifying commands support `--dry-run` and `--diff`
- **Structured output**: commands support `--json` where useful
- **Round-trip preservation**: unmodified entries, comments, and JabRef metadata stay intact
- **Explicit behavior**: local operations are testable and network access is opt-in
- **Conflict-aware**: ambiguous cases return errors or conflicts rather than guessing

## Quick Start

```bash
pip install -e ".[dev]"

pynakes inspect refs.bib
pynakes lint refs.bib --json
pynakes normalize refs.bib --dry-run --diff
pynakes normalize refs.bib
```

## Implemented Features

- BibTeX parsing/writing with duplicate-key preserving entry storage
- JabRef group fields and structured `jabref-meta` parsing/preservation/update
- JabRef citation-key pattern metadata for key generation and DOI imports
- JabRef metadata list/set commands and `inspect --json` metadata output
- Read-only library search with free text, phrase, and field-scoped terms
- Group list/add/remove commands
- Citation-key check/generate/repair commands
- Field rename/move/append/clear and title-capitalization protection
- Reference import through DOI, supported repository identifiers, ISBN and URLs
- Deduplication and conservative merge workflows
- Integrity/enrichment workflows with opt-in online provider lookups
- JabRef linked-file validation through `asset check`
- AUX/TeX citation analysis with used/unused/missing reporting
- Daily `normalize` routine:
  - title capitalization protection
  - JabRef-style author/editor normalization
  - DOI normalization
  - exact journal mappings and LTWA-style journal abbreviation
- Local pre-commit hooks and GitHub Actions CI
- Capability introspection JSON

## Documentation

- [Installation Guide](guides/installation.md)
- [Quick Start](guides/quickstart.md)
- [Usage Guide](guides/usage.md)
- [Public API and compatibility](guides/public-api.md)
- [API Reference](api/index.md)
- [Examples](examples/index.md)
- [Architecture](guides/architecture.md)
- [Philosophy](vision.md)

## Why pynakes?

BibTeX libraries grow unwieldy: duplicate entries, inconsistent fields, fragile
title casing, and mixed metadata conventions. `pynakes` gives you small,
inspectable operations that preserve human-curated data while making routine
maintenance scriptable.

## License

MIT License. See `LICENSE` in the repository.
