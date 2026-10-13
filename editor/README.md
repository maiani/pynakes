# Pynakes for VS Code

A graphical editor for BibTeX and BibLaTeX bibliographies, powered by the
pynakes reference management engine.

**Status: 0.1.0 alpha prerelease, not yet published.** The UI and settings may
change. See the [changelog](CHANGELOG.md) for changes.

Browse and search entries, organize groups, edit fields and metadata, review
duplicates, follow manuscript citations, and open or fetch linked materials.
Changes go through the engine’s validation and diff review before writing.

## Get started

You need Python 3.12 or newer. The packaged extension includes the pynakes
engine; a separate pynakes installation is not required.

Until publication, build and install a VSIX using the
[development guide](docs/development.md). Then open a `.bib` file with
**Reopen Editor With… → Pynakes Bibliography**, or use **Open with Pynakes**
from the command palette or Explorer context menu.

Click an entry to edit it, double-click to open a local PDF, and use the dock
tabs for findings, diffs, comparisons, duplicates, materials, and metadata.
Ctrl/Cmd-click selects multiple entries; Shift-click selects a range.

## Documentation

- [User guide](docs/usage.md): navigation, selection, editing, groups, metadata,
  citations, materials, and review before applying changes.
- [Configuration](docs/configuration.md): settings, PDF behavior, and which
  engine runs.
- [Architecture](docs/architecture.md): the engine boundary and project scope.
- [Development and packaging](docs/development.md): setup, tests, source layout,
  development host, and alpha VSIX builds.

This is the client for bibliographies belonging to a document or repository.
It shares bibliography behavior with the engine and has no parser or metadata
schema of its own. Repository contributors should also read
[AGENTS.md](../AGENTS.md).
