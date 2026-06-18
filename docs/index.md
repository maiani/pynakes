# pynakes

Agent-friendly BibTeX library management tool.

> **Status — v0.1 in development.** The features, commands, and APIs in these
> docs describe the *planned* v0.1 surface. The core library (parser, writer,
> model, I/O) is implemented; most CLI commands are still scaffolded stubs.
> See `DEVPLAN.md` and `CHANGELOG.md` in the repo for current build status, and
> treat command examples as the target design until then.

## Overview

**pynakes** is a command-line tool for managing BibTeX bibliographies with safety-first design:

- **Deterministic**: Same input always produces the same output
- **Dry-run by default**: Preview changes with `--dry-run` before committing
- **Structured output**: JSON output for easy automation
- **Safe conflicts**: Conflicts are reported with options, not guesses
- **Atomic operations**: Each operation is independent and composable

Perfect for:
- Organizing large BibTeX libraries
- Cleaning up metadata and citations
- Converting between BibTeX formats
- Automated bibliography curation with agents (Claude, etc.)

## Quick Start

```bash
# Install
pip install pynakes

# Inspect a bibliography
pynakes inspect refs.bib --json

# List groups
pynakes groups list refs.bib

# Lint for issues
pynakes lint refs.bib

# Preview a change
pynakes keys repair refs.bib --dry-run --diff

# Apply the change
pynakes keys repair refs.bib
```

## Features

### Core Operations (v0.1)
- **Parse & write** with round-trip fidelity
- **Group management** (add, remove, list)
- **Citation key repair** (detect duplicates, generate keys)
- **Field operations** (rename, move, append, clear)
- **Linting** (validate required fields, detect issues)
- **Format conversion** (BibTeX ↔ BibLaTeX)
- **Journal abbreviation** (expand/abbreviate journal names)

### Future (v0.2+)
- DOI import integration
- Deduplication and merge
- Configuration profiles
- Advanced query DSL
- MCP server integration

## Installation

```bash
pip install -e .           # Development install
pip install -e ".[dev]"    # With development tools
```

## Documentation

- [Installation Guide](guides/installation.md)
- [Quick Start](guides/quickstart.md)
- [Usage Guide](guides/usage.md)
- [Architecture](guides/architecture.md)
- [API Reference](api/index.md)
- [Examples](examples/index.md)

## Project Status

**Phase 1** (Foundation): In progress
- [x] Project setup
- [x] Data model
- [ ] Parser
- [ ] Writer
- [ ] I/O orchestration
- [ ] Test fixtures

Target: v0.1.0 release in ~4 weeks with 12 core features.

See [DEVPLAN.md](https://github.com/user/pynakes/blob/main/DEVPLAN.md) for the full development roadmap.

## Why pynakes?

BibTeX libraries grow unwieldy: duplicate entries, inconsistent formatting, missing metadata. Existing tools are either too rigid or too unsafe. **pynakes** gives you:

1. **Safety first** — preview changes, atomic writes, backup creation
2. **Agent-friendly** — deterministic, structured output, clear exit codes
3. **Composable** — chain operations, dry-run to verify, apply when ready
4. **Transparent** — see exactly what will change before it happens

## License

MIT License. See [LICENSE](https://github.com/user/pynakes/blob/main/LICENSE) for details.

## Contributing

Contributions welcome! See [CONTRIBUTING.md](https://github.com/user/pynakes/blob/main/CONTRIBUTING.md) for guidelines.

## Support

- **Issues**: [GitHub Issues](https://github.com/user/pynakes/issues)
- **Discussions**: [GitHub Discussions](https://github.com/user/pynakes/discussions)
- **Email**: [andrea.maiani@su.se](mailto:andrea.maiani@su.se)
