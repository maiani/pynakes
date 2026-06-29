# Installation

## System Requirements

- Python 3.11 or later
- pip or equivalent package manager
- (Optional) git for development installation

## Installation Methods

### From PyPI (Public Alpha)

Install with pip:

```bash
pip install pynakes
```

### Development Installation

Clone the repository and install in editable mode:

```bash
git clone https://github.com/maiani/pynakes.git
cd pynakes
pip install -e .
```

### With Development Tools

Install with dev dependencies (`pytest`, `ruff`, `pre-commit`):

```bash
pip install -e ".[dev]"
```

## Verification

Verify the installation by checking the help:

```bash
pynakes --help
```

You should see output like:

```
Usage: pynakes [OPTIONS] COMMAND [ARGS]...

 Agent-friendly BibTeX library management tool

╭─ Options ──────────────────────────────────────────────────────────────────╮
│ --version             -V        Show the pynakes version and exit.         │
│ --install-completion            Install completion for the current shell.  │
│ --show-completion               Show completion for the current shell.     │
│ --help                          Show this message and exit.                │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ Inspect & validate ───────────────────────────────────────────────────────╮
│ inspect       Inspect a .bib file structure.                               │
│ search        Search entries by free text, phrases, or field-scoped terms. │
│ lint          Validate entries and report issues.                          │
│ verify        Verify entries against authoritative metadata.               │
│ capabilities  Show tool capabilities.                                      │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ Edit references ──────────────────────────────────────────────────────────╮
│ normalize     Normalize entries: titles, authors, journals, DOIs,          │
│               identifier case, and ordering.                               │
│ convert       Convert between BibTeX/BibLaTeX dialects and formats.         │
│ enrich        Conservatively fill missing metadata.                        │
│ ref           Manage individual reference entries → add, import, remove    │
│ dedupe        Detect and merge duplicate works → check, merge              │
│ fields        Edit entry fields → rename, move, append, clear, …           │
│ keys          Work with citation keys → check, generate, repair, rename    │
│ groups        Manage entry groups → list, add-entry, remove-entry          │
│ metadata      Inspect and update library metadata → list, set, …           │
│ tex           Manage linked TeX sources and scan them → list, add, scan, … │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ Create ───────────────────────────────────────────────────────────────────╮
│ init          Create or initialize a .bib library.                         │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ Materials (pinax) ────────────────────────────────────────────────────────╮
│ asset         Fetch and validate Pinax materials → fetch, check            │
╰────────────────────────────────────────────────────────────────────────────╯
╭─ Corpus (multiple files) ──────────────────────────────────────────────────╮
│ corpus        Operate across multiple .bib files → combine, split, batch   │
╰────────────────────────────────────────────────────────────────────────────╯
```

## Development Checks

Run the same checks as CI:

```bash
ruff check src tests
ruff format --check src tests
pytest
```

Install local pre-commit hooks:

```bash
pre-commit install
pre-commit run --all-files
```

GitHub Actions runs these checks on Python 3.11, 3.12, and 3.13.

## Shell Completion

Install shell completion for bash, zsh, or fish:

```bash
# Bash
pynakes --install-completion bash

# Zsh
pynakes --install-completion zsh

# Fish
pynakes --install-completion fish
```

## Troubleshooting

### Command not found

If `pynakes` is not found after installation, ensure the installation directory is in your `$PATH`:

```bash
# Show where pynakes was installed
which pynakes

# Or run via Python module
python -m pynakes --help
```

### Version mismatch

If you see version conflicts during installation, try upgrading pip:

```bash
pip install --upgrade pip
pip install -e .
```

### Development installation issues

For development, ensure you have git and the latest setuptools:

```bash
pip install --upgrade setuptools wheel
pip install -e ".[dev]"
```

## Next Steps

- [Quick Start Guide](quickstart.md)
- [Usage Guide](usage.md)
- [Examples](../examples/index.md)
