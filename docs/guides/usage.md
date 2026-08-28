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

## Selecting entries (`--where`)

Every command that addresses a *set* of entries takes the same selector: the
`--where` grammar. A selector written for one command is valid for the others,
so there are no command-specific filter flags to learn.

Accepted by [`fields`](#fields) (`--where`), [`search`](#search) (`--where`),
[`format`](#format) (`--where`), [`corpus combine`](#combine) (`--where`),
[`corpus split`](#split) (`--to` rules), and the `fields.*` operations of
`corpus batch`.

Predicates combine with `and`, `or`, and `not`; `and` binds tighter than `or`,
and parentheses group explicitly:

```bash
pynakes fields set refs.bib note "review" \
  --where 'year >= 2024 and doi missing and type in [article, inproceedings]'

pynakes search widgets refs.bib --where 'not (group "Reviewed" or keywords contains draft)'
```

Field operators:

| Operator | Meaning |
| --- | --- |
| `contains` | case-insensitive substring |
| `=`, `==` | case-insensitive equality |
| `!=` | case-insensitive inequality (true when the field is absent) |
| `>`, `>=`, `<`, `<=` | ordered comparison (numeric, date, or text — see below) |
| `in [a, b]`, `not in [a, b]` | membership in a list of values |
| `matches` | case-insensitive regular expression |
| `~` | fuzzy match (normalized similarity ≥ 0.8) |
| `exists` | the field is present |
| `missing` | the field is absent or empty |

Ordered comparisons compare numerically when both sides are numbers, as partial
dates (`YYYY[-MM[-DD]]`) when both sides are dates, and as text otherwise — so
`year >= 2025` orders by value rather than by string, and `date >= 2020-06` is a
date range. Partial dates compare by their known components: an entry with only
`year = {2020}` does not satisfy `date >= 2020-06`.

Besides stored fields, four names are special: `key` (citation key), `type`
(entry type), `year` (falls back to the year inside `date`), and `date` (falls
back to a date composed from `year`/`month`/`day`). `group "Name"` tests JabRef
group membership; the stored field itself is reachable as `groups`.

Pass an empty query to select by predicate alone:

```bash
pynakes search "" refs.bib --where 'key in [Newton1687, Euler1748]'
pynakes search "" refs.bib --where 'date >= 1900-06 and date <= 1910'
pynakes search "" refs.bib --where 'abstract missing'          # "entries missing field X"
pynakes search "" refs.bib --where 'title ~ "quantum computing"'
pynakes search "" refs.bib --where 'journal matches "^Phys\. Rev\."'
```

Use `""`, not a filler query like `.`: a filler is a real search term, so
`search . --where 'abstract missing'` quietly returns only those matching
entries whose text happens to contain a period. An empty query searches nothing
and lets the predicate decide, which is the whole set. The query argument stays
required, so a lone path can never be mistaken for a query.

Quote values containing spaces or punctuation; bare tokens may not contain
whitespace, brackets, commas, or comparison characters. A comparison against a
field an entry does not have is false, except `!=` and `missing`, which are
true. `corpus split --to` additionally accepts the bucket predicates `*`
(catch-all), and `used` / `unused` against `--tex`/`--aux` sources, which
compose with everything else (`used and year >= 2020`).

`pynakes capabilities --json` reports this grammar under `predicate_grammar`.

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
pynakes inspect refs.bib --resolved --json    # + crossref/xdata-inherited fields
pynakes inspect refs.bib --display --json     # + human-readable title/author view
```

JSON output includes file encoding, line ending, entries, duplicate keys, and
structured JabRef library metadata under `jabref_metadata`. Use `lint` for
validation findings.

`--display` adds a `display` object per entry: title-family fields
(`title`/`booktitle`/`maintitle`/`subtitle`) with LaTeX markup and braces
cleaned to plain text, and `author`/`editor` split into individual, cleaned
names (`["Watson, James", "Crick and Sons"]` rather than a raw
`Watson, James and {Crick and Sons}` string). It is a presentation projection
for a UI to render — never a value to edit or write back; combine with
`--resolved` to clean the inherited view instead of the entry's own fields.

## lint

Validate entries.

```bash
pynakes lint                         # auto-detects one .bib file
pynakes lint refs.bib
pynakes lint refs.bib --json
pynakes lint refs.bib chapters/*.bib --strict   # multi-file CI gate
pynakes lint refs.bib --category correctness    # only structural problems
```

Checks include duplicate citation keys, dialect-aware missing required fields by
entry type, malformed DOI fields, missing article DOIs, malformed group
fields, and mixed-case entry types or field names. BibLaTeX required-field
validation follows the official BibLaTeX manual from CTAN, section 2.1 entry
types and aliases:
<https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf>. It
also verifies the lintable parts of a stored library profile: citation-key
patterns, journal style, profile-required fields, and title brace protection.

The library's stored metadata comments are validated too, so metadata drift no
longer passes silently: a `pynakes-meta` key outside the pynakes schema is
flagged, a key's value is checked against the grammar pynakes defines for it
(a typo'd `pinax-fetch-policy` or `normalize-journal-style` token, a dialect
that is not `bibtex`/`biblatex`, or a bad formatting choice), and repeated
blocks for one key within a namespace — which make the effective metadata
ambiguous — are reported. The JabRef flat `groups:` format is exempt from the
duplicate check, since it repeats the `groups` key once per group line by
design.

`lint` only diagnoses; it never rewrites a library. Every finding carries a
**category** naming what kind of problem it is and which command resolves it,
and a **severity** ranking urgency:

| Category | Fixed by | Severity | Examples |
| --- | --- | --- | --- |
| `correctness` | you decide | `error` | duplicate keys, missing required fields, undefined string references |
| `content` | `normalize` | `warning` | journal style, malformed DOI, unprotected title case, key-pattern mismatch |
| `layout` | `format` | `info` | mixed-case entry types and field names |
| `consistency` | nothing — an observation | `info` | missing article DOI, a field most comparable peers define |
| `profile` | you decide | `warning` | deviations from the library's stored lint profile |

The cross-entry consistency check compares an entry only with peers of the same
entry type **and** identity class — `preprint`, `published`, `book`, `code`, or
`unknown` — so a preprint is never judged against published articles that carry
issue and publisher metadata by construction. It also ignores publisher
decoration such as `issn`, `publisher`, `month`, `url`, and `abstract`, whose
absence reflects how rich the metadata source was rather than a gap in the
reference.

Layout and consistency findings are `info` so that they cannot bury a structural
`error`; `--category` filters the report, and `--json` adds `info` and
`by_category` counts plus per-finding `category` and `fixer` keys. Only errors
and profile deviations gate `--strict` — including metadata drift (unknown
pynakes keys, invalid metadata values, duplicate blocks). Human output ends
with the commands that would clear the fixable findings, for example
`Run `pynakes format` to resolve 3 of them.`

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
[Metadata Reference](metadata-reference.md) for the complete schema and
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

`groups list` reports every known group — the union of flat per-entry tags and
tree nodes — so a flat-only group is never hidden by the presence of a tree, and
a member-less tree node still appears. Each group lists its direct members only;
it does not expand tree descendants. Use `groups list-entries` for
descendant-inclusive membership, or `--exact` to restrict it to direct members:

```bash
pynakes groups list-entries refs.bib "Machine Learning"           # includes descendants
pynakes groups list-entries refs.bib "Machine Learning" --exact   # direct members only
```

A group name that matches neither a tree node nor a flat tag is a `KeyNotFound`
error rather than an empty result, so a typo is distinguishable from a group
that genuinely has no members.

`groups update-group` distinguishes an omitted option from an explicit empty
one: passing `--parent ""`, `--color ""`, or `--description ""` clears that
property, and `--expanded`/`--collapsed` both take effect. Invoked with no
options it reports no modification instead of claiming an update.

See [Metadata Reference](metadata-reference.md#grouping) for the tree's node
schema and native format.

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

pynakes keys usage OldKey2020 --path paper.tex --path chapters/ --json
```

Generated keys default to `AuthorYearTitle`. JabRef metadata is honored when
present:

```bibtex
@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}
@comment{jabref-meta: keypattern_article:[auth][year][veryshorttitle];}
```

Unsupported key-pattern markers or modifiers fail explicitly instead of
silently generating an incorrect key.

Markers cover authors (`auth`, `authors`, `authorIni`, `authIniN`, `authorsN`,
`authorLast`, and `authN`), the equivalent editor family (`edtr`, `editors`,
`editorIni`, `edtrIniN`, `editorsN`, `editorLast` — these read only the
`editor` field, never falling back to `author`), `year`/`shortyear`,
title markers (`title`, `shorttitle`, `veryshorttitle`, `camel`/`camelN`,
and `fulltitle`, which keeps every word and its original spacing instead of
filtering to significant words), page markers derived from the `pages` field
(`firstpage`/`lastpage` — the lowest/highest of every number found, not just
the ends of one range — and `pageprefix`, e.g. `L` from `L7`), `entrytype`,
and any literal field name. Modifiers chain after `:` — `lower`, `upper`,
`capitalize`, `titlecase`, `sentencecase`, `abbr`, `truncateN`, `regex("pattern","replacement")`,
and a `(default)` fallback inserted when the preceding marker resolved empty —
plus any registered field formatter (`latex_cleanup`, `remove_braces`, ...)
usable directly as a modifier. A handful of rarer combinator markers
(`authN_M`, `authorsAlpha`, `editorLastForeIni`, `keywordN`, and similar) are
not yet supported and raise the same explicit error.

Pass a citation key to apply that preferred pattern to just one entry, or
`--all` to regenerate the whole library. Like `keys rename`, generated renames
also rewrite matching TeX citations in linked `tex-sources` metadata when it is
configured.

`keys rename` updates the entry key in the `.bib` file and matching keys inside
recognized TeX citation commands in the supplied `.tex` files/directories. It
does not edit commented-out citations, and it exits with conflict if the target
key already exists.

`keys usage` is a read-only lookup: given a key and one or more `--path`
files/directories, it reports every `\cite`-family occurrence (file and line)
that cites that key, and takes neither a `.bib` file nor `tex-sources`
metadata. Use it to check a rename's blast radius over `.tex` that is not, and
may never be, registered with `tex add` — a frozen snapshot, a generated diff,
someone else's copy of the manuscript.

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

`--where` is the shared [entry selector](#selecting-entries-where):

```bash
pynakes fields append refs.bib keywords "transformers" \
  --where 'title contains "neural network"'

pynakes fields clear refs.bib doi --where 'type = book'
pynakes fields clear refs.bib note --where 'doi exists'
pynakes fields clear refs.bib abstract --where 'year < 2000 or type in [book, thesis]'
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
pynakes ref show --keys Manual2026,Newton1687 refs.bib --abstract
pynakes ref edit Manual2026 refs.bib \
  --field title="Revised title" --field year=2027 \
  --clear-field note --type book --dry-run --diff
pynakes ref edit Manual2026 refs.bib  # interactive when no change options are supplied
```

`--keys` turns `ref show` into a **triage view**: instead of every stored field
of one reference, it prints a compact summary of each requested reference — the
title, the first present of `author`/`editor`, the first present of
`year`/`date`, the most specific venue field (`journaltitle`, `journal`,
`booktitle`, …), and every identifier present (`doi`, `eprint`, `isbn`, `url`).
That is enough to judge a set of candidates in one call rather than one
invocation per key. Add `--abstract` to include each abstract; entries that
store none report `(none)` (JSON `null`), so "no abstract" is distinguishable
from "not requested". The keys may be comma-separated, the option repeated, or
both; repeats collapse and the requested order is preserved. Every unknown key
is reported together in one exit-1 `KeyNotFound` error. With `--keys` the
positional argument is the library, so `ref show --keys a,b refs.bib` reads
naturally.

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

Import a reference by DOI, repository/preprint identifier, ISBN, or supported
URL. The type is auto-detected, so the same command handles all of these:

```bash
pynakes ref import 10.5555/example refs.bib --dry-run --diff
pynakes ref import https://doi.org/10.5555/example refs.bib
pynakes ref import arXiv:2301.00001 refs.bib
pynakes ref import https://arxiv.org/abs/2301.00001 refs.bib
pynakes ref import PMID:12345678 refs.bib
pynakes ref import https://www.nber.org/papers/w12345 refs.bib
pynakes ref import https://zenodo.org/records/1234567 refs.bib
```

Publisher article URLs and book ISBNs work the same way, so a page URL copied
from a browser can be imported without first digging out its DOI:

```bash
pynakes ref import https://link.springer.com/article/10.5555/example refs.bib
pynakes ref import https://onlinelibrary.wiley.com/doi/10.5555/example refs.bib
pynakes ref import https://journals.plos.org/plosone/article?id=10.5555/example refs.bib
pynakes ref import https://iopscience.iop.org/article/10.5555/example refs.bib
pynakes ref import https://scipost.org/SciPostPhys.10.1.001 refs.bib
pynakes ref import https://www.jstor.org/stable/1171664 refs.bib
pynakes ref import https://www.sciencedirect.com/science/article/pii/S0123456789012345 refs.bib
pynakes ref import 978-0-00-000000-2 refs.bib
pynakes ref import ISBN:0123456789 refs.bib
```

SciPost article ids and numeric JSTOR stable ids become their publisher's DOI;
ScienceDirect URLs carry a Publisher Item Identifier, which is resolved to a DOI
before the metadata lookup. ISBNs resolve through Open Library and produce a
`@book` entry; check digits are validated locally, so a mistyped ISBN fails
before any network request.

Discipline-specific databases publish their own BibTeX, which carries detail the
DOI record omits — eprints and report numbers from INSPIRE, venue and editor
details from the ACL Anthology:

```bash
pynakes ref import INSPIRE:Author:2024abc refs.bib
pynakes ref import https://inspirehep.net/literature/451647 refs.bib
pynakes ref import DBLP:journals/cacm/Codd70 refs.bib
pynakes ref import https://aclanthology.org/2023.acl-long.1 refs.bib
```

An INSPIRE texkey is the citation key high-energy physics already uses, so
`--key-source provider` adopts it verbatim. DBLP's own key is not usable as a
citation key, so a key is generated instead.

Some platforms publish article URLs with no identifier in them at all — AIP's
`pubs.aip.org` pages and legacy ISSN-based IOPscience URLs among them. Those
fail with advice to import the DOI printed on the article page rather than
guessing at a match.

Options:

```bash
pynakes ref import 10.5555/example refs.bib --key ManualKey2026
pynakes ref import 10.5555/example refs.bib --key-source provider
pynakes ref import 10.5555/example refs.bib --allow-duplicate
pynakes ref import arXiv:2301.00001 refs.bib --fetch
pynakes ref import 10.5555/example refs.bib --fetch --cache-file .pynakes-cache
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

`asset check` takes one or more libraries as positional arguments (handy for CI
gating). `asset fetch` downloads materials for one entry or for a whole library;
its first positional is a citation key, so the whole-library form names the
library with `--file`:

```bash
pynakes asset fetch alvarez2019 refs.bib   # one entry
pynakes asset fetch --file refs.bib        # every entry with missing materials
```

See the [Pinax guide](pinax.md#fetch-the-first-slice) for what gets downloaded
and how `pinax-fetch-policy` governs it.

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
pynakes format refs.bib --field-order preserve
pynakes format refs.bib --wrap-values stable --line-width 100
```

`format` runs the lint checks first and refuses source shapes that its semantic
model cannot rewrite losslessly, currently repeated assignments of one field in
an entry. Other lint findings remain available through `pynakes lint` but do not
block layout formatting of an incomplete draft.

`format` clears every `layout`-category lint finding: it lowercases entry types
and field names, both of which BibTeX treats case-insensitively, so recasing them
changes no bibliographic value. Only `format` does this — an ordinary surgical
edit leaves the spelling of entries it was not asked to change untouched.

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

`--field-order` accepts `preferred`, `preserve`, or `alphabetical`.
`--entry-order` accepts `preserve`, `key`, or `profile` (the library's `sort-order` /
`saveOrderConfig`). `--block-order preserve` keeps comments, strings, preambles,
and raw source in place as barriers while sorting entry runs; the default
`canonical` policy retains pynakes' metadata/JabRef placement convention.

Safe value wrapping is opt-in. `--wrap-values stable` preserves authored legal
breaks and repairs overflow; `canonical` reflows safe values from scratch.
Names break only between top-level names. Verbatim identifiers and paths, dates,
bare macros/numbers, and `#` concatenations are never wrapped, and value
delimiters are preserved. The other layout controls configure indentation,
`=` alignment, trailing commas, and blank lines. Unlike ordinary surgical
commands, `format` is an explicit whole-file rewrite.

`--where` narrows the rewrite to the entries a
[selector](#selecting-entries-where) matches; every other byte of the file —
including unmatched entries — stays identical, so the diff covers exactly the
entries you asked for:

```bash
pynakes format refs.bib --where 'year >= 2024' --dry-run --diff
pynakes format refs.bib --where 'key in [Newton1687]' --alignment equals
```

A selection owns the layout *inside* each entry it matches, not the layout of
the file, so the whole-file options `--entry-order`, `--block-order`, and
`--blank-lines`/`--no-blank-lines` cannot be combined with `--where`.

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

To always strip a field — `abstract` is the common case — across every entry,
use `--drop-field` (repeatable) or persist it as `normalize-drop-fields`
metadata:

```bash
pynakes normalize refs.bib --drop-field abstract
```

Off by default, like journal-style conversion: dropping a field is opinionated
and not reversible, so it only runs for fields named explicitly.

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
normalize-drop-fields: abstract
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

With `--json`, the report's `usages` object locates every citation: each cited
key maps to its occurrences, one `{path, line, column, text, macro}` per
`\cite`-family macro that names it. Keys **missing** from the library are in
there too — a cited key with no entry is the one most worth locating — while an
entry cited nowhere simply has no occurrences. This is the whole-library
counterpart to [`keys usage`](#keys), which locates one key at a time
without needing a `.bib` file at all.

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

`--where` keeps only the entries a [selector](#selecting-entries-where) matches,
so a focused subset of several libraries is one command:

```bash
pynakes corpus combine a.bib b.bib --out recent.bib --where 'year >= 2020 and doi exists'
```

## split

Combine one or more inputs (merged in memory) and route their entries into
several output files, each selected by a predicate. This is `1.bib 2.bib → 3.bib
4.bib` in one step.

Each `--to FILE='predicate'` rule pairs an output file with a selector. The
predicate is any [`--where`](#selecting-entries-where) expression — including
`and`/`or`/`not` — plus the bucket predicates `*` (catch-all) and `used` /
`unused` (against the citations found in `--tex`/`--aux` sources).

```bash
# Partition by group (first match wins; `*` collects the rest)
pynakes corpus split refs.bib extra.bib \
  --to ml.bib='group "Machine Learning"' \
  --to rest.bib='*'

# Partition into cited vs uncited against a manuscript
pynakes corpus split refs.bib --tex paper.tex \
  --to used.bib='used' \
  --to unused.bib='*' --dry-run --diff

# Bucket predicates compose with field predicates
pynakes corpus split refs.bib --tex paper.tex \
  --to recent-cited.bib='used and year >= 2020' \
  --to rest.bib='*'
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
pynakes search "" refs.bib --where 'doi missing'    # predicate only, no text match
```

Terms are ANDed. Quoted phrases stay together. `field:term` scopes a term to a
field; plain terms search the key, type, and stored fields.

`--fuzzy` also accepts near-misses — misspellings and inflections — by
normalized similarity, so a half-remembered title still finds its entry:

```bash
pynakes search 'nueral widgts' refs.bib --fuzzy
pynakes search widgets refs.bib --where 'year >= 2020 and abstract missing' --json
```

Results are ranked by match strength (key > title > author > other fields >
groups/abstract, then by score) with ties in file order; `--no-rank` restores
plain file order. With `--json` each result explains itself: `matched_fields`
names the fields that matched and `matches` lists one entry per hit with its
`field`, `term`, `kind` (`exact` or `fuzzy`), `score`, and the matching
`excerpt`. The result's `score` is the weakest term score, and `where_parsed`
echoes the parsed selector.

Which entries are searched is a separate question from what matches: `--where`
answers it with the shared [selector grammar](#selecting-entries-where),
covering date ranges and missing-field queries without search-specific flags.

`--show-abstract` prints a one-line abstract excerpt under each hit, so a
result list can be triaged without a second command; a result with no stored
abstract says `(no abstract)`. The excerpt is for reading — `--json` always
carries the full abstract, including when `--field` restricts the fields
searched, and reporting the abstract never widens what the query matches:

```bash
pynakes search 'quantum computing' refs.bib --fuzzy --show-abstract --limit 10
```

For the promising keys, `ref show --keys k1,k2,…` prints the summarized
entries; a single `ref show <key>` prints one in full.

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
passed, and never write a cache to disk unless `--cache-file` is passed. Within a
single run, provider responses are reused from memory — the same DOI is looked up
once no matter how many entries carry it — and discarded when the command exits.
Pass `--cache-file PATH` to keep them for later runs; see
[Caching provider responses](#caching-provider-responses).

```bash
pynakes verify --online --strict --json        # auto-detects one .bib file
pynakes verify refs.bib --online --strict --json
pynakes verify refs.bib --online --published --json
pynakes enrich refs.bib --online --dry-run --diff
pynakes enrich refs.bib --online --published --dry-run --diff
```

`verify --strict` exits with code `1` when warnings or errors are reported.

An `--online` pass looks up entries concurrently — `-j/--concurrency N`
(default 8) controls how many provider lookups run at once. Output is
identical at any concurrency: reports, applied field updates, and the
progress bar all follow the library's own entry order, not fetch completion
order.

### Caching provider responses

Nothing is cached to disk unless you ask for it. Every command that can go
online — `verify`, `enrich`, `ref compare`, `ref import --fetch`, `asset fetch` —
accepts `--cache-file PATH`, and only that flag creates a cache. Without it, an
online run leaves the directory holding your `.bib` exactly as it found it.

```bash
pynakes verify refs.bib --online --cache-file .pynakes-cache
```

The cache is one file: newline-delimited JSON, one record per provider response,
identifiers in plain text so it stays readable and greppable. A single
`.gitignore` line covers it and `rm` removes it — a missing cache only costs
refetches, so there is nothing to manage and no command to learn.

No record ever expires. Provider metadata does change, which is why `verify
--online` exists at all, so treat a cache as a snapshot you chose to keep: delete
it when you want a genuinely fresh comparison.

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
