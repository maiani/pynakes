# Examples

Short recipes for common jobs. Each modifying command is shown with
`--dry-run --diff` first; the [usage guide](../guides/usage.md) explains the
commands and the [command reference](../guides/command-reference.md) lists
their options.

## Example 1: Daily Bibliography Maintenance

Preview, then apply the normalization pass.

```bash
pynakes inspect refs.bib
pynakes lint refs.bib --json

pynakes normalize refs.bib --dry-run --diff
pynakes normalize refs.bib

pynakes lint refs.bib
```

By default `normalize` protects title capitalization, normalizes author/editor
lists in JabRef style, cleans DOI fields, page ranges and month macros, and
leaves journal titles alone unless a journal style is configured.

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

Run (a table applies only when a journal style requests abbreviation):

```bash
pynakes normalize refs.bib --journal-style abbreviated --journal-table journals.csv --dry-run --diff
```

Add an LTWA-style word table when you want broader word-level generation:

```csv
Word,Abbreviation,Language
Polymer,Polym.,English
Science,Sci.,English
```

Run:

```bash
pynakes normalize refs.bib --journal-style abbreviated --ltwa-table ltwa.csv --dry-run --diff
```

## Example 3: Import or Add a Reference

```bash
pynakes ref import refs.bib 10.5555/example --dry-run --diff
pynakes ref import refs.bib 10.5555/example
pynakes ref import refs.bib arXiv:2301.00001
pynakes ref import refs.bib arXiv:2301.00001 --fetch
pynakes ref add refs.bib Manual2026 --field title="Manual Reference" --field year=2026
```

Use the provider key or an explicit key:

```bash
pynakes ref import refs.bib 10.5555/example --key-source provider
pynakes ref import refs.bib 10.5555/example --key Smith2026Example
```

If the DOI already exists, the command exits with a conflict unless you pass
`--allow-duplicate`.

## Example 4: Organize Papers by Topic

```bash
pynakes groups list refs.bib

pynakes groups assign refs.bib Smith2020 "Machine Learning" --dry-run --diff
pynakes groups assign refs.bib Smith2020 "Machine Learning"

pynakes groups unassign refs.bib Smith2020 "Machine Learning" --dry-run --diff
```

## Example 5: Add Keywords to Matching Papers

```bash
pynakes fields append refs.bib keywords "transformers" \
  --where 'title contains "neural network"' \
  --dry-run --diff

pynakes fields append refs.bib keywords "transformers" \
  --where 'title contains "neural network"'
```

`--where` takes the shared selector grammar — comparisons, lists, regular
expressions, fuzzy matches, and `and`/`or`/`not`; see
[Selecting entries](../guides/usage.md#selecting-entries-where).

## Example 6: Protect Title Capitalization

```bash
pynakes normalize refs.bib --only titles --title-protection on --dry-run --diff
pynakes normalize refs.bib --only titles --title-protection on
```

Protect an additional exact term in another title-like field:

```bash
pynakes normalize refs.bib --only titles --title-protection on \
  --title-field booktitle \
  --term Proceedings \
  --dry-run --diff
```

## Example 7: Repair Citation Keys

```bash
pynakes lint refs.bib --only duplicate_key --json
pynakes keys repair refs.bib --dry-run --diff
pynakes keys repair refs.bib
```

Regenerate a key from entry metadata, or regenerate every key explicitly:

```bash
pynakes keys generate refs.bib OldKey2020 --dry-run --diff
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

To act on the cited entries, link the manuscript once and select them with
`--where used`. Tag them:

```bash
pynakes tex add refs.bib paper.tex
pynakes fields append refs.bib groups Cited --where used --dry-run --diff
pynakes fields append refs.bib groups Cited --where used
```

Export a cited-only `.bib` file:

```bash
pynakes combine refs.bib --where used --out cited-only.bib
```

## Example 9: Combine and Split Across Files

Combine two bibliographies into one:

```bash
pynakes combine 1.bib 2.bib --out combined.bib --dedupe --dry-run --diff
```

Combine `1.bib` and `2.bib` and split the result into two outputs — here cited
entries go to `3.bib` and the rest to `4.bib`:

```bash
pynakes split 1.bib 2.bib --tex paper.tex \
  --route 3.bib='used' \
  --route 4.bib='*'
```

Or partition by group instead (first match wins; `*` is the catch-all):

```bash
pynakes split 1.bib 2.bib \
  --route ml.bib='group "Machine Learning"' \
  --route archive.bib='group "Archive"' \
  --route rest.bib='*'
```

## Example 10: Bulk Field Editing

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
pynakes fields move refs.bib school institution --dry-run --diff
pynakes fields clear refs.bib abstract --where 'type = article' --dry-run --diff
```

Apply only the changes you reviewed:

```bash
pynakes fields rename refs.bib journal journaltitle
```

## Example 11: A `.bib` File with Metadata Settings

pynakes reads two top-level metadata namespaces. JabRef writes its own settings
as `@comment{jabref-meta: …}`, one comment per key. pynakes adds a
`@comment{pynakes-meta: …}` namespace for settings JabRef has no place for, and
packs all of its keys into one consolidated block, one `key: value` line per
setting. A bibliography that carries both namespaces looks like this:

```bibtex
@comment{jabref-meta: databaseType:biblatex;}
@comment{jabref-meta: keypatterndefault:[auth][year];}
@comment{jabref-meta: fileDirectory:/home/me/papers;}

@comment{pynakes-meta:
normalize-journal-style: abbreviated
normalize-author-style: jabref
normalize-protected-terms: GPU,API,JSON
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

# Honors normalize-journal-style/normalize-author-style/normalize-protected-terms
# from pynakes-meta:
pynakes normalize refs.bib --dry-run --diff
```

Inspect both namespaces (the merged "effective" view is what operations read):

```bash
pynakes metadata list refs.bib
#   [jabref:known:library] databaseType = biblatex
#   [jabref:known:citation-key] keypatterndefault = [auth][year]
#   [jabref:known:files] fileDirectory = /home/me/papers
#   [pynakes:known:normalization] normalize-journal-style = abbreviated
#   [pynakes:known:normalization] normalize-author-style = jabref
#   [pynakes:known:normalization] normalize-protected-terms = GPU,API,JSON
```

Add a preference. A JabRef-native key lands in `jabref-meta` (so JabRef keeps
seeing it); a pynakes-only key lands in `pynakes-meta` — automatically:

```bash
pynakes metadata set refs.bib databaseType bibtex            # → jabref-meta
pynakes metadata set refs.bib normalize-dois true           # → pynakes-meta
```

For scripted and agent workflows built on `--json`, see
[LLM & automation integration](../guides/llm-integration.md); for repository
gates, [Git workflows](../guides/git-workflows.md).
