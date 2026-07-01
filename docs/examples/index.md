# Examples

Practical examples for the currently implemented `pynakes` workflow.

## Example 1: Daily Bibliography Maintenance

Preview, then apply the normalization pass.

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

## Example 3: Import or Add a Reference

```bash
pynakes ref import 10.5555/example refs.bib --dry-run --diff
pynakes ref import 10.5555/example refs.bib
pynakes ref import arXiv:2301.00001 refs.bib
pynakes ref import arXiv:2301.00001 refs.bib --fetch
pynakes ref add Manual2026 refs.bib --field title="Manual Reference" --field year=2026
```

Use the provider key or an explicit key:

```bash
pynakes ref import 10.5555/example refs.bib --key-source provider
pynakes ref import 10.5555/example refs.bib --key Smith2026Example
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
pynakes fields append refs.bib keywords "transformers" \
  --where 'title contains "neural network"' \
  --dry-run --diff

pynakes fields append refs.bib keywords "transformers" \
  --where 'title contains "neural network"'
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

Regenerate a key from entry metadata, or regenerate the whole library explicitly:

```bash
pynakes keys generate OldKey2020 refs.bib --dry-run --diff
pynakes keys generate refs.bib --all --dry-run --diff
```

If JabRef citation-key metadata is present, `keys generate` uses it:

```bibtex
@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}
```

Rename one key consistently across the `.bib` file and TeX citations:

```bash
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/ --dry-run --diff
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/
```

## Example 8: Analyze Cited and Unused Entries

```bash
pynakes tex scan refs.bib paper.tex paper.aux --json
```

Tag cited entries:

```bash
pynakes tex scan refs.bib paper.tex --group Cited --dry-run --diff
pynakes tex scan refs.bib paper.tex --group Cited
```

Export a cited-only `.bib` file:

```bash
pynakes tex scan refs.bib paper.tex --out cited-only.bib
```

## Example 8b: Combine and Split Across Files

Combine two libraries into one:

```bash
pynakes corpus combine 1.bib 2.bib --out combined.bib --dedupe --dry-run --diff
```

Combine `1.bib` and `2.bib` and split the result into two outputs — here cited
entries go to `3.bib` and the rest to `4.bib`:

```bash
pynakes corpus split 1.bib 2.bib --tex paper.tex \
  --to 3.bib='used' \
  --to 4.bib='*'
```

Or partition by group instead (first match wins; `*` is the catch-all):

```bash
pynakes corpus split 1.bib 2.bib \
  --to ml.bib='group "Machine Learning"' \
  --to archive.bib='group "Archive"' \
  --to rest.bib='*'
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

## Example 12: A `.bib` file with library metadata

pynakes reads two top-level metadata namespaces. JabRef writes its own settings
as `@comment{jabref-meta: …}`, one comment per key. pynakes adds a
`@comment{pynakes-meta: …}` namespace for settings JabRef has no place for;
because JabRef never reads it, pynakes packs all of its keys into one
consolidated block, one setting per line. Each setting is a `key: value` line — pynakes also reads the older
`key:value;` spelling and rewrites it to this form. A library that carries both
namespaces looks like this:

```bibtex
@comment{jabref-meta: databaseType:biblatex;}
@comment{jabref-meta: keypatterndefault:[auth][year];}
@comment{jabref-meta: fileDirectory:/home/me/papers;}

@comment{pynakes-meta:
normalize-journal-style: abbreviated
normalize-author-style: jabref
protected-terms: GPU,API,JSON
}

@article{Smith2021,
  author = {John Smith},
  title  = {On {GPU} acceleration and {API} design},
  journaltitle = {Journal of Machine Learning Research},
  date   = {2021},
  doi    = {10.1000/example}
}
```

These settings act as **defaults** when you run operations — no flags needed:

```bash
# Honors keypatterndefault from jabref-meta:
pynakes keys generate refs.bib --all --dry-run --diff

# Honors journal-style/author-style/protected-terms from pynakes-meta:
pynakes normalize refs.bib --dry-run --diff
```

Inspect both namespaces (the merged "effective" view is what operations read):

```bash
pynakes metadata list refs.bib
#   [jabref:known:library] databaseType = biblatex
#   [jabref:known:citation-key] keypatterndefault = [auth][year]
#   [jabref:known:files] fileDirectory = /home/me/papers
#   [pynakes:known:pynakes] normalize-journal-style = abbreviated
#   [pynakes:known:pynakes] normalize-author-style = jabref
#   [pynakes:known:pynakes] protected-terms = GPU,API,JSON
```

Add a preference. A JabRef-native key lands in `jabref-meta` (so JabRef keeps
seeing it); a pynakes-only key lands in `pynakes-meta` — automatically:

```bash
pynakes metadata set refs.bib databaseType bibtex            # → jabref-meta
pynakes metadata set refs.bib normalize-dois on             # → pynakes-meta
```

## Next Steps

- [Usage Guide](../guides/usage.md)
- [API Reference](../api/index.md)
- [Architecture](../guides/architecture.md)
