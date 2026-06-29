# pynakes

Small, reviewable, deterministic edits to your `.bib` library — for researchers,
scripts, CI, and LLM agents. Reads and writes BibTeX, BibLaTeX, and
JabRef-compatible files without disturbing what it does not change.

> **Status — v0.5 public alpha.** The single-file bibliography engine is
> feature-complete for this release, with Pinax material handling implemented
> through arXiv PDF/source download. Until v1.0, pynakes does **not** guarantee
> backward compatibility for the Python API, CLI syntax, or JSON envelopes; pin
> exact `0.x` versions for reproducible automation.

## Overview

`pynakes` is designed for researchers, scripts, and LLM-assisted workflows that
need reviewable changes to `.bib` files:

- **Safe previews**: modifying commands support `--dry-run` and `--diff`
- **Structured output**: commands support `--json` where useful
- **Round-trip preservation**: unmodified entries, comments, and JabRef metadata stay intact
- **Deterministic behavior**: operations are explicit and testable
- **Conflict-aware**: unsafe cases return errors or conflicts rather than guessing

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
- [Public API & Stability](guides/api-stability.md)
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
