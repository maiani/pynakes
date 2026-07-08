# pynakes

<p align="center">
  <img src="https://raw.githubusercontent.com/maiani/pynakes/main/docs/assets/logo.svg" alt="pynakes logo" width="128">
</p>

[![PyPI](https://img.shields.io/pypi/v/pynakes.svg)](https://pypi.org/project/pynakes/)
[![Python](https://img.shields.io/pypi/pyversions/pynakes.svg)](https://pypi.org/project/pynakes/)
[![CI](https://img.shields.io/github/actions/workflow/status/maiani/pynakes/ci.yml?branch=main)](https://github.com/maiani/pynakes/actions)
[![License](https://img.shields.io/pypi/l/pynakes.svg)](https://github.com/maiani/pynakes/blob/main/LICENSE)

**Clean, complete, addressable. With or without the papers.** `pynakes` is a Python CLI that makes small, explicit, reviewable changes to `.bib`
files — minimal diffs, dry-run previews, atomic writes, and structured JSON. Deterministic enough to hand to a script, a CI pipeline, or an LLM agent.

Works on Python 3.11+, Linux, macOS, and Windows, with minimal dependencies.

Untouched entries write back byte-for-byte — no hidden reformatting, reordering, or re-quoting. The file stays diff-friendly in git and yours for decades.

Named after the *Pinakes*, Callimachus's catalog of the Library of Alexandria — antiquity's first bibliography.
A `.bib` file is the index card; a **pinax** is the card together with the shelf it points at.

## Why pynakes

- **Reviewable by design.** Every modifying command previews as a unified diff (`--dry-run --diff`) before anything is written, then writes atomically with a `.bak` backup. Ambiguous cases — conflicting merges, duplicate DOIs — are reported with exit code `2` rather than guessed.
- **Round-trip fidelity.** An entry you don't touch is written back byte-for-byte. pynakes never normalizes whitespace, reorders fields, or re-quotes values behind your back — so diffs stay tiny and reviewable.
- **Built for agents and CI.** Stable JSON output and exit codes, machine-readable `capabilities`, and `--strict` / pre-commit gates that lint a bibliography like source code.
- **Deterministic and offline by default.** No hidden time, randomness, or ordering; network access is explicit (`ref import`, `asset fetch`, or `--online`) and confined to the few commands that need it.
- **Losslessly interoperable.** Reads and writes the BibTeX/BibLaTeX toolchain's files unchanged, and round-trips JabRef's own metadata and `saveActions` — adding the `pynakes-meta` namespace only where no existing equivalent exists.

## Two workflows

### 1. Bibliography engine
Load any `.bib` file the BibTeX/BibLaTeX toolchain produces,
then:

- **Inspect** — entry count, encoding, duplicates, JabRef metadata
- **Lint** — validate required fields, DOI shape, key conflicts (CI-gate multiple files)
- **Normalize** — authors, DOIs, months, journals, `saveActions` pipeline
- **Import** by DOI or arXiv identifier, with configurable key generation, or add a manual entry
- **Dedupe & merge** — detect and resolve duplicates, with conflict reporting
- **Edit fields** — rename, move, append, clear, protect title capitalization
- **Manage groups and keys** — list, rename, repair, generate from patterns
- **Convert** between BibTeX/BibLaTeX dialects and CSL-JSON, RIS, MODS, EndNote
- **Track citation usage** — find cited, unused, and missing keys in `.tex` sources
- **Remove** entries with a single command

All through the standardized lifecycle: load → stage →
preview/diff → commit. Full JabRef metadata parity, including round-trip
`saveActions` and group definitions. Every modifying command supports
`--dry-run --diff` before writing, and writes atomically with an optional `.bak` backup.

### 2. Pinax — the corpus layer

Opt in by setting a `files-dir` in the library metadata. Now every citation key can carry materials:

- **arXiv download** — PDFs and source bundles, automatically fetched, verified, and extracted with provenance tracking (source hash, download timestamp)
- **Open-access published PDFs** — resolved from DOI via OpenAlex, CrossRef, and publisher-specific URL overrides; `.published.pdf` lands only for genuinely OA papers, never misidentified repository mirrors
- **`asset fetch`** — download configured materials for all entries or one key
- **`asset check`** — validate presence, detect orphans, verify checksums, optionally fix (`--fix`)
- **`ref remove`** — removes both the entry and its materials 
- **Coordinated key edits** — renaming a key moves its materials
- **`corpus combine`/`corpus split`** — materials follow their entries

The `.bib` stays the source of truth; Pinax just keeps the shelf tidy. 

## Installation

```bash
pip install pynakes
```

For development (with test/lint tools):

```bash
git clone https://github.com/maiani/pynakes.git
cd pynakes
pip install -e ".[dev]"
pre-commit install  # enable ruff hooks on commit
```

See the [Installation guide](docs/guides/installation.md) for shell completion and troubleshooting.

## Quick start

```bash
# Create a new library, then inspect and check for issues
pynakes init mylib.bib
pynakes inspect mylib.bib
pynakes lint mylib.bib --json

# Import a reference by DOI or arXiv id, or add one manually
pynakes ref import 10.5555/example mylib.bib
pynakes ref import arXiv:2301.00001 mylib.bib
pynakes ref add Manual2026 mylib.bib --field title="Manual Reference" --field year=2026

# Preview the normalization pass before committing
pynakes normalize mylib.bib --dry-run --diff

# Remove entries by citation key (with pinax material cleanup)
pynakes ref remove mylib.bib DeprecatedKey2020

# Rename a citation key across the .bib file and .tex sources
pynakes keys rename mylib.bib OldKey2020 NewKey2020 paper.tex chapters/

# Fetch configured materials for one entry (Pinax mode)
pynakes asset fetch arXivKey2024 mylib.bib

# Search entries
pynakes search mylib.bib "neural network" --json

# Gate a build: fail if any .bib has errors
pynakes lint mylib.bib chapters/*.bib --strict

# Shell completion for cite keys (bash/zsh/fish)
eval "$(pynakes --show-completion bash)"
```

When the current directory contains exactly one `.bib` file, its path may be omitted from commands that operate on a single library (for example, `pynakes normalize --dry-run`). 

Commands still require an explicit path when there are multiple `.bib` files.

See the [Quick Start guide](docs/guides/quickstart.md) and [Usage guide](docs/guides/usage.md) for the full command surface.

## Safety model

Every modifying command:

- Validates before writing (parse errors, conflicts, missing required fields)
- Supports `--dry-run` and `--diff` to preview changes
- Writes atomically and optionally creates a `.bak` backup
- Reports conflicts and exits `2` rather than guessing (e.g. duplicate DOI on import)
- Emits structured JSON (`--json`) for programmatic use

## For scripted and LLM-assisted workflows

`pynakes` is designed to be safe for automation:

- `--json` returns machine-readable results with status, warnings, and errors
- `pynakes capabilities --json` describes supported operations for an agent
- Exit codes: `0` success, `1` error, `2` conflict (safe to retry with user input)

See the [LLM Integration guide](docs/guides/llm-integration.md) for the full JSON envelope and recommended workflows.

## Status

v0.5 will be the first public alpha release on PyPI. The single-file bibliography
engine is feature-complete for this release: parser/writer with byte-for-byte
round-trip fidelity, all maintenance operations, full JabRef metadata parity,
and a self-describing agent surface (~1087 tests, ≥90% coverage). The Pinax
corpus layer is fully implemented including arXiv download and open-access
published-PDF import.

Until v1.0, pynakes does **not** guarantee backward compatibility for the Python
API, CLI syntax, or JSON envelopes. The project aims to keep automation
workflows predictable and documents breaking changes in the changelog, but
production users should pin exact `0.x` versions.

Parser conformance is verified against the TeX Live 2026 toolchain (BibTeX 0.99d,
BibLaTeX 3.21, Biber 2.21). The project roadmap is documented in
[DEVPLAN.md](DEVPLAN.md).

## Documentation

- [Quick Start](docs/guides/quickstart.md)
- [Usage Guide](docs/guides/usage.md)
- [Installation](docs/guides/installation.md)
- [LLM Integration](docs/guides/llm-integration.md)
- [Git Workflows: pre-commit & CI](docs/guides/git-workflows.md)
- [Architecture](docs/guides/architecture.md)
- [Pinax — the corpus layer](docs/guides/pinax.md)
- [API Reference](docs/api/reference.md)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Contributions are welcome. Open an issue to discuss the feature or bug, write
tests for any new functionality, and ensure `pytest` and `ruff` pass before
opening a PR.
