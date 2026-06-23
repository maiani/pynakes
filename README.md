# pynakes

**A headless, round-trip-faithful maintenance toolkit for BibTeX, BibLaTeX, and JabRef-compatible `.bib` libraries.**

`pynakes` makes small, explicit, reviewable changes to bibliography files — without reformatting, reordering, or corrupting the metadata a human or reference manager curated. It is built for researchers, scripts, CI pipelines, and LLM-assisted workflows.

Named after the *Pinakes*, Callimachus's catalog of the Library of Alexandria — antiquity's first bibliography.

## Why pynakes

- **Round-trip fidelity.** An entry you don't touch is written back byte-for-byte. pynakes never normalizes whitespace, reorders fields, or re-quotes values behind your back — so diffs stay tiny and reviewable.
- **JabRef-compatible — and a superset.** It reads JabRef's own metadata and `saveActions`, normalizing the way JabRef would; it adds the `pynakes-meta` namespace only where JabRef has no equivalent.
- **Reviewable by design.** Every modifying command previews as a unified diff (`--dry-run --diff`) before anything is written, then writes atomically with a `.bak` backup.
- **Conservative.** Conversions, deduplication, and enrichment report conflicts and exit `2` rather than guessing.
- **Built for agents and CI.** Stable JSON output and exit codes, machine-readable `capabilities`, and `--strict` / pre-commit gates that lint a bibliography like source code.

## Installation

Not yet published to PyPI. Install from source:

```bash
git clone https://github.com/maiani/pynakes.git
cd pynakes
pip install -e ".[dev]"
```

See [Installation](docs/guides/installation.md) for full setup instructions including shell completion.

## Quick start

```bash
# Inspect a library and check for issues
pynakes inspect refs.bib
pynakes lint refs.bib --json

# Preview the standard maintenance pass
pynakes normalize refs.bib --dry-run --diff

# Import a reference by DOI (preview, then apply)
pynakes doi import refs.bib 10.5555/example --dry-run --diff
pynakes doi import refs.bib 10.5555/example

# Rename a citation key across the .bib file and .tex sources
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/

# Gate a build: fail if any .bib has errors
pynakes lint refs.bib chapters/*.bib --strict
```

See the [Quick Start guide](docs/guides/quickstart.md) and [Usage guide](docs/guides/usage.md) for the full command surface.

## Safety model

Every modifying command:

- Validates before writing (parse errors, conflicts, missing required fields)
- Supports `--dry-run` and `--diff` to preview changes
- Writes atomically and creates a `.bak` backup
- Reports conflicts and exits `2` rather than guessing (e.g. duplicate DOI on import)
- Emits structured JSON (`--json`) for programmatic use

## For scripted and LLM-assisted workflows

`pynakes` is designed to be safe for automation:

- `--json` returns machine-readable results with status, warnings, and errors
- `pynakes capabilities --json` describes supported operations for an agent
- Exit codes: `0` success, `1` error, `2` conflict (safe to retry with user input)

See the [LLM Integration guide](docs/guides/llm-integration.md) for the full JSON envelope and recommended workflows.

## Status

pynakes provides the full single-file maintenance workflow — deduplication/merge,
integrity/enrichment, the JabRef metadata superset with `saveActions` parity, and
pre-commit/CI gating — from the CLI. Parser conformance to the pinned BibTeX and
BibLaTeX input grammars is a hard requirement before the 0.4 release; progress and
the remaining compatibility corpus are tracked in [DEVPLAN.md](DEVPLAN.md).

## Documentation

- [Quick Start](docs/guides/quickstart.md)
- [Usage Guide](docs/guides/usage.md)
- [Installation](docs/guides/installation.md)
- [LLM Integration](docs/guides/llm-integration.md)
- [Git Workflows: pre-commit & CI](docs/guides/git-workflows.md)
- [Architecture](docs/guides/architecture.md)

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Contributions are welcome. Open an issue to discuss the feature or bug, write tests for any new functionality, and ensure `pytest` and `ruff` pass before opening a PR.
