# Installation

## System Requirements

- Python 3.12 or later
- pip, uv, or an equivalent package manager
- (Optional) git for development installation

## Installation Methods

### From PyPI

Install with pip:

```bash
pip install pynakes
```

### With uv

Install the CLI in an isolated tool environment:

```bash
uv tool install pynakes
```

To use pynakes as a Python library in a uv-managed project, add it as a dependency:

```bash
uv add pynakes
```

See [uv’s tools guide](https://docs.astral.sh/uv/guides/tools/) for tool management.

### Development installation

Clone the repository with its tags and install it in editable mode with the
development and documentation tools (`pytest`, `ruff`, `ty`, `pre-commit`,
`zensical`):

```bash
git clone https://github.com/maiani/pynakes.git
cd pynakes
pip install -e ".[dev,docs]"
```

## Development checks

Run the same checks as CI (see [Type checking](type-checking.md) for `ty`):

```bash
ruff check src tests
ruff format --check src tests
ty check
pytest --cov --cov-fail-under=90
python scripts/command_reference.py
zensical build --strict
```

Install local pre-commit hooks:

```bash
pre-commit install
pre-commit run --all-files
```

GitHub Actions runs these checks on Linux, Windows, and macOS with Python 3.12,
3.13, 3.14, and 3.15, plus once against the lowest dependency versions
`pyproject.toml` declares.

## Shell Completion

Run this in the target bash, zsh, or fish shell. Typer detects the shell;
a shell-name argument is ignored and does not select a different shell:

```bash
pynakes --install-completion
```

To print the completion script for the detected shell, use
`pynakes --show-completion`.

## Troubleshooting

### Command not found

If `pynakes` is not found after installation, ensure the installation directory is in your `$PATH`:

```bash
# Show where pynakes was installed
which pynakes

# Or run via Python module
python -m pynakes --help
```

### Version conflicts

If you see version conflicts during installation, upgrade pip and retry:

```bash
pip install --upgrade pip
pip install pynakes
```

### Development version numbers

The version comes from git tags (setuptools-scm), so install from a clone with
its history and tags: a shallow clone reports a placeholder such as `0.1.dev1`.
Between releases, `pynakes --version` names the next release, the commits since
the last tag, and the commit (for example `1.2.0.dev12+g1a2b3c4`). An editable
install records the version when it is installed; reinstall to refresh it.

## Next steps

- [Quick Start](quickstart.md)
- [Usage](usage.md)
- [Examples](../examples/index.md)
