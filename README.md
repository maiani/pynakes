# pynakes

<p align="center">
  <img src="https://raw.githubusercontent.com/maiani/pynakes/main/docs/assets/logo.svg" alt="pynakes logo" width="128">
</p>

[![PyPI](https://img.shields.io/pypi/v/pynakes.svg)](https://pypi.org/project/pynakes/)
[![Python](https://img.shields.io/pypi/pyversions/pynakes.svg)](https://pypi.org/project/pynakes/)
[![CI](https://img.shields.io/github/actions/workflow/status/maiani/pynakes/ci.yml?branch=main)](https://github.com/maiani/pynakes/actions)
[![License](https://img.shields.io/github/license/maiani/pynakes)](https://github.com/maiani/pynakes/blob/main/LICENSE)

> [!WARNING]
> `pynakes` is alpha-quality software. Interfaces and behavior may change between releases.

**pynakes is a reference management engine for BibTeX and BibLaTeX bibliographies and their research materials.**

It curates BibTeX and BibLaTeX bibliographies and optionally manages their PDFs
and source materials. Researchers, applications, and automation use the same
Python API and CLI to acquire references, compare and enrich records, track
citations, and review changes before writing them.

The `.bib` remains authoritative. Edits preserve untouched source, conflicts
are reported explicitly, and previews, diffs, and structured JSON make the work
inspectable. JabRef compatibility keeps existing libraries usable across tools.

Requires Python 3.12+ and is packaged as an OS-independent CLI and library.

Untouched entries write back byte-for-byte — no hidden reformatting, reordering, or re-quoting. The file stays diff-friendly in git and yours for decades.

Named after the *Pinakes*, Callimachus's catalog of the Library of Alexandria — antiquity's first bibliography.
A `.bib` file is the index card; a **pinax** is the card together with the shelf it points at.

## Why pynakes

- **Reviewable by design.** Modifying commands support `--dry-run --diff` for review before writing. Writes are atomic and re-parse-validated; `--backup` optionally retains the previous file. Ambiguous cases — conflicting merges, duplicate DOIs — are reported with exit code `2` rather than guessed.
- **Round-trip fidelity.** An entry you don't touch is written back byte-for-byte. pynakes never normalizes whitespace, reorders fields, or re-quotes values behind your back — so diffs stay tiny and reviewable.
- **Automation and CI support.** JSON output and exit codes, machine-readable
  `capabilities`, structured change plans, and `--strict` / pre-commit gates
  allow callers to inspect outcomes without rewriting bibliography text.
- **Explicit network access.** Network use is limited to `ref import`, `asset
  fetch`, and operations invoked with `--online`.
- **Preservation-first interoperability.** Untouched BibTeX/BibLaTeX source and
  JabRef metadata round-trip unchanged. `pynakes-meta` holds native settings;
  JabRef metadata can be preserved, adopted, and projected explicitly.

## Two workflows

### 1. Reference curation
Load any `.bib` file the BibTeX/BibLaTeX toolchain produces,
then:

- **Inspect** — entry count, encoding, duplicates, JabRef metadata
- **Lint** — validate required fields, DOI shape, key conflicts (CI-gate multiple files)
- **Normalize** — authors, DOIs, months, journals, `saveActions` pipeline
- **Format** — lint-gated, deterministic layout rewrites with portable
  field/entry/block ordering and opt-in safe value wrapping
- **Import** by DOI, repository/preprint id, ISBN, or supported publisher URL,
  with configurable key generation, or add a manual entry
- **Dedupe & merge** — detect and resolve duplicates, with conflict reporting
- **Bulk-edit fields** — set, rename, move, append, clear, or protect fields on matching references
- **Manage groups and keys** — list, rename, repair, generate from patterns
- **Convert** between BibTeX/BibLaTeX dialects; import/export CSL-JSON, RIS,
  MODS, and EndNote; export CSV
- **Track citation usage** — find cited, unused, and missing keys in `.tex` or
  `.aux` sources
- **Scrub** — write a public copy without private fields, metadata blocks, or
  comments, for an arXiv upload or a submission bundle
- **Remove** entries with a single command

All through the standardized lifecycle: load → stage → preview/diff → commit.
JabRef v5.15 interoperability covers metadata preservation and classification,
offline-compatible `saveActions`, all four group types, save-order configuration,
and common key-pattern markers and modifiers. Unsupported formatter names are
reported rather than silently applied. Every modifying command supports
`--dry-run --diff` and atomic writes; backups are opt-in.

### 2. Pinax — references and their materials

Opt in by setting `pinax-files-dir` in the library metadata. Now every citation key can carry materials:

- **arXiv download** — PDFs and source bundles, automatically fetched, verified, and extracted with provenance tracking (source hash, download timestamp)
- **Open-access published PDFs** — discover candidate URLs through DOI metadata,
  OpenAlex, CrossRef, and publisher rules, with source provenance for review
- **`asset fetch`** — download configured materials for all entries or one key
- **`asset check`** / **`asset repair`** — validate presence and detect orphans and manifest drift; reconcile the manifest, with a preview
- **`ref remove`** — removes both the entry and its materials by default
- **Coordinated key edits** — renaming a key moves its materials
- **`corpus combine`/`corpus split`** — materials follow their entries

The `.bib` stays the source of truth. Pinax connects each reference to its
materials and their provenance, so citation-key edits and bibliography
projections can carry the associated files.

## Direction

The ambition is to support a research library throughout its life: acquire and
curate references, assemble a bibliography for a project, keep its materials
traceable, maintain citations as the manuscript changes, and prepare a public
release copy.

The current engine provides those operations for individual bibliographies,
with explicit combine, split, and batch workflows across files. The next planned
step is `Library` and a rebuildable `Catalogue`: search, compare, reconcile,
and analyze a collection without moving its authoritative data into a database.
Graphical clients and agent integrations will use the same engine. These library
and catalogue APIs are planned, not implemented; see [DEVPLAN.md](DEVPLAN.md).

## Installation

```bash
pip install pynakes
```

For development (with test/lint tools):

```bash
git clone https://github.com/maiani/pynakes.git
cd pynakes
pip install -e ".[dev]"
pre-commit install  # enable Ruff and ty checks on commit
```

See the [Installation guide](docs/guides/installation.md) for shell completion and troubleshooting.

## Quick start

### Python

The curated package API covers the common application workflow without going
through the CLI:

```python
from pynakes import Bibliography, CanonicalLayout

bib = Bibliography.open("refs.bib")
issues = bib.lint()

bib.format(CanonicalLayout(field_order="preferred", wrap_values="stable"))
print(bib.diff())
bib.commit(backup=True)
```

`Bibliography` stages changes in memory. Use `preview()`, `diff()`, and
`change_plan()` before `commit()`. Lower-level parsers, writers, models, and
operation modules remain available for applications that need them.

### Command line

```bash
# Create a new library, then inspect and check for issues
pynakes init mylib.bib
pynakes inspect mylib.bib
pynakes lint mylib.bib --json

# Import by DOI, repository id, ISBN, or supported URL, or add one manually
pynakes ref import mylib.bib 10.5555/example
pynakes ref import mylib.bib arXiv:2301.00001
pynakes ref import mylib.bib PMID:12345678
pynakes ref import mylib.bib 978-0-00-000000-2
pynakes ref import mylib.bib INSPIRE:Author:2024abc
pynakes ref import mylib.bib https://link.springer.com/article/10.5555/example
pynakes ref add mylib.bib Manual2026 --field title="Manual Reference" --field year=2026
pynakes ref add  # interactive
pynakes ref show mylib.bib Manual2026
pynakes ref edit mylib.bib Manual2026 --field year=2027 --clear-field note
pynakes ref edit mylib.bib Manual2026  # interactive

# Preview the normalization pass before committing
pynakes normalize mylib.bib --dry-run --diff

# Remove entries by citation key (with pinax material cleanup)
pynakes ref remove mylib.bib DeprecatedKey2020

# Rename a citation key across the .bib file and .tex sources
pynakes keys rename mylib.bib OldKey2020 NewKey2020 paper.tex chapters/

# Fetch configured materials for one entry (Pinax mode)
pynakes asset fetch mylib.bib arXivKey2024

# Search entries
pynakes search mylib.bib "neural network" --json

# Gate a build: fail if any .bib has errors
pynakes lint mylib.bib chapters/*.bib --strict

# Write a public copy for arXiv: no private fields, metadata blocks, or comments
pynakes scrub mylib.bib --out arxiv/refs.bib --diff
pynakes scrub arxiv/refs.bib --check   # exits 1 if anything private is left

# Shell completion for cite keys (bash/zsh/fish)
eval "$(pynakes --show-completion bash)"
```

When the current directory contains exactly one `.bib` file, its path may be omitted from commands that operate on a single library (for example, `pynakes normalize --dry-run`). 

Commands still require an explicit path when there are multiple `.bib` files.

See the [Quick Start guide](docs/guides/quickstart.md) and [Usage guide](docs/guides/usage.md) for the full command surface.

## Write behavior

Bibliography edits use a staged load → preview → commit lifecycle:

- Most modifying commands support `--dry-run` and `--diff`
- Commits prepare and re-parse a temporary file before replacing the destination
- `--backup` retains the previous contents where the command supports it
- Ambiguous operations report a conflict and exit `2`
- `--json` emits structured results for programmatic use

These mechanisms reduce common write risks; they are not a formal guarantee
against every process, operating-system, or storage failure.

## For automated workflows

Scripts and LLM-assisted tools can use the same command interface as interactive
users:

- `--json` returns machine-readable results with status, warnings, and errors
- `pynakes capabilities --json` describes supported operations
- Exit codes: `0` success, `1` error, `2` conflict

See the [LLM Integration guide](docs/guides/llm-integration.md) for the full JSON envelope and recommended workflows.

## Status

This checkout targets v0.7.0: a beta CLI contract and an alpha VS Code client.
Published pre-0.7 releases remain alpha; the Python API is intended to stabilize
at 1.0. From 0.7.0, incompatible CLI, JSON-envelope, and error-code changes
require a documented deprecation period. Pin versions for reproducible workflows.

CI is configured for Python 3.12–3.15 on Linux, Windows, and macOS, with a 90%
coverage floor. Current hardening work and remaining release gates are tracked
in [DEVPLAN.md](DEVPLAN.md).

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

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
