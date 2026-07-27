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

## init

Create a new `.bib` library, seeded with a metadata profile. With no options it
writes a sensible default — the BibLaTeX dialect and pynakes' default
citation-key pattern (`[auth][year][veryshorttitle]`) — so the library works with
`keys generate` and `normalize` out of the box. It refuses to overwrite an
existing file unless `--force`; pass `--backup` to keep a `.bak` copy.

```bash
pynakes init refs.bib                          # default profile (biblatex)
pynakes init refs.bib --type bibtex            # choose the dialect
pynakes init refs.bib --key-pattern '[auth][year]'
pynakes init refs.bib --from template.bib      # copy another library's profile
pynakes init refs.bib --dry-run --diff         # preview the seed file
```

`--from` copies the template's *conventions* — dialect, key patterns,
`saveActions`, and pynakes normalization/lint settings — but not its own content
(group tree, linked TeX sources). `--type` / `--key-pattern` override individual
settings on top of the default (or copied) profile.

## inspect

Inspect a `.bib` file.

```bash
pynakes inspect                           # auto-detects one .bib file
pynakes inspect refs.bib
pynakes inspect refs.bib --json
```

JSON output includes file encoding, line ending, entries, duplicate keys, and
structured JabRef library metadata under `jabref_metadata`. Use `lint` for
validation findings.

## lint

Validate entries.

```bash
pynakes lint                         # auto-detects one .bib file
pynakes lint refs.bib
pynakes lint refs.bib --json
pynakes lint refs.bib chapters/*.bib --strict   # multi-file CI gate
```

Checks include duplicate citation keys, dialect-aware missing required fields by
entry type, malformed DOI fields, missing article DOI warnings, malformed group
fields, and mixed-case entry types or field names. BibLaTeX required-field
validation follows the official BibLaTeX manual from CTAN, section 2.1 entry
types and aliases:
<https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf>. It
also verifies the lintable parts of a stored library profile: citation-key
patterns, journal style, profile-required fields, and title brace protection.
Casing and profile findings are warnings; run `normalize` to repair formatting
issues surgically.

`pynakes normalize refs.bib` also repairs bare full month names such as
`month = june`, which BibTeX interprets as an undefined string reference. It
rewrites them to the standard macro (`month = jun`) and canonicalizes macro
casing (`month = Jan` → `month = jan`), while preserving literals such as
`month = {June}` and declared custom strings.

`lint` (along with `keys check`, `asset check`, `dedupe check`, and `verify`)
accepts multiple files, or auto-detects a single `.bib` in the current directory
when no file is given. Auto-detection ignores RevTeX-generated `*Notes.bib`
auxiliary files; pass one explicitly if you really want to inspect it. These
checks support `--strict`, which exits `1` for errors or profile deviations so
it can gate a build. See
[Library Profile](library-profile.md) for the complete schema and
[Git Workflows](git-workflows.md) for pre-commit and CI recipes.

## groups

Manage JabRef-style `groups` fields and the hierarchical group tree.

### Flat group membership

```bash
pynakes groups list                       # auto-detects one .bib file
pynakes groups list refs.bib
pynakes groups list refs.bib --json

pynakes groups add-entry KEY "GroupName" --dry-run --diff  # auto-detects one .bib file
pynakes groups add-entry refs.bib KEY "GroupName" --dry-run --diff
pynakes groups add-entry refs.bib KEY "GroupName"

pynakes groups remove-entry refs.bib KEY "GroupName" --dry-run --diff
pynakes groups remove-entry refs.bib KEY "GroupName"
```

### Group tree (hierarchical groups)

Group-tree metadata allows parent/child relationships among groups, stored
in the `pynakes-meta` `group-tree` key. Trees with multiple nodes are split
across continuation lines (one node per line) for readability. The tree is
bidirectionally compatible with JabRef's `grouping` block and flat `groups:`
metadata.
```bash
pynakes groups tree refs.bib              # display the group tree
pynakes groups tree refs.bib --json

pynakes groups add-group refs.bib "Machine Learning"                  # root node
pynakes groups add-group refs.bib "Deep Learning" --parent "Machine Learning"
pynakes groups add-group refs.bib "NLP" --parent "Machine Learning" --color "ff0000ff"

pynakes groups rename-group refs.bib "NLP" "Natural Language Processing"

pynakes groups move-group refs.bib "Deep Learning" "Machine Learning"
pynakes groups move-group refs.bib "Deep Learning" ""   # move to root

pynakes groups update-group refs.bib "Deep Learning" --color "00ff00ff" --context 2

pynakes groups remove-group refs.bib "NLP"   # removes group + its children
```

`groups list` reports flat per-entry membership only; it does not currently
expand tree descendants. See [Library Profile](library-profile.md#grouping)
for the tree's node schema and native format.

## keys

Check, generate, rename, and repair citation keys.

```bash
pynakes keys check refs.bib
pynakes keys check refs.bib --json

pynakes keys generate OldKey2020 refs.bib --dry-run --diff
pynakes keys generate refs.bib --all --dry-run --diff
pynakes keys repair --dry-run --diff              # auto-detects one .bib file
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

Pass a citation key to apply that preferred pattern to just one entry, or
`--all` to regenerate the whole library. Like `keys rename`, generated renames
also rewrite matching TeX citations in linked `tex-sources` metadata when it is
configured.

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
set, `keys rename refs.bib Old New` and generated `keys generate` renames update
the linked sources automatically, and `tex scan refs.bib` scans them when no
paths are given. Explicit arguments still override the metadata. `keys repair`
consults the list too, but only to **warn** when a de-duplicated key is still
cited (the citation is ambiguous, so it is not rewritten).

## metadata

pynakes recognizes **two** structurally identical top-level comment namespaces:

- `@comment{jabref-meta: key:value;}` — JabRef's own library settings.
- `@comment{pynakes-meta: key:value;}` — pynakes' **superset**, for settings
  JabRef cannot represent (pynakes is a superset of JabRef metadata).

`metadata list` shows both, tagged by namespace; reads (`lint`, `normalize`,
key generation) use the **merged** view, where `pynakes-meta` overrides
`jabref-meta` on a conflicting key.

The `format` command deterministically places top-level comments before string
declarations, preambles, and entries: `pynakes-meta` first, then `jabref-meta`,
then other comments. It does not consolidate or change metadata values;
metadata consolidation remains a `normalize` concern.

In JSON/API output, each metadata block exposes both forms of the value:
`raw_value` is the parsed payload as stored in the comment, including JabRef's
trailing `;` when present; `value` is the normalized display/semantic form with
that terminator stripped. The exact source comment remains available as the
block's raw text in the Python model.

```bash
pynakes metadata list                     # auto-detects one .bib file
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

Bulk-edit one field operation across all references matching `--where`, while
preserving entry formatting. Use `ref edit` when patching one reference across
several fields.

```bash
pynakes fields set refs.bib journal "Physical Review B" --where 'journal = "Phys. Rev. B"'
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
pynakes fields move refs.bib journal journaltitle --dry-run --diff
pynakes fields append refs.bib keywords "AI" --dry-run --diff
pynakes fields clear refs.bib abstract --dry-run --diff
```

Supported filters:

```bash
pynakes fields append refs.bib keywords "transformers" \
  --where 'title contains "neural network"'

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

## add

Add a manually specified reference entry:

```bash
pynakes ref add Manual2026 refs.bib --field title="Manual Reference" --field year=2026
pynakes ref add Manual2026 refs.bib --type book --field author="Ada Lovelace"
pynakes ref add Manual2026 --field title="Manual Reference"  # auto-detects one .bib file
pynakes ref add  # interactive; auto-detects one .bib file
pynakes ref add --file refs.bib  # interactive with an explicit library
```

`--field` is repeatable and uses `name=value` syntax. `--type` defaults to
`article`. Existing citation keys are rejected unless `--allow-duplicate` is
passed. With no citation-key argument, `ref add` starts interactive mode and
first asks for the key. Leave it blank to generate the key from the collected
metadata and the library's configured key pattern. It then asks for the entry
type and only the required fields not already supplied with `--type` or
`--field`. The prompts follow the library's BibTeX or BibLaTeX required-field
rules. Supply the key (and `--field`) to add non-interactively; interactive
mode requires a terminal and errors under `--json` or headless stdin. Use
`--file` when an interactive run cannot auto-detect the library.

## show and edit

Read or transactionally patch one uniquely identified reference:

```bash
pynakes ref show Manual2026 refs.bib
pynakes ref show Manual2026 refs.bib --resolved --json
pynakes ref edit Manual2026 refs.bib \
  --field title="Revised title" --field year=2027 \
  --clear-field note --type book --dry-run --diff
pynakes ref edit Manual2026 refs.bib  # interactive when no change options are supplied
```

`ref edit` applies all requested field and type changes in one commit. It does
not rename the citation key: use `keys rename` for that coordinated operation,
which can also update linked TeX sources and Pinax materials. `ref show` and
`ref edit` return a conflict when the key is duplicated rather than guessing
which physical entry was intended. With no change options, `ref edit` starts
interactive mode automatically and presents the current type and required
fields as defaults; pressing Enter preserves each value. Interactive mode
requires a terminal: supplying no change options under `--json` or headless
stdin is an error rather than a prompt.

## import

Import a reference by DOI, repository/preprint identifier, or supported URL. The type is
auto-detected, so the same command handles all of these:

```bash
pynakes ref import 10.5555/example refs.bib --dry-run --diff
pynakes ref import https://doi.org/10.5555/example refs.bib
pynakes ref import arXiv:2301.00001 refs.bib
pynakes ref import https://arxiv.org/abs/2301.00001 refs.bib
pynakes ref import PMID:12345678 refs.bib
pynakes ref import https://www.nber.org/papers/w12345 refs.bib
pynakes ref import https://zenodo.org/records/1234567 refs.bib
```

Options:

```bash
pynakes ref import 10.5555/example refs.bib --key ManualKey2026
pynakes ref import 10.5555/example refs.bib --key-source provider
pynakes ref import 10.5555/example refs.bib --allow-duplicate
pynakes ref import arXiv:2301.00001 refs.bib --fetch
pynakes ref import 10.5555/example refs.bib --fetch --cache-dir .pynakes-cache
```

Each identifier is fetched through its matching provider. By default
`ref import` imports metadata only; `--fetch` also downloads configured Pinax
materials for the new entry: arXiv preprint PDF/source when an arXiv id is
present, and an open-access published PDF when the entry has a DOI and a
suitable `pinax-fetch-policy`. Existing matching provider ids and returned DOIs are
detected before importing. Provider entries follow the library's
BibTeX/BibLaTeX dialect.

See [Import providers](import-providers.md) for the complete supported and
planned identifier, repository, catalogue, and publisher URL inventory.

## files

Validate JabRef linked files stored in `file` fields.

```bash
pynakes asset check refs.bib
pynakes asset check refs.bib --json
pynakes asset check refs.bib --root ~/papers --json
pynakes asset check refs.bib --fix --backup
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

## format

Rewrite the whole-file layout deterministically without changing bibliographic
values or conventions:

```bash
pynakes format refs.bib --dry-run --diff
pynakes format refs.bib
pynakes format refs.bib --check
pynakes format refs.bib --preserve-field-order
```

By default, fields use **pynakes' preferred order**. This is not prescribed by
BibTeX, BibLaTeX, or JabRef; field order has no bibliographic meaning. It is a
readability convention chosen to make entries predictable and easy to scan:

1. Inheritance fields (`crossref`, `xdata`, and `xref`) come first so structural
   relationships are immediately visible.
2. Entry-type fields identifying the work and its publication context follow,
   such as author, title, journal or book title, year, volume, and pages.
3. Identifiers and access fields, then annotations such as notes and abstracts,
   generally come last.
4. Unknown and custom fields retain their relative source order after the known
   fields, avoiding an arbitrary alphabetical reshuffle.

Use `--preserve-field-order` when the library already has a preferred ordering.
The other layout controls configure indentation, `=` alignment, trailing
commas, and blank lines. Unlike ordinary surgical commands, `format` is an
explicit whole-file rewrite.

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
- lowercase entry types and field names
- leave journal titles unchanged unless a journal style is configured

Useful overrides:

```bash
pynakes normalize refs.bib --author-style conservative
pynakes normalize refs.bib --journal-style none
pynakes normalize refs.bib --journal-style full
pynakes normalize refs.bib --title-protection off
pynakes normalize refs.bib --doi-normalization off
pynakes normalize refs.bib --identifier-case off
pynakes normalize refs.bib --keys on
```

Journal source tables:

```bash
pynakes normalize refs.bib --journal-style abbreviated --journal-table journals.csv --ltwa-table ltwa.csv
```

`journals.csv` accepts `title`, `abbreviation`, and optional `issn` columns.
LTWA tables accept `Word` and `Abbreviation` columns.

To expand abbreviated titles back to full names, use `--journal-style full`.
To check journal-title conformance without modifying the file, set
`normalize-journal-style` metadata and run `pynakes lint refs.bib`.

Normalization preferences live in metadata. pynakes-specific settings (no
JabRef equivalent) go in `pynakes-meta`, under the `normalize-` key prefix.
pynakes writes them as one consolidated block, one `key: value` line per setting
(JabRef never reads this namespace, so there is no reason to repeat the prefix or
keep JabRef's `;` terminator):

```bibtex
@comment{pynakes-meta:
normalize-journal-style: none
normalize-protect-titles: false
normalize-identifier-case: false
normalize-keys: true
normalize-protected-terms: Proceedings,OpenAI
}
```

pynakes also reads the older one-comment-per-key and `key:value;` layouts, and
`normalize` rewrites them into this consolidated block on its next pass.

Where JabRef already has a setting, pynakes uses **that**: if the library has
JabRef `saveActions` enabled, `normalize` honors them — a `normalize_names`
formatter on a name field drives author normalization and a
`clean_up_doi` formatter on `doi` drives DOI cleanup; its absence
disables those steps. An explicit flag or a `pynakes-meta` key overrides.
JabRef's `short_doi` action is not run: it requires the shortdoi.org network
service, outside pynakes' offline normalization boundary, and is
reported as an unsupported formatter warning.

When `normalize` detects a JabRef aliased key whose pynakes-native equivalent
is absent, it **adopts** the value as a native key — `databaseType` becomes
`dialect`, `saveOrderConfig` becomes `sort-order`, `keypatterndefault` becomes
`key-pattern`, `keypattern_<type>` becomes `key-pattern-<type>`,
and `grouping` becomes `group-tree`.
Existing native keys are never overwritten.

To regenerate citation keys from the configured pattern, set
`normalize-keys: true` in `pynakes-meta` or pass `--keys on`. The
pattern is read from `key-pattern` (native) or
`keypatterndefault`/`keypattern_<type>` (JabRef fallback). The
bibliography entry is renamed in the `.bib` file and any Pinax
material files on disk are renamed consistently. TeX source rewrites
are handled separately.

```bibtex
@comment{jabref-meta: saveActions:enabled;
author[normalize_names]
doi[clean_up_doi]
;}
```

## tex scan

Analyze which entries are cited by `.tex` or `.aux` files.

```bash
pynakes tex scan refs.bib paper.tex paper.aux
pynakes tex scan refs.bib paper.tex --json
```

Tag cited entries:

```bash
pynakes tex scan refs.bib paper.tex --group Cited --dry-run --diff
pynakes tex scan refs.bib paper.tex --keyword cited
```

Export only cited entries:

```bash
pynakes tex scan refs.bib paper.tex --out cited-only.bib
```

## combine

Union several `.bib` files into one. Inputs are read-only; the combined file is
created (atomic write). Duplicate citation keys across inputs are kept and
reported by default; `--dedupe` collapses entries that share a key when their
content is identical and reports a **conflict** (exit `2`) when it differs,
rather than guessing.

(`corpus combine` unions whole files; merging two records of the *same* work is a
different operation — see [`dedupe merge`](#dedupe).)

```bash
pynakes corpus combine a.bib b.bib --out combined.bib
pynakes corpus combine a.bib b.bib --out combined.bib --dedupe --dry-run --diff
```

## split

Combine one or more inputs (merged in memory) and route their entries into
several output files, each selected by a predicate. This is `1.bib 2.bib → 3.bib
4.bib` in one step.

Each `--to FILE='predicate'` rule pairs an output file with a selector. The
predicate is a [`--where`](#fields) expression, or one of `*` (catch-all),
`used` / `unused` (against the citations found in `--tex`/`--aux` sources), or
`group "Name"`.

```bash
# Partition by group (first match wins; `*` collects the rest)
pynakes corpus split refs.bib extra.bib \
  --to ml.bib='group "Machine Learning"' \
  --to rest.bib='*'

# Partition into cited vs uncited against a manuscript
pynakes corpus split refs.bib --tex paper.tex \
  --to used.bib='used' \
  --to unused.bib='*' --dry-run --diff
```

Routing is **first match** by default — each entry lands in the first output
whose predicate matches, so the outputs are a partition. Pass `--copy` to send an
entry to *every* matching output instead (outputs may then overlap). Entries that
match no rule are dropped and reported under `unrouted`. `--dedupe` applies to the
in-memory merge, exactly as for `corpus combine`.

## convert

Convert between BibTeX and BibLaTeX field/type conventions (in place), or
export/import the interchange formats CSL-JSON, RIS, MODS, and EndNote tagged
text. The target is required: pynakes does not infer it from JabRef's
`databaseType` metadata.

```bash
# Dialect conversion (edits the .bib in place, with a reviewable diff):
pynakes convert refs.bib --to biblatex --dry-run --diff
pynakes convert refs.bib --to bibtex

# Export to an interchange format (stdout, or --out FILE):
pynakes convert refs.bib --to csl-json --out refs.json
pynakes convert refs.bib --to ris
pynakes convert refs.bib --to mods --out refs.xml
pynakes convert refs.bib --to endnote --out refs.enw

# Import an interchange format to BibTeX:
pynakes convert records.ris --from ris --out refs.bib
pynakes convert items.json --from csl-json
pynakes convert records.xml --from mods
pynakes convert records.enw --from endnote
```

Export/import map the common entry types and fields; unmapped fields are
dropped rather than guessed.

## capabilities

Print the machine-readable command/capability description.

```bash
pynakes capabilities
pynakes capabilities --json
```

## search

Search entries without modifying the library.

```bash
pynakes search learning                   # auto-detects one .bib file
pynakes search learning refs.bib
pynakes search 'title:"natural language" type:article' refs.bib --json
pynakes search widgets refs.bib --field title --where 'year = 2024' --json
```

Terms are ANDed. Quoted phrases stay together. `field:term` scopes a term to a
field; plain terms search the key, type, and stored fields.

## dedupe

Detect and conservatively merge duplicate works.

```bash
pynakes dedupe check refs.bib
pynakes dedupe merge refs.bib --dry-run --diff
```

`merge` exits with code `2` when field values disagree and cannot be safely
resolved. In a Pinax library, `merge` also moves the duplicate entries'
materials and provenance onto the surviving key when the survivor has no
material of the same kind; an existing survivor material is reported as a
conflict rather than overwritten.

## verify / enrich

Integrity and enrichment commands never use the network unless `--online` is
passed. Online provider responses are cached beside the `.bib` file by default,
or in `--cache-dir` when supplied.

```bash
pynakes verify --online --strict --json        # auto-detects one .bib file
pynakes verify refs.bib --online --strict --json
pynakes verify refs.bib --online --published --json
pynakes enrich refs.bib --online --dry-run --diff
pynakes enrich refs.bib --online --published --dry-run --diff
```

`verify --strict` exits with code `1` when warnings or errors are reported.
`enrich` only fills missing fields. The `--published` flag folds in the
preprint published-version workflow: on `verify` it reports (read-only) preprints
that now have a published version; on `enrich` it promotes them — preserving the
preprint identifier and adding the published DOI/journal metadata.

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
