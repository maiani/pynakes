# Quick Start

Get up and running with `pynakes` in a few minutes.

## 1. Install

For local development:

```bash
git clone https://github.com/user/pynakes.git
cd pynakes
pip install -e ".[dev]"
```

Once published, end users will install with:

```bash
pip install pynakes
```

## 2. Inspect a Bibliography

```bash
pynakes inspect refs.bib
pynakes inspect refs.bib --json
```

`inspect` reports entry count, encoding, line endings, entries, duplicate keys,
JabRef library metadata, and lint issues.

## 3. Inspect JabRef Metadata

```bash
pynakes metadata list refs.bib --json
pynakes metadata set refs.bib databaseType biblatex --dry-run --diff
```

Use `metadata set` for known `jabref-meta` blocks. Unknown blocks are preserved
and duplicate matching blocks are reported as conflicts.

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

## 7. Import by DOI

```bash
pynakes doi import refs.bib 10.5555/example --dry-run --diff
pynakes doi import refs.bib 10.5555/example
```

Citation-key choices:

```bash
pynakes doi import refs.bib 10.5555/example --key-source provider
pynakes doi import refs.bib 10.5555/example --key ManualKey2026
```

By default, imported entries use generated keys. If the library has JabRef
`keypatterndefault` or `keypattern_<entrytype>` metadata, that pattern is used.

## 8. Organize with Groups

```bash
pynakes groups list refs.bib
pynakes groups add-entry refs.bib Smith2020 "Machine Learning" --dry-run --diff
pynakes groups add-entry refs.bib Smith2020 "Machine Learning"
```

## 9. Common Field Operations

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"' \
  --dry-run --diff
pynakes fields protect-title refs.bib --dry-run --diff
```

## 10. Linked Files

```bash
pynakes files check refs.bib --json
pynakes files check refs.bib --root ~/papers
```

This validates JabRef `file` fields without modifying the library.

## 11. Citation Usage

```bash
pynakes used refs.bib paper.tex paper.aux --json
pynakes used refs.bib paper.tex --group Cited --dry-run --diff
pynakes used refs.bib paper.tex --out cited-only.bib
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
