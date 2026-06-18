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
```

Checks include duplicate citation keys, missing required fields by entry type,
malformed DOI fields, missing article DOI warnings, and malformed group fields.

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

Check, generate, and repair citation keys.

```bash
pynakes keys check refs.bib
pynakes keys check refs.bib --json

pynakes keys generate refs.bib --dry-run --diff
pynakes keys repair refs.bib --dry-run --diff
```

Generated keys default to `AuthorYearTitle`. JabRef metadata is honored when
present:

```bibtex
@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}
@comment{jabref-meta: keypattern_article:[auth][year][veryshorttitle];}
```

Unsupported JabRef key-pattern markers fail explicitly instead of silently
generating incorrect keys.

## metadata

Inspect and update top-level JabRef `jabref-meta` blocks.

```bash
pynakes metadata list refs.bib
pynakes metadata list refs.bib --json
```

Set a known metadata block:

```bash
pynakes metadata set refs.bib databaseType biblatex --dry-run --diff
pynakes metadata set refs.bib databaseType biblatex
```

Known blocks include JabRef library/save/group/file/selector/key-pattern
metadata such as `databaseType`, `saveOrderConfig`, `saveActions`,
`groupstree`, `groups-search-syntax-version`, `fileDirectory*`,
`selector_*`, `VersionDBStructure`, `keypatterndefault`, and
`keypattern_<entrytype>`.

Unknown metadata blocks are preserved byte-for-byte. `metadata set` refuses to
write unknown keys unless `--allow-unknown` is passed, and exits with conflict
code `2` if duplicate blocks make an update ambiguous.

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

Normalization metadata can be stored in `jabref-meta` comments, for example:

```bibtex
@comment{jabref-meta: pynakes-normalize-journal-style:none;}
@comment{jabref-meta: pynakes-normalize-protect-titles:false;}
@comment{jabref-meta: pynakes-protected-terms:Proceedings,OpenAI;}
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

## capabilities

Print the machine-readable command/capability description.

```bash
pynakes capabilities
pynakes capabilities --json
```

## Best Practices

1. Preview modifying commands with `--dry-run --diff`.
2. Use `--json` for scripts and agent workflows.
3. Run `pynakes lint refs.bib` after bulk changes.
4. Keep exact journal mappings in a local CSV when journal style matters.
5. Commit `.bib` changes separately from unrelated edits for easy review.

## Still Planned

The following commands/features are not implemented yet:

- `entries`
- `dedupe` and `merge`
- linked-file repair

## Next Steps

- [Examples](../examples/index.md)
- [Architecture](architecture.md)
- [API Reference](../api/index.md)
