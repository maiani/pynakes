# Usage Guide

This guide documents the currently implemented `pynakes` command surface.

## Command Conventions

Modifying commands support:

- `--dry-run`: show what would change without writing
- `--diff`: include a unified diff
- `--json`: emit structured output where supported

Exit codes:

- `0`: success
- `1`: error, such as parse, I/O, or validation failure
- `2`: conflict, such as duplicate DOI import without `--allow-duplicate`

## inspect

Inspect a `.bib` file.

```bash
pynakes inspect refs.bib
pynakes inspect refs.bib --json
```

JSON output includes file encoding, line ending, entries, duplicate keys, and
lint issues. It also includes structured JabRef library metadata under
`jabref_metadata`.

## lint

Validate entries.

```bash
pynakes lint refs.bib
pynakes lint refs.bib --json
pynakes lint refs.bib chapters/*.bib --strict   # multi-file CI gate
```

Checks include duplicate citation keys, missing required fields by entry type,
malformed DOI fields, missing article DOI warnings, and malformed group fields.

`lint` (along with `keys check`, `files check`, `dedupe check`, and `verify`)
accepts multiple files and supports `--strict`, which exits `1` when a finding
is present so it can gate a build. See [Git Workflows](git-workflows.md) for
pre-commit and CI recipes.

## groups

Manage JabRef-style `groups` fields.

```bash
pynakes groups list refs.bib
pynakes groups list refs.bib --json

pynakes groups add-entry refs.bib KEY "GroupName" --dry-run --diff
pynakes groups add-entry refs.bib KEY "GroupName"

pynakes groups remove-entry refs.bib KEY "GroupName" --dry-run --diff
pynakes groups remove-entry refs.bib KEY "GroupName"
```

## keys

Check, generate, rename, and repair citation keys.

```bash
pynakes keys check refs.bib
pynakes keys check refs.bib --json

pynakes keys generate refs.bib --dry-run --diff
pynakes keys repair refs.bib --dry-run --diff
pynakes keys rename refs.bib OldKey2020 NewKey2020 paper.tex chapters/ --dry-run --diff
```

Generated keys default to `AuthorYearTitle`. JabRef metadata is honored when
present:

```bibtex
@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}
@comment{jabref-meta: keypattern_article:[auth][year][veryshorttitle];}
```

Unsupported JabRef key-pattern markers fail explicitly instead of silently
generating incorrect keys.

`keys rename` updates the entry key in the `.bib` file and matching keys inside
recognized TeX citation commands in the supplied `.tex` files/directories. It
does not edit commented-out citations, and it exits with conflict if the target
key already exists.

### Linked TeX sources

Record the `.tex` files that cite a library once, and the citation-key commands
reuse them — no need to pass paths every time:

```bash
pynakes metadata set refs.bib tex-sources "paper.tex, chapters_src/"
```

```bibtex
@comment{pynakes-meta: tex-sources:paper.tex, chapters_src/;}
```

Paths are stored relative to the `.bib` (so the library stays portable). With it
set, `keys rename refs.bib Old New` updates the linked sources automatically, and
`used refs.bib` scans them when no paths are given. Explicit arguments still
override the metadata. `keys repair` consults the list too, but only to **warn**
when a de-duplicated key is still cited (the citation is ambiguous, so it is not
rewritten).

## metadata

pynakes recognizes **two** structurally identical top-level comment namespaces:

- `@comment{jabref-meta: key:value;}` — JabRef's own library settings.
- `@comment{pynakes-meta: key:value;}` — pynakes' **superset**, for settings
  JabRef cannot represent (pynakes is a superset of JabRef metadata).

`metadata list` shows both, tagged by namespace; reads (`lint`, `normalize`,
key generation) use the **merged** view, where `pynakes-meta` overrides
`jabref-meta` on a conflicting key.

```bash
pynakes metadata list refs.bib
pynakes metadata list refs.bib --json
```

Set a metadata value:

```bash
pynakes metadata set refs.bib databaseType biblatex --dry-run --diff
pynakes metadata set refs.bib databaseType biblatex
```

By default `metadata set` **routes the key automatically for maximum JabRef
compatibility**: keys JabRef understands (library/save/group/file/selector/
key-pattern, e.g. `databaseType`, `saveOrderConfig`, `saveActions`,
`groupstree`, `fileDirectory*`, `selector_*`, `keypatterndefault`,
`keypattern_<entrytype>`) go to `jabref-meta`; anything JabRef cannot represent
goes to `pynakes-meta`. Force a target with `--namespace jabref|pynakes`.

```bash
# pynakes-only setting → lands in pynakes-meta automatically
pynakes metadata set refs.bib normalize-journal-style abbreviated
# force a key into jabref-meta (requires --allow-unknown if JabRef won't know it)
pynakes metadata set refs.bib myKey myValue --namespace jabref --allow-unknown
```

Unknown metadata blocks are preserved byte-for-byte. Writing an unrecognized key
into `jabref-meta` requires `--allow-unknown` (so JabRef's namespace is not
polluted); `pynakes-meta` accepts any key. `metadata set` exits with conflict
code `2` if duplicate blocks in the target namespace make an update ambiguous.

## fields

Edit fields surgically while preserving entry formatting.

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
pynakes fields move refs.bib journal journaltitle --dry-run --diff
pynakes fields append refs.bib keywords "AI" --dry-run --diff
pynakes fields clear refs.bib abstract --dry-run --diff
```

Supported filters:

```bash
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"'

pynakes fields clear refs.bib doi --where 'type = book'
pynakes fields clear refs.bib note --where 'doi exists'
```

Title capitalization protection:

```bash
pynakes fields protect-title refs.bib --dry-run --diff
pynakes fields protect-title refs.bib --field booktitle --term Proceedings
```

This protects acronyms, uppercase/digit tokens, mixed-case terms such as
`LaTeX`, and explicit terms.

## doi import

Import a BibTeX entry from a DOI.

```bash
pynakes doi import refs.bib 10.5555/example --dry-run --diff
pynakes doi import refs.bib https://doi.org/10.5555/example
```

Options:

```bash
pynakes doi import refs.bib 10.5555/example --key ManualKey2026
pynakes doi import refs.bib 10.5555/example --key-source provider
pynakes doi import refs.bib 10.5555/example --allow-duplicate
```

The command fetches BibTeX through DOI resolver content negotiation and checks
for existing matching DOI fields before importing.

## files

Validate JabRef linked files stored in `file` fields.

```bash
pynakes files check refs.bib
pynakes files check refs.bib --json
pynakes files check refs.bib --root ~/papers --json
```

The checker parses plain paths and JabRef descriptors such as:

```bibtex
file = {Paper:papers/Smith2020.pdf:PDF}
file = {file1.pdf:path/file1.pdf:PDF; file2.pdf:path/file2.pdf:PDF}
file = {:/path/to/folder:directory}
```

Relative paths are resolved against the `.bib` file directory, repeated
`--root` directories, and JabRef `fileDirectory*` metadata. It reports `ok`,
`missing`, `wrong_type`, and `unresolved` statuses. This command is read-only;
repair is planned separately.

## normalize

Run the daily maintenance pass.

```bash
pynakes normalize refs.bib --dry-run --diff
pynakes normalize refs.bib
```

Default behavior:

- protect capitalization in title-like fields
- normalize author/editor lists in JabRef style
- normalize DOI values
- abbreviate journal titles using exact mappings and LTWA-style generation

Useful overrides:

```bash
pynakes normalize refs.bib --author-style conservative
pynakes normalize refs.bib --journal-style none
pynakes normalize refs.bib --journal-style full
pynakes normalize refs.bib --title-protection off
pynakes normalize refs.bib --doi-normalization off
```

Journal source tables:

```bash
pynakes normalize refs.bib --journal-table journals.csv --ltwa-table ltwa.csv
```

`journals.csv` accepts `title`, `abbreviation`, and optional `issn` columns.
LTWA tables accept `Word` and `Abbreviation` columns.

Normalization preferences live in metadata. pynakes-specific settings (no
JabRef equivalent) go in `pynakes-meta`. The canonical keys use a bare
`normalize-` prefix; the older `pynakes-normalize-` spelling is still accepted
as an alias:

```bibtex
@comment{pynakes-meta: normalize-journal-style:none;}
@comment{pynakes-meta: normalize-protect-titles:false;}
@comment{pynakes-meta: protected-terms:Proceedings,OpenAI;}
```

Where JabRef already has a setting, pynakes uses **that**: if the library has
JabRef `saveActions` enabled, `normalize` honors them — a `normalize_names`
formatter on a name field drives author normalization and a
`clean_up_doi`/`short_doi` formatter on `doi` drives DOI cleanup; their absence
disables those steps. An explicit flag or a `pynakes-meta` key overrides.

```bibtex
@comment{jabref-meta: saveActions:enabled;
author[normalize_names]
doi[clean_up_doi]
;}
```

## used

Analyze which entries are cited by `.tex` or `.aux` files.

```bash
pynakes used refs.bib paper.tex paper.aux
pynakes used refs.bib paper.tex --json
```

Tag cited entries:

```bash
pynakes used refs.bib paper.tex --group Cited --dry-run --diff
pynakes used refs.bib paper.tex --keyword cited
```

Export only cited entries:

```bash
pynakes used refs.bib paper.tex --out cited-only.bib
```

## convert

Convert between BibTeX and BibLaTeX field/type conventions.

```bash
pynakes convert refs.bib --to biblatex --dry-run --diff
pynakes convert refs.bib --to bibtex
```

## journals

Abbreviate, expand, or check journal titles.

```bash
pynakes journals abbreviate refs.bib --dry-run --diff
pynakes journals expand refs.bib
pynakes journals check refs.bib --json
```

The journal commands accept the same `--journal-table` and `--ltwa-table`
options as `normalize`.

To use the same lists as JabRef, download a CSV from
[abbrv.jabref.org](https://github.com/JabRef/abbrv.jabref.org) (e.g.
`journals/journal_abbreviations_general.csv`) and pass it directly — pynakes
reads JabRef's headerless `"Full Name","Abbreviation"` format as-is:

```bash
pynakes journals abbreviate refs.bib --journal-table journal_abbreviations_general.csv
pynakes journals expand   refs.bib --journal-table journal_abbreviations_general.csv
```

The same table drives both directions: `abbreviate` maps full → short, `expand`
maps short → full.

## capabilities

Print the machine-readable command/capability description.

```bash
pynakes capabilities
pynakes capabilities --json
```

## dedupe

Detect and conservatively merge duplicate works.

```bash
pynakes dedupe check refs.bib
pynakes dedupe merge refs.bib --dry-run --diff
```

`merge` exits with code `2` when field values disagree and cannot be safely
resolved.

## verify / enrich / published

Integrity and enrichment commands never use the network unless `--online` is
passed. Online provider responses are cached beside the `.bib` file by default,
or in `--cache-dir` when supplied.

```bash
pynakes verify refs.bib --online --strict --json
pynakes enrich refs.bib --online --dry-run --diff
pynakes published refs.bib --online --json
pynakes published refs.bib --online --apply --dry-run --diff
```

`verify --strict` exits with code `1` when warnings or errors are reported.
`enrich` only fills missing fields. `published --apply` preserves the preprint
identifier and only adds missing DOI/journal metadata.

## Best Practices

1. Preview modifying commands with `--dry-run --diff`.
2. Use `--json` for scripts and agent workflows.
3. Run `pynakes lint refs.bib` after bulk changes.
4. Keep exact journal mappings in a local CSV when journal style matters.
5. Commit `.bib` changes separately from unrelated edits for easy review.

## Still Planned

The following commands/features are not implemented yet:

- `entries`
- linked-file repair

## Next Steps

- [Examples](../examples/index.md)
- [Architecture](architecture.md)
- [API Reference](../api/index.md)
