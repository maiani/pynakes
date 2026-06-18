# Examples

Practical examples for the currently implemented `pynakes` workflow.

## Example 1: Daily Bibliography Maintenance

Preview, then apply the standard normalization pass.

```bash
pynakes inspect refs.bib
pynakes lint refs.bib --json

pynakes normalize refs.bib --dry-run --diff
pynakes normalize refs.bib

pynakes lint refs.bib
```

`normalize` protects title capitalization, normalizes JabRef-style author/editor
lists, normalizes DOI fields, and abbreviates journal titles.

Use conservative author handling if you do not want `John Smith` rewritten to
`Smith, John`:

```bash
pynakes normalize refs.bib --author-style conservative --dry-run --diff
```

## Example 2: Journal Abbreviation Sources

Prefer exact local mappings by title or ISSN:

```csv
title,abbreviation,issn
Nature Machine Intelligence,Nat. Mach. Intell.,2522-5839
Canonical Journal,Can. J.,1234-567X
```

Run:

```bash
pynakes normalize refs.bib --journal-table journals.csv --dry-run --diff
```

Add an LTWA-style word table when you want broader word-level generation:

```csv
Word,Abbreviation,Language
Polymer,Polym.,English
Science,Sci.,English
```

Run:

```bash
pynakes normalize refs.bib --ltwa-table ltwa.csv --dry-run --diff
```

## Example 3: Import a Reference by DOI

```bash
pynakes doi import refs.bib 10.5555/example --dry-run --diff
pynakes doi import refs.bib 10.5555/example
```

Use the provider key or an explicit key:

```bash
pynakes doi import refs.bib 10.5555/example --key-source provider
pynakes doi import refs.bib 10.5555/example --key Smith2026Example
```

If the DOI already exists, the command exits with a conflict unless you pass
`--allow-duplicate`.

## Example 4: Organize Papers by Topic

```bash
pynakes groups list refs.bib

pynakes groups add-entry refs.bib Smith2020 "Machine Learning" --dry-run --diff
pynakes groups add-entry refs.bib Smith2020 "Machine Learning"

pynakes groups remove-entry refs.bib Smith2020 "Machine Learning" --dry-run --diff
```

## Example 5: Add Keywords to Matching Papers

```bash
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"' \
  --dry-run --diff

pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"'
```

The current filter syntax supports `contains`, `=`, `==`, `exists`, and the
special field `type`.

## Example 6: Protect Title Capitalization

```bash
pynakes fields protect-title refs.bib --dry-run --diff
pynakes fields protect-title refs.bib
```

Protect an additional exact term in another title-like field:

```bash
pynakes fields protect-title refs.bib \
  --field booktitle \
  --term Proceedings \
  --dry-run --diff
```

## Example 7: Repair Citation Keys

```bash
pynakes keys check refs.bib --json
pynakes keys repair refs.bib --dry-run --diff
pynakes keys repair refs.bib
```

Regenerate keys from entry metadata:

```bash
pynakes keys generate refs.bib --dry-run --diff
```

If JabRef citation-key metadata is present, `keys generate` uses it:

```bibtex
@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}
```

## Example 8: Analyze Cited and Unused Entries

```bash
pynakes used refs.bib paper.tex paper.aux --json
```

Tag cited entries:

```bash
pynakes used refs.bib paper.tex --group Cited --dry-run --diff
pynakes used refs.bib paper.tex --group Cited
```

Export a cited-only `.bib` file:

```bash
pynakes used refs.bib paper.tex --out cited-only.bib
```

## Example 9: Batch Field Editing

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
pynakes fields move refs.bib school institution --dry-run --diff
pynakes fields clear refs.bib abstract --where 'type = article' --dry-run --diff
```

Apply only the changes you reviewed:

```bash
pynakes fields rename refs.bib journal journaltitle
```

## Example 10: Repository CI

This repository’s CI runs:

```bash
ruff check src tests
ruff format --check src tests
pytest
```

Install the same local checks:

```bash
pip install -e ".[dev]"
pre-commit install
pre-commit run --all-files
```

## Example 11: Agent-Friendly JSON Workflow

```bash
pynakes inspect refs.bib --json > state.json
pynakes lint refs.bib --json > issues.json
pynakes normalize refs.bib --dry-run --diff --json > normalize-preview.json
```

An agent or script can inspect `normalize-preview.json`, show the diff to a
user, and then run the same command without `--dry-run` after approval.

## Next Steps

- [Usage Guide](../guides/usage.md)
- [API Reference](../api/index.md)
- [Architecture](../guides/architecture.md)
