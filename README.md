# pynakes

<p align="center">
  <img src="https://raw.githubusercontent.com/maiani/pynakes/main/docs/assets/logo.svg" alt="pynakes logo" width="128">
</p>

[![PyPI](https://img.shields.io/pypi/v/pynakes.svg)](https://pypi.org/project/pynakes/)
[![Python](https://img.shields.io/pypi/pyversions/pynakes.svg)](https://pypi.org/project/pynakes/)
[![CI](https://img.shields.io/github/actions/workflow/status/maiani/pynakes/ci.yml?branch=main)](https://github.com/maiani/pynakes/actions)
[![License](https://img.shields.io/github/license/maiani/pynakes)](https://github.com/maiani/pynakes/blob/main/LICENSE)

**pynakes is a reference management engine for BibTeX and BibLaTeX
bibliographies and their research materials**, exposed through a Python library
and CLI.

Acquire and curate references, compare and enrich records, organize groups,
track citations in manuscripts, and optionally manage PDFs and source bundles
through **Pinax**, addressed by citation key. The `.bib` remains authoritative,
and JabRef interoperability keeps existing libraries usable across tools.

> **Release preparation:** this checkout targets **pynakes 0.7.0 Beta** and the
> **VS Code editor 0.1.0 Alpha**, neither published yet. The Python API is
> experimental until 1.0; the 0.7 CLI, JSON envelope, and error codes follow the
> [compatibility policy](https://github.com/maiani/pynakes/blob/main/docs/guides/public-api.md).
> See the [release checklist](https://github.com/maiani/pynakes/blob/main/RELEASE.md)
> for remaining gates.

## What it offers

- **Source preservation.** Untouched entries write back byte-for-byte. Surgical
  edits keep diffs focused; whole-file formatting is an explicit operation.
- **Review before writing.** Preview changes with `--dry-run --diff`. Writes are
  atomic and re-parse-validated, backups are optional, and ambiguous operations
  report conflicts rather than guessing.
- **Reference management.** Import, search, lint, normalize, deduplicate, edit,
  convert, and export references. Track TeX citations and prepare scrubbed public
  copies without altering the working library.
- **References and materials together.** Pinax tracks PDFs, source bundles, and
  provenance. Materials can follow entries through citation-key changes and
  bibliography combine/split operations.
- **Research reads.** Compare a set of papers through bounded, paged reads of
  their abstracts, materials, and recorded provenance; save selections as named
  queries; describe a library's coverage with `analyze`; and map its co-author
  network with `coauthors`.
- **Automation.** Structured JSON, change plans, exit codes, and machine-readable
  capabilities support scripts, CI, and agent workflows. Network access is
  explicit.

## Install

Requires **Python 3.12+** on Linux, macOS, or Windows. Install the published
release with:

```sh
pip install pynakes
```

Or install the CLI as an isolated tool with [uv](https://docs.astral.sh/uv/guides/tools/):

```sh
uv tool install pynakes
```

For this development checkout and optional tooling, see the
[installation guide](https://github.com/maiani/pynakes/blob/main/docs/guides/installation.md).

## Quick start

This offline example creates a bibliography and previews an edit before applying it:

```bash
pynakes init refs.bib
pynakes ref add refs.bib Newton1687 --type book --field author="Isaac Newton" --field title="Principia" --field year=1687 --field publisher="Royal Society"
pynakes inspect refs.bib --json
pynakes ref edit refs.bib Newton1687 --field note="Reviewed" --dry-run --diff
# Apply after reviewing the diff:
pynakes ref edit refs.bib Newton1687 --field note="Reviewed"
pynakes search refs.bib Principia --json
```

When the current directory has exactly one `.bib` file, single-library commands
can infer its path. Otherwise, provide the file explicitly. See the
[quick-start guide](https://github.com/maiani/pynakes/blob/main/docs/guides/quickstart.md)
for imports, normalization, and other workflows.

The Python library uses the same staged lifecycle:

```python
from pynakes import Bibliography, CanonicalLayout

bib = Bibliography.open("refs.bib")
bib.format(CanonicalLayout(field_order="preferred", wrap_values="stable"))
print(bib.diff())
# Commit after reviewing the diff:
bib.commit(backup=True)
```

See the [API reference](https://github.com/maiani/pynakes/blob/main/docs/api/reference.md)
for `preview()`, `change_plan()`, and the other library operations.

## VS Code editor

The [editor companion](https://github.com/maiani/pynakes/blob/main/editor/README.md)
provides a bibliography table, entry and metadata editing, groups, citation
navigation, and material access using the same engine. It is a project-scoped
editor, currently an unpublished alpha. Its
[user guide](https://github.com/maiani/pynakes/blob/main/editor/docs/usage.md) and
[build instructions](https://github.com/maiani/pynakes/blob/main/editor/docs/development.md)
are maintained separately.

## Documentation

- [Usage and commands](https://github.com/maiani/pynakes/blob/main/docs/guides/usage.md)
- [Pinax: references and their materials](https://github.com/maiani/pynakes/blob/main/docs/guides/pinax.md)
- [Metadata settings](https://github.com/maiani/pynakes/blob/main/docs/guides/metadata-reference.md)
- [JabRef compatibility](https://github.com/maiani/pynakes/blob/main/docs/guides/jabref-compatibility.md)
- [Network and privacy](https://github.com/maiani/pynakes/blob/main/docs/guides/network-and-privacy.md)
- [Automation and JSON contract](https://github.com/maiani/pynakes/blob/main/docs/guides/llm-integration.md)
- [Git workflows and CI](https://github.com/maiani/pynakes/blob/main/docs/guides/git-workflows.md)
- [Architecture](https://github.com/maiani/pynakes/blob/main/docs/guides/architecture.md)

The planned `Library` and rebuildable `Catalogue` APIs extend this engine to
collection-wide work; they are not implemented yet. See the
[vision](https://github.com/maiani/pynakes/blob/main/docs/vision.md) and
[development plan](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md).
Release history is in the [changelog](https://github.com/maiani/pynakes/blob/main/CHANGELOG.md).

## Contributing and license

See [CONTRIBUTING.md](https://github.com/maiani/pynakes/blob/main/CONTRIBUTING.md)
for development setup and checks. Licensed under
[MIT](https://github.com/maiani/pynakes/blob/main/LICENSE).

Named after the *Pinakes*, Callimachus’s catalogue of the Library of Alexandria.
A `.bib` is the index card; a **pinax** is the card together with the shelf it points at.
