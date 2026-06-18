# pynakes

Agent-friendly BibTeX, BibLaTeX, and JabRef-compatible bibliography maintenance.

> **Status — v0.1 in development.** The core command-line workflow is usable:
> inspect, lint, groups, citation keys, fields, DOI import, citation-usage
> analysis, normalization, conversion, capabilities JSON, journal title
> commands, JabRef metadata inspection/update, and linked-file validation.
> Merge workflows and linked-file repair are still planned.

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
- Group list/add/remove commands
- Citation-key check/generate/repair commands
- Field rename/move/append/clear and title-capitalization protection
- DOI import via DOI resolver BibTeX content negotiation
- JabRef linked-file validation through `files check`
- AUX/TeX citation analysis with used/unused/missing reporting
- Daily `normalize` routine:
  - title capitalization protection
  - JabRef-style author/editor normalization
  - DOI normalization
  - exact journal mappings and LTWA-style journal abbreviation
- Local pre-commit hooks and GitHub Actions CI
- Capability introspection JSON

## Still Planned

- Deduplication and merge workflows
- Linked-file repair
- Advanced query DSL
- MCP server integration

## Documentation

- [Installation Guide](guides/installation.md)
- [Quick Start](guides/quickstart.md)
- [Usage Guide](guides/usage.md)
- [API Reference](api/index.md)
- [Examples](examples/index.md)
- [Architecture](guides/architecture.md)

## Why pynakes?

BibTeX libraries grow unwieldy: duplicate entries, inconsistent fields, fragile
title casing, and mixed metadata conventions. `pynakes` gives you small,
inspectable operations that preserve human-curated data while making routine
maintenance scriptable.

## License

MIT License. See `LICENSE` in the repository.
