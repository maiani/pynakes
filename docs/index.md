# pynakes

A Python library and command-line maintenance engine for BibTeX, BibLaTeX, and
JabRef-compatible files. Pynakes inspects, validates, previews, and applies
bibliography changes while preserving source text it does not modify. Its
in-process API, structured CLI output, and exit codes support applications,
interactive use, scripts, and CI.

> **Status — v0.5 public alpha.** The single-file bibliography engine is
> feature-complete for this release, with Pinax material handling implemented
> through arXiv PDF/source download and open-access published PDF fetches. Until
> v1.0, pynakes does **not** guarantee backward compatibility for the Python API,
> CLI syntax, or JSON envelopes; pin exact `0.x` versions for reproducible
> automation.

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
- DOI import via DOI resolver BibTeX content negotiation
- Deduplication and conservative merge workflows
- Integrity/enrichment workflows with opt-in cached provider lookups
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
