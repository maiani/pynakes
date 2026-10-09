# Quick Start

Get up and running with `pynakes` in a few minutes.

## 1. Install

For normal use:

```bash
pip install pynakes
```

For local development:

```bash
git clone https://github.com/maiani/pynakes.git
cd pynakes
pip install -e ".[dev]"
```

## 2. Inspect a Bibliography

```bash
pynakes inspect refs.bib
pynakes inspect refs.bib --json
```

`inspect` reports entry count, encoding, line endings, entries, duplicate keys,
and JabRef library metadata. Use `lint` for validation findings.

## 3. Inspect and Set Metadata

```bash
pynakes metadata list refs.bib --json
pynakes metadata set refs.bib dialect biblatex --dry-run --diff
```

`metadata set` accepts pynakes-native keys (e.g. `dialect`, `key-pattern`, which
land in `pynakes-meta`) as well as JabRef-native keys (e.g. `databaseType`).
Unknown blocks are preserved and duplicate matching blocks are reported as
conflicts. See the [JabRef compatibility guide](jabref-compatibility.md) for how
native keys relate to their JabRef equivalents.

## 4. Check for Issues

```bash
pynakes lint refs.bib
pynakes lint refs.bib --json
```

Lint currently checks duplicate keys, required fields, DOI shape, missing DOI
warnings for articles, and broken group field formatting.

## 5. Preview a Maintenance Pass

```bash
pynakes normalize refs.bib --dry-run --diff
```

The default normalization pass protects title capitalization, normalizes
author/editor names in JabRef style, normalizes DOI fields, and abbreviates
known journal titles using exact mappings and LTWA-style word rules.

## 6. Apply the Maintenance Pass

```bash
pynakes normalize refs.bib
```

To keep author names in their current order and only normalize separators:

```bash
pynakes normalize refs.bib --author-style conservative
```

To use local journal data:

```bash
pynakes normalize refs.bib --journal-table journals.csv --ltwa-table ltwa.csv
```

`journals.csv` should contain `title`, `abbreviation`, and optional `issn`
columns. LTWA tables should contain `Word` and `Abbreviation` columns.

## 7. Import or add a reference

```bash
pynakes ref import refs.bib 10.5555/example --dry-run --diff
pynakes ref import refs.bib 10.5555/example
pynakes ref import refs.bib arXiv:2301.00001
pynakes ref import refs.bib arXiv:2301.00001 --fetch
pynakes ref add refs.bib Manual2026 --field title="Manual Reference" --field year=2026
```

Citation-key choices:

```bash
pynakes ref import refs.bib 10.5555/example --key-source provider
pynakes ref import refs.bib 10.5555/example --key ManualKey2026
```

By default, imported entries use generated keys. If the library stores a
`key-pattern` or `key-pattern-<entrytype>` (or JabRef's
`keypatterndefault`/`keypattern_<entrytype>` as a fallback), that pattern is used.
`--fetch` also downloads configured Pinax materials for the new entry: arXiv
preprint artifacts when an arXiv id is present, and published PDFs when
`pinax-fetch-policy` can resolve an open-access DOI copy.

## 8. Organize with Groups

```bash
pynakes groups list refs.bib
pynakes groups add-entry refs.bib Smith2020 "Machine Learning" --dry-run --diff
pynakes groups add-entry refs.bib Smith2020 "Machine Learning"
```

## 9. Common Field Operations

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
pynakes fields append refs.bib keywords "transformers" \
  --where 'title contains "neural network"' \
  --dry-run --diff
pynakes fields protect-title refs.bib --dry-run --diff
```

## 10. Linked Files

```bash
pynakes asset check refs.bib --json
pynakes asset check refs.bib --root ~/papers
```

This validates JabRef `file` fields without modifying the library.

## 11. Citation Usage

```bash
pynakes tex scan refs.bib paper.tex paper.aux --json
pynakes tex scan refs.bib paper.tex --group Cited --dry-run --diff
pynakes tex scan refs.bib paper.tex --out cited-only.bib
```

## Development Checks

```bash
ruff check src tests
ruff format --check src tests
pytest
```

Local hooks:

```bash
pre-commit install
pre-commit run --all-files
```

## Next Steps

- [Full Usage Guide](usage.md)
- [Examples](../examples/index.md)
- [API Reference](../api/index.md)
