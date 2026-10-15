# Usage Guide

This guide explains the engine's workflows and selection semantics. The
[generated command reference](command-reference.md) lists every live command,
argument, option, default, choice and stability marker. It is rebuilt from the
same Click tree as `capabilities --json`; it includes `metadata remove`,
`tex list/remove/clear`, `ref remove --keep-files`, `corpus batch --ops-file`
and `init --agent-guide`.

## Offline walkthrough

Run this block in an empty directory. It creates its own library, so no
private bibliography or network service is needed. The README, quickstart and
this guide's `bash` blocks are executed in CI. Installation, online and
terminal-only examples use `sh` and are labeled separately.

```bash
pynakes init refs.bib --pinax --agent-guide
pynakes ref add refs.bib Newton1687 --type book --field author="Isaac Newton" --field title="Principia" --field year=1687 --field publisher="Royal Society"
pynakes ref add refs.bib Euler1748 --type book --field author="Leonhard Euler" --field title="Introductio" --field year=1748 --field publisher="Bousquet"
pynakes fields set refs.bib note "review" --where 'year < 1800 and type = book'
pynakes search refs.bib "" --where 'key in [Newton1687, Euler1748]' --json
pynakes groups add-group refs.bib Classics
pynakes groups add-entry refs.bib Newton1687 Classics
pynakes groups list-entries refs.bib Classics --json
pynakes metadata set refs.bib normalize-journal-style abbreviated
pynakes metadata remove refs.bib normalize-journal-style
pynakes tex list refs.bib --json
pynakes tex add refs.bib paper.tex
pynakes tex remove refs.bib paper.tex
pynakes tex clear refs.bib
pynakes lint refs.bib --only duplicate_key --json
pynakes dedupe check refs.bib --json
pynakes asset check refs.bib --json
pynakes format refs.bib --dry-run --diff
pynakes normalize refs.bib --dry-run --diff
pynakes capabilities --json
```

`tex add` records a path; it does not create a manuscript. `tex scan` and
citation rewrites require actual TeX sources. Online operations and their
transmitted data are described in [Network and privacy](network-and-privacy.md).

## Command Conventions

Modifying commands support:

- `--dry-run`: show what would change without writing
- `--diff`: include a unified diff
- `--json`: emit structured output where supported

Exit codes:

- `0`: success
- `1`: error, such as parse, I/O, or validation failure
- `2`: conflict, such as duplicate DOI import without `--allow-duplicate`

A citation key, group name, or query that begins with `-` would be read as an
option. Put the options first and such values after `--`, which ends the
options: `pynakes groups add-entry refs.bib --create -- Newton1687 -draft`.

## Selecting entries (`--where`)

Every command that addresses a *set* of entries takes the same selector: the
`--where` grammar. A selector written for one command is valid for the others,
so there are no command-specific filter flags to learn.

Accepted by [`ref show`](#show-and-edit), [`fields`](#fields), [`search`](#search), [`format`](#format),
[`normalize`](#normalize), [`enrich`](#verify-enrich), `keys generate`,
`asset fetch`, `ref directive`, [`corpus combine`](#combine),
[`corpus split`](#split) (`--route` rules), and the `fields.*` operations of
`corpus batch`. A `--key` that names no entry is a `KeyNotFound` error, and a
selection that matches nothing writes nothing and warns `no_entries_selected`.
`pynakes capabilities` lists every command that takes the selector under
`predicate_grammar.used_by`.

Predicates combine with `and`, `or`, and `not`; `and` binds tighter than `or`,
and parentheses group explicitly, for example `not (group "Reviewed" or keywords contains draft)`.

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
`used` / `unused` test whether a citation key appears in the library's
[linked TeX sources](#linked-tex-sources), and `query "name"` runs one of the
library's [saved queries](#query), so `--where 'query "to-read" and unused'`
composes both.

To read a selection, use `ref show FILE --where EXPRESSION`: it returns a
summary per matching entry in file order, under the bounded-read options.
`search` is for text: `search FILE "" --where EXPRESSION` also selects by
predicate alone, but use `""`, not a filler query like `.`, which is a real
search term.

Quote values containing spaces or punctuation; bare tokens may not contain
whitespace, brackets, commas, or comparison characters. A comparison against a
field an entry does not have is false, except `!=` and `missing`, which are
true. `corpus split --route` additionally accepts the bucket predicate `*`
(catch-all), and resolves `used` / `unused` against its `--tex`/`--aux`
sources, which compose with everything else (`used and year >= 2020`).

### Selecting by citation key

When you already know the key, `--key` says so without the grammar. It is
comma-separated and repeatable, and every command that takes `--where` takes it.

`--key X` is exactly `--where 'key in [X]'`. Passing both *narrows* — they are
combined with `and`, so `--key Newton1687,Euler1748 --where 'type = article'`
acts on whichever of the two is an article.

On [`ref add`](#add) and [`ref import`](#import), which create an entry rather
than select one, `--key` names the key to assign. Commands that act on exactly
one existing reference — [`ref show` and `ref edit`](#show-and-edit),
— take the citation key as a positional argument. `ref remove` accepts
one or more keys.

`pynakes capabilities --json` reports this grammar under `predicate_grammar`.

## init

Create a new `.bib` library, seeded with a metadata profile. With no options it
writes a sensible default — the BibLaTeX dialect and pynakes' default
citation-key pattern (`[auth][year][veryshorttitle]`) — so the library works with
`keys generate` and `normalize` out of the box. It refuses to overwrite an
existing file unless `--force`; pass `--backup` to keep a `.bak` copy.

`--profile-from` copies the template's *conventions* — dialect, key patterns,
`saveActions`, and pynakes normalization/lint settings — but not its own content
(group tree, linked TeX sources). `--dialect` / `--key-pattern` override individual
settings on top of the default (or copied) profile.

## inspect

Inspect a `.bib` file.

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
| `content` | `normalize` | `warning` | journal style, malformed DOI, non-BibTeX page range, unprotected title case, key-pattern mismatch |
| `formatting` | `format` | `info` | mixed-case field names, and entry types unless `format-entry-type-case` is `preserve` |
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
`by_category` counts plus per-finding `category` and `fixer` keys.
`--strict` means *clean*: any finding left in the report fails it, whatever its
severity, as every other check fails on any finding. A finding the library
accepts is suppressed explicitly — `lint-ignore`, `--ignore`, or an `ignore`
directive on the entry — rather than tolerated by a severity rule. Human output ends
with the commands that would clear the fixable findings, for example
“Run `pynakes format` to resolve 3 of them.”

Some findings can never be fixed — a venue that assigns no DOIs, a journal with
no volumes — and would keep a commit hook failing or noisy. `--ignore NAME`
(repeatable) leaves a finding type (`missing_doi`) or a whole category
(`consistency`) out of the report and out of the `--strict` gate. To make that a
property of the library rather than of one invocation, store it:

```bibtex
@comment{pynakes-meta:
lint-ignore: missing_doi, formatting
}
```

`--ignore` adds to the stored list; it cannot re-enable what the library
ignores. To accept a finding on one entry only — this venue assigns no DOIs —
write an `ignore` [directive](#per-entry-directives) above it instead. Suppression is never silent: the summary's `suppressed` count, and a
closing line in human output, report how many findings were left out. An
unknown name is refused on the command line and reported as
`invalid_metadata_value` in the stored setting.

`pynakes normalize refs.bib` also repairs bare full month names such as
`month = june`, which BibTeX interprets as an undefined string reference. It
rewrites them to the standard macro (`month = jun`) and canonicalizes macro
casing (`month = Jan` → `month = jan`), while preserving literals such as
`month = {June}` and declared custom strings.

`lint` (along with `asset check`, `dedupe check`, and `verify`)
accepts multiple files, or auto-detects a single `.bib` in the current directory
when no file is given. Auto-detection ignores the `<jobname>Notes.bib` file
REVTeX generates, recognized by that name and the `@CONTROL{REVTEX4...}` entry it
opens with, and names it in the error when it was the only `.bib` found; pass one
explicitly if you really want to inspect it. A library you named `notes.bib` is
not skipped. These
checks support `--strict`, which exits `1` when any finding remains so it can
gate a build; for `lint`, suppressed findings do not count. See
[Metadata Reference](metadata-reference.md) for the complete schema and
[Git Workflows](git-workflows.md) for pre-commit and CI recipes.

## groups

Manage JabRef-style `groups` fields and the hierarchical group tree.

### Flat group membership

Use `groups add-entry` and `groups remove-entry` for tags on a reference.
Create the group first with `groups add-group`, or pass `--create` when adding
a member to a new group. `groups list` reports the membership.

### Group tree (hierarchical groups)

Group-tree metadata allows parent/child relationships among groups, stored
in the `pynakes-meta` `group-tree` key. Trees with multiple nodes are split
across continuation lines (one node per line) for readability. The tree is
bidirectionally compatible with JabRef's `grouping` block and flat `groups:`
metadata.

`groups list` reports every known group — the union of flat per-entry tags and
tree nodes — so a flat-only group is never hidden by the presence of a tree, and
a member-less tree node still appears. Each group lists its direct members only;
it does not expand tree descendants. Use `groups list-entries` for
descendant-inclusive membership, or `--exact` to restrict it to direct members.

A group name that matches neither a tree node nor a flat tag is a `KeyNotFound`
error rather than an empty result, so a typo is distinguishable from a group
that genuinely has no members.

The tree and per-entry membership are separate records, and the tree commands
edit only the first unless asked. `groups rename-group OLD NEW` renames the node
(and the parent reference of each child); entries filed under `OLD` keep that
membership, which then shows up as a group the tree does not declare. Pass
`--members` to carry the members along: every entry whose `groups` field names
exactly `OLD` is rewritten to `NEW` (`Optics Lab` is not a member of `Optics`),
an entry never ends up naming `NEW` twice, and only those `groups` lines change.
The JSON envelope lists the moved entries' keys as `members_renamed` (empty
without `--members`), so a preview can name them before the write.
`groups remove-group` never edits entries: a removed group's members keep it.

```bash
pynakes groups rename-group refs.bib Classics "Natural Philosophy" --members --dry-run --diff
```

`groups update-group` distinguishes an omitted option from an explicit empty
one: passing `--parent ""`, `--color ""`, or `--description ""` clears that
property, and `--expanded`/`--collapsed` both take effect. Invoked with no
options it reports no modification instead of claiming an update.

See [Metadata Reference](metadata-reference.md#grouping) for the tree's node
schema and native format.

## keys

Check, generate, rename, and repair citation keys.

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

`keys rename` updates the entry key in the `.bib` file, every `crossref`, `xref`,
`xdata`, `related`, and `entryset` value in the library that names it, and
matching keys inside recognized TeX citation commands in the supplied `.tex`
files/directories. It does not edit commented-out citations, and it exits with
conflict if the target key already exists. `keys generate` and `dedupe merge`
update those reference fields the same way; `keys repair` leaves them alone,
since a reference to a duplicated key is ambiguous. `lint` reports a reference
field naming a key the library lacks as `missing_reference_target`.

`keys usage` is a read-only lookup: given a key and one or more `.tex`
files or directories, it reports every `\cite`-family occurrence (file and line)
that cites that key, and takes neither a `.bib` file nor `tex-sources`
metadata. Use it to check a rename's blast radius over `.tex` that is not, and
may never be, registered with `tex add` — a frozen snapshot, a generated diff,
someone else's copy of the manuscript.

### Linked TeX sources

Record the `.tex` files that cite a library once, and the citation-key commands
reuse them — no need to pass paths every time. Use `tex add FILE PATH...`
or set `tex-sources` metadata.

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

A comment written **directly above an entry** — an `@comment{...}` block or a
`%` line with no blank line between it and the entry — belongs to that entry:
a note about it, or a directive another tool reads for the next entry, such as a
linter suppression. Every command that moves or drops entries keeps such a
comment with its entry: `format` and sorting write it directly above the entry
wherever the entry lands, `ref remove` and `dedupe merge` remove it with the
entry, and `corpus split`/`combine` send it to the output that receives the
entry. Separate a comment from the entry below it with a blank line to make it a
free, file-level comment instead.

In JSON/API output, each metadata block exposes both forms of the value:
`raw_value` is the parsed payload as stored in the comment, including JabRef's
trailing `;` when present; `value` is the normalized display/semantic form with
that terminator stripped. The exact source comment remains available as the
block's raw text in the Python model.

Set a metadata value with `metadata set FILE KEY VALUE`; remove a block
with `metadata remove FILE KEY`.

By default `metadata set` **routes the key automatically for maximum JabRef
compatibility**: keys JabRef understands (library/save/group/file/selector/
key-pattern, e.g. `databaseType`, `saveOrderConfig`, `saveActions`,
`groupstree`, `fileDirectory*`, `selector_*`, `keypatterndefault`,
`keypattern_<entrytype>`) go to `jabref-meta`; anything JabRef cannot represent
goes to `pynakes-meta`. Force a target with `--namespace jabref|pynakes`.

Unknown metadata blocks are preserved byte-for-byte. Writing an unrecognized key
into `jabref-meta` requires `--allow-unknown` (so JabRef's namespace is not
polluted); `pynakes-meta` accepts any key. `metadata set` exits with conflict
code `2` if duplicate blocks in the target namespace make an update ambiguous.

## fields

Bulk-edit one field operation across all references matching `--where`, while
preserving entry formatting. Use `ref edit` when patching one reference across
several fields.

`--where` is the shared [entry selector](#selecting-entries-where).

`fields protect-title` protects capitalization in title-family fields.

This protects acronyms, uppercase/digit tokens, mixed-case terms such as
`LaTeX`, and explicit terms.

## add

Use `ref add FILE KEY --field name=value...` to add a manual entry.

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

Read with `ref show FILE KEY`; patch with `ref edit FILE KEY --field name=value`.

`--key` turns `ref show` into a **triage view**: instead of every stored field
of one reference, it prints a compact summary of each requested reference — the
title, the first present of `author`/`editor`, the first present of
`year`/`date`, the most specific venue field (`journaltitle`, `journal`,
`booktitle`, …), and every identifier present (`doi`, `eprint`, `isbn`, `url`).
That is enough to judge a set of candidates in one call rather than one
invocation per key. Add `--abstract` to include each abstract; entries that
store none report `(none)` (JSON `null`), so "no abstract" is distinguishable
from "not requested". The keys may be comma-separated, the option repeated, or
both; repeats collapse and the requested order is preserved. Every unknown key
is reported together in one exit-1 `KeyNotFound` error.

`--where EXPRESSION` gives the same view for every entry a
[selector](#selecting-entries-where) matches, in file order:
`ref show refs.bib --where 'year < 1800 and abstract missing'`, or
`--where 'query "to-read"'` for a saved query. With `--key` as well, the two
narrow each other.

For comparing a set, `--select` returns exactly the named stored fields
(`--select title,abstract`) in place of the summary, and `--include` adds what
the library records outside the fields: `materials` (Pinax materials for the
key and `file` links with their status) and `provenance` (the Pinax manifest
record of each material and the directives above the entry). What the library
lacks is listed under `missing_fields` or `missing`, never hidden.
`--max-chars` cuts long values and lists each cut under `truncated`, and
`--limit` pages the selection, printing a `--cursor` that resumes it. A cursor is refused once the library changes, so
the pages of one read always come from one snapshot.

`ref edit` applies all requested field and type changes in one commit. It does
not rename the citation key: use `keys rename` for that coordinated operation,
which can also update linked TeX sources and Pinax materials. `ref show` and
`ref edit` return a conflict when the key is duplicated rather than guessing
which physical entry was intended. With no change options, `ref edit` starts
interactive mode automatically and presents the current type and required
fields as defaults; pressing Enter preserves each value. Interactive mode
requires a terminal: supplying no change options under `--json` or headless
stdin is an error rather than a prompt.

## Per-entry directives

A library's settings live in its `pynakes-meta` comment. A setting for **one
entry** lives in a comment directly above that entry — a *directive*:

```bibtex
% pynakes: ignore missing_doi -- the venue assigns no DOIs
@article{Newton1687,
```

A directive is `pynakes:`, a verb, its comma-separated arguments, and an
optional reason after ` -- `, written as a `%` line or as
`@comment{pynakes: ...}`. It must sit directly above the entry: a blank line
in between makes it a free comment that applies to nothing. Every command that
moves or drops entries carries it along (see
[metadata](#metadata)), and BibTeX, Biber, and JabRef leave it alone.

| Verb | Arguments | Effect |
| --- | --- | --- |
| `ignore` | finding types or categories, each optionally `NAME:FIELD` | `lint` leaves this entry's matching findings out of its report and its `--strict` gate |

An `ignore` that waives `citation_key_pattern_mismatch` (directly or through
its `content` category) also says the key is deliberately off-pattern, so
`normalize` with key generation and `keys generate --all` or `--key`/`--where`
keep it. Only naming that one key, `keys generate FILE KEY`, still renames it.

`ref directive` writes and removes directives on the entries named by `--key`
or selected by `--where`, changing only the directive lines.

`--where` is how a library adopts `lint --strict`: waive the findings it has
accepted, by selection, and every new finding still fails the gate.

Arguments the entry's directives already carry are not repeated; giving a new
`--reason` for them rewrites the reason. `--remove` takes arguments out of the
entry's directives of that verb and deletes a directive left with none. A
directive pynakes cannot act on is refused by `ref directive` and reported by
`lint` as `invalid_entry_directive`; an `ignore` that no longer matches any
finding is reported as `unused_entry_directive`, so a waiver does not outlive
its reason unnoticed. Waived findings count toward the lint summary's
`suppressed`.

## find

Find the real records matching a reference written out in prose.

```
3 candidate(s) from crossref:
 *1.   57.6  10.1002/j.1538-7305.1948.tb00917.x
        A Mathematical Theory of Communication
        C. E. Shannon · Bell System Technical Journal · 1948
  2.   41.5  10.1002/j.1538-7305.1949.tb00928.x
        Communication Theory of Secrecy Systems
        C. E. Shannon · Bell System Technical Journal · 1949
  Import one with: pynakes ref import <doi>
```

Every other way into a library starts from an identifier, which is a claim that
can be checked: `ref import` either resolves it or does not. A reference written
out as text carries no such claim, and this is how to ask whether one describes
anything that exists. Read-only; import a candidate you accept by its DOI.

`ref find` requires `--online`. `ref import`, `asset fetch`, and
`ref add` / `ref import --fetch` authorize network access explicitly without it.
`--limit` caps the candidates (5 by default), and `--cache-file` reuses answers
across runs.

A `*` marks a candidate that plainly matches — either its title occurs in the
text you gave, or the index scored it far above the rest. When none does, the
command says so:

```
  No candidate plainly matches the text; review before importing any.
```

That is the signal worth having when a reference arrives already written out
rather than copied from a publisher page, which is the shape a conversational
assistant produces — and produces just as fluently for a paper that was never
written. Nothing in the text distinguishes the two; whether an index has ever
heard of it does.

The command stops at reporting, deliberately. An empty result means the index
matched nothing, which is **evidence, not proof**: a genuinely obscure, very
recent, or non-Crossref-deposited work also matches nothing. Turning that into
a verdict would be a quality judgment the data does not support.

## import

Import a reference by DOI, repository/preprint identifier, ISBN, or supported
URL. The type is auto-detected.

Publisher article URLs and book ISBNs work the same way, so a page URL copied
from a browser can be imported without first digging out its DOI.

SciPost article ids and numeric JSTOR stable ids become their publisher's DOI;
ScienceDirect URLs carry a Publisher Item Identifier, which is resolved to a DOI
before the metadata lookup. ISBNs resolve through Open Library and produce a
`@book` entry; check digits are validated locally, so a mistyped ISBN fails
before any network request.

Discipline-specific databases publish their own BibTeX, which carries detail the
DOI record omits — eprints and report numbers from INSPIRE, venue and editor
details from the ACL Anthology.

An INSPIRE texkey is the citation key high-energy physics already uses, so
`--key-source provider` adopts it verbatim. DBLP's own key is not usable as a
citation key, so a key is generated instead.

Some platforms publish article URLs with no identifier in them at all — AIP's
`pubs.aip.org` pages and legacy ISSN-based IOPscience URLs among them. Those
fail with advice to import the DOI printed on the article page rather than
guessing at a match.

### Imports follow the library's style

An imported entry is written the way the library says its entries look, so a
clean file stays clean. The `normalize-*` settings the library declares (journal
style, author style, title protection, and the rest) and its JabRef saveActions
are applied to the new entry, and so is its `format-*` layout, such as
`format-alignment: equals`. Nothing else in the file changes. A library that
declares none of these settings gets the entry as the provider described it;
run `normalize` or `format` with `--key` to bring it in line by hand.

### Importing several at once

Give several identifiers, or pipe a list, and they resolve in one call and
commit in one write. Use `-` as the identifier to read standard input.

Piped input is one identifier per line; blank lines and `#` comments are
skipped, so a list pasted out of a chat or a notes file needs no cleaning up
first.

Each identifier is reported separately, and **one that does not resolve does not
stop the others**:

```
Imported 6 of 8 reference(s) (1 already present, 1 unresolved).
  10.5555/invented: Server returned HTTP 404 for 10.5555/invented
  10.5555/known: already present as Smith2020; skipped.
```

That is the intended shape rather than a lenient one. A reference list produced
by a conversational assistant routinely contains a plausible identifier that no
provider has ever heard of, and telling you *which* one is the useful answer —
stopping at the first would just hide the other seven. The write stays atomic:
everything that resolved is staged in memory and committed once, so the file
never holds half a list. With `--json`, `results` carries one record per
identifier (`imported`, `skipped`, or `failed`) alongside the usual envelope.

An identifier already in the library is `skipped`, not a conflict — exit 2 is
for a question only you can answer, and here the rest of the list still has to
resolve. Re-run that one with `--allow-duplicate` if a second copy was wanted.

A single identifier keeps its existing behavior exactly: a failure is the
command's failure, and `--key` applies to the one entry.

All import options are listed in the [generated reference](command-reference.md#ref-import).

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

`asset check` only reports, so it can gate a commit. `asset repair` reconciles
the Pinax manifest with the material files that exist: it drops records for
keys the library no longer has and for files that are gone, and records files
the manifest does not know. It changes only the manifest — no material file and
no byte of the library.
With `--reclassify` it also moves each published PDF that `asset check` reports
as `misclassified` — a preprint, on recorded evidence — to the preprint path,
with its manifest record; a file whose preprint path is taken is reported as a
conflict and left alone.

`asset check` keeps two questions apart under `coverage`: `linked_files`
counts `file`-field links (the top-level `checked`/`ok`/`missing`), and
`materials` counts the entries that have a PDF in Pinax and names those that
do not.

`asset check` takes one or more libraries as positional arguments (handy for CI
gating). `asset fetch` downloads materials for one entry or for a whole library;
its first positional is the library, followed by an optional citation key.
Omit the key to fetch the whole library.

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
`missing`, `wrong_type`, and `unresolved` statuses. This command is read-only.
In Pinax mode, `asset repair` reconciles manifest drift. Neither command
repairs arbitrary JabRef attachment paths or recomputes checksums.

## format

Rewrite the whole-file layout deterministically without changing bibliographic
values or conventions.

`format` runs the lint checks first and refuses source shapes that its semantic
model cannot rewrite losslessly, currently repeated assignments of one field in
an entry. Other lint findings remain available through `pynakes lint` but do not
block layout formatting of an incomplete draft.

`format` clears every `formatting`-category lint finding: it lowercases entry types
and field names, both of which BibTeX treats case-insensitively, so recasing them
changes no bibliographic value. An ordinary surgical edit leaves the spelling of
entries it was not asked to change untouched.

A library that another tool saves in its own type spelling — JabRef writes
`@Article` and `@InProceedings` — would churn: `format` lowercases the types and
the next JabRef save restores them. Set `format-entry-type-case: preserve` (or
pass `--entry-type-case preserve`) to keep each entry's own spelling. The
setting governs type case for every command: `format` keeps the spelling,
`normalize` leaves types alone while still lowercasing field names, and `lint`
reports a type only when `format` would recase it. `init --jabref` sets it.

```bibtex
@comment{pynakes-meta:
format-entry-type-case: preserve
}
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

`--field-order` accepts `preferred`, `preserve`, or `alphabetical`.
`--entry-order` accepts `preserve`, `key`, `profile` (the library's `sort-order` /
`saveOrderConfig`), or an explicit sort spec in the same grammar, such as
`--entry-order author,year:desc` (`citationkey`/`key` and `entrytype`/`type`
name the key and the type; crossref parents always follow their children).
`format` owns entry order: `normalize --sort-by` and `normalize`'s sorting by
`sort-order` are deprecated and removed in 0.9.0. `--block-order preserve` keeps comments, strings, preambles,
and raw source in place as barriers while sorting entry runs (a comment attached
directly above an entry is not a barrier; it moves with its entry); the default
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
entries you asked for.

A selection owns the layout *inside* each entry it matches, not the layout of
the file, so the whole-file options `--entry-order`, `--block-order`, and
`--blank-lines`/`--no-blank-lines` cannot be combined with `--where`.

## normalize

Run the daily maintenance pass.

Default behavior:

- protect capitalization in title-like fields
- normalize author/editor lists in JabRef style
- normalize DOI values
- rewrite page ranges to `start--end`
- lowercase entry types and field names (entry types stay as they are under
  `format-entry-type-case: preserve`; see [format](#format))
- leave journal titles unchanged unless a journal style is configured

A step the library has turned off reports `off` rather than `0`, because the
two are different claims: `journals=0` means "checked every journal title and
changed none", while `journals=off` means the step never ran. The human summary
names the flag that turns each one on, and `--json` carries the full reason
under `operations.skipped`.

To run some steps on some entries, name the steps with `--only` and the
entries with `--key` or `--where`.

The steps are `metadata`, `drop-fields`, `titles`, `authors`, `dois`, `pages`,
`journals`, `save-actions`, `months`, `identifier-case`, `sort` (deprecated:
use `format --entry-order`), and `keys`. A
step left out reports why under `operations.skipped`. A selection never re-sorts
the file or rearranges its metadata, since those act on the file as a whole, and
`--sort-by` or `--metadata-formatting` given with a selection is refused. So is a
flag that configures a step `--only` leaves out, such as
`--only journals --author-style biblatex`.

See the generated reference for the full set of overrides.

Page ranges are rewritten to BibTeX's `start--end`: a Unicode en-dash
(`1052–1055`, which is what Crossref hands out) or a single hyphen becomes
`--`, and `p.`/`pp.` prefixes are stripped. A value that is not a simple range
— an article number, or a list like `7,41,73--97` — is left alone. This runs by
default, unlike journal-style conversion, because `--` is the format's own
convention for the same value rather than an editorial preference. Turn it off
with `--pages off` or `normalize-pages: false`. `lint` reports the same values
as `nonstandard_page_range`, so a range an import or a paste introduced is
visible before it reaches a build.

Provider markup in titles is converted to LaTeX. Publishers deposit titles
with MathML, JATS or HTML structure (`<mml:math>…`, `<i>…</i>`), and DOI
content negotiation passes it on verbatim. Imports convert it on the way in;
`normalize` converts any already in the library, whatever the title-protection
setting, and `lint` reports what is left as `title_markup`. A chemical formula
becomes `Fe$_3$O$_4$`, a symbol becomes inline math (`$p$`), and italics become
`\textit{…}`.

Journal source tables require `--journal-style abbreviated` (or a stored
journal style) to request abbreviation.

`journals.csv` accepts `title`, `abbreviation`, and optional `issn` columns.
LTWA tables accept `Word` and `Abbreviation` columns.

To expand abbreviated titles back to full names, use `--journal-style full`.
To check journal-title conformance without modifying the file, set
`normalize-journal-style` metadata and run `pynakes lint refs.bib`.

To always strip a field — `abstract` is the common case — across every entry,
use `--drop-field` (repeatable) or persist it as `normalize-drop-fields`
metadata.

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
normalize-pages: true
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
`normalize-keys: true` in `pynakes-meta` or pass `--key-generation on`. The
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

Analyze which entries are cited by `.tex` or `.aux` files: the given ones,
else the library's [linked TeX sources](#linked-tex-sources). The report
lists the used and unused entries and the cited keys the library lacks.

To act on the cited entries, select them with `--where used` in the command
that does the work:

```bash
pynakes tex add refs.bib paper.tex                             # link the manuscript once
pynakes corpus combine refs.bib --where used --out cited.bib   # a working subset
pynakes scrub refs.bib --where used --out public.bib           # a public copy
pynakes fields append refs.bib keywords cited --where used     # tag them
```

`tex scan --out`, `--group`, and `--keyword` still export and tag until 0.9.0,
with a `deprecated` warning.

With `--json`, the report's `usages` object locates every citation: each cited
key maps to its occurrences, one `{path, line, column, text, macro}` per
`\cite`-family macro that names it. Keys **missing** from the library are in
there too — a cited key with no entry is the one most worth locating — while an
entry cited nowhere simply has no occurrences. This is the whole-library
counterpart to [`keys usage`](#keys), which locates one key at a time
without needing a `.bib` file at all.

## scrub

Write a public copy of a library with its private content removed — the step
before a `.bib` goes to arXiv, into a submission bundle, or into a public
repository. The input is read-only; `--out` names the copy (give it the input
path to scrub in place).

Three kinds of content are removed by default:

| Kind | What goes |
| --- | --- |
| Private entry fields | `owner`, `timestamp`, `creationdate`, `modificationdate`, `__markedentry`, `annote`, `annotation`, `comment`, `review`, `priority`, `ranking`, `readstatus`, `relevance`, `printed`, `qualityassured`, `file`, `pdf`, `local-url`, `bdsk-file-*`, `groups` |
| Metadata blocks | every `jabref-meta` and `pynakes-meta` comment: group tree, save configuration, selectors, `pinax-files-dir` |
| Free comments | `@comment{...}` blocks and `%` lines that are not metadata |

Bibliographic content is never removed unasked: `abstract`, `keywords`, and
`note` stay unless you name them.

Use `--drop-field` and `--keep-field` to adjust what counts as private.

A library can record its own policy instead of repeating flags — see
[`scrub-fields`, `scrub-keep-fields`, `scrub-comments`, and
`scrub-metadata`](metadata-reference.md#pynakes-meta-keys).

`--check` reports instead of writing and exits `1` when anything private is
found, which is what a submission or CI check needs.

Everything not removed stays byte-for-byte identical, so the copy is reviewable
as a diff of its source. To release only the entries a document actually cites,
select them: `scrub refs.bib --where used --out public.bib`. Selection happens
before scrubbing, so `used` still reads the `tex-sources` the copy loses.

## combine

Union several `.bib` files into one. Inputs are read-only; the combined file is
created (atomic write). Duplicate citation keys across inputs are kept and
reported by default; `--dedupe` collapses entries that share a key when their
content is identical and reports a **conflict** (exit `2`) when it differs,
rather than guessing.

(`corpus combine` unions whole files; merging two records of the *same* work is a
different operation — see [`dedupe merge`](#dedupe).)

`--where` keeps only the entries a [selector](#selecting-entries-where) matches,
so a focused subset of several libraries is one command.

## split

Combine one or more inputs (merged in memory) and route their entries into
several output files, each selected by a predicate. This is `1.bib 2.bib → 3.bib
4.bib` in one step.

Each `--route FILE='predicate'` rule pairs an output file with a selector. The
predicate is any [`--where`](#selecting-entries-where) expression — including
`and`/`or`/`not` — plus the bucket predicates `*` (catch-all) and `used` /
`unused` (against the citations found in `--tex`/`--aux` sources).

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

Export/import map the common entry types and fields; unmapped fields are
dropped rather than guessed.

CSV is export-only: it cannot carry repeated names, braced capitalization,
string macros, linked files, comments, or metadata, so `--from csv` is refused
as an invalid choice. An import that cannot be read — malformed JSON or XML,
CSL-JSON that is not an item or array of items, MODS that declares XML
entities, or a value with unbalanced braces — is a JSON error envelope (exit 1)
and writes no output file.

## capabilities

Print the machine-readable command/capability description.

## search

Search entries without modifying the library.

Terms are ANDed. Quoted phrases stay together. `field:term` scopes a term to a
field; plain terms search the key, type, and stored fields.

`--fuzzy` also accepts near-misses — misspellings and inflections — by
normalized similarity, so a half-remembered title can still find its entry.

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

Two more options shape a search independently. `--in title,abstract` looks for
the terms only in those stored fields (the citation key and entry type stay
searchable); `--select title,year` returns only those fields for each match,
listing absent ones under `missing_fields`. `--in title --select abstract`
matches titles and returns abstracts. `--in-field` is deprecated and will be
removed in 0.9.0: it did both at once, so replace `--in-field title` with
`--in title --select title`.

`--abstract` prints a one-line abstract excerpt under each hit, so a
result list can be triaged without a second command; a result with no stored
abstract says `(no abstract)`. The excerpt is for reading — `--json` always
carries the full abstract, including under `--in` or `--select`, and
reporting the abstract never widens what the query matches.

For the promising keys, `ref show --key k1,k2,…` prints the summarized
entries; a single `ref show <key>` prints one in full.

`--limit` caps a page of results and `--cursor` resumes the same search at the
next page; `--max-chars` cuts long field values in `--json` output.

## query

Save a selection the library keeps reusing, and run it later against the
entries as they are then:

```bash
pynakes query set refs.bib to-read 'abstract exists and not group "Read"'
pynakes ref show refs.bib --where 'query "to-read"' --select title,abstract --limit 10
pynakes fields append refs.bib keywords queued --where 'query "to-read" and year < 1900'
pynakes query list refs.bib
pynakes query remove refs.bib to-read
```

A saved query is one `query-<name>` line in `pynakes-meta` holding a
[`--where`](#selecting-entries-where) expression; the library stores the query,
never its result. `query "name"` is a predicate of the `--where` grammar, so
every command that selects entries runs it, and a saved expression may itself
refer to other saved queries. `ref show --where` returns the matches in file
order with the same options as `ref show --key`.

## analyze

Describe what a library holds and how complete its records are:

```bash
pynakes analyze refs.bib
pynakes analyze refs.bib --section identifiers --section lint --json
```

The report counts entries and duplicate keys, entry types, years, the most
frequent authors and venues (`--top`, default 10), identifier and field
coverage, groups, `lint` findings, and linked-file and Pinax materials. It is
offline and descriptive: each section composes an existing report, so the
`lint` section matches `lint` and every count can be traced to the entries
behind it.

## dedupe

Detect and conservatively merge duplicate works.

`check` reports each cluster with the identity that matched it and the keys in
it. `merge` folds every cluster into its first entry; `--key` narrows it to the
clusters containing the named keys, which is the shape the decision usually has
— you look at one pair, decide they are the same work, and resolve that one
without accepting every other merge the file invites. The selector is the shared
[`--key`](#selecting-by-citation-key), so it is comma-separated and repeatable.
A key belonging to no cluster is an error rather than a silent no-op.

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

`--key` and `--where` limit `enrich` to the selected entries, so a lookup for a
few references never queries a provider for the rest of the library.

`verify --strict` exits with code `1` when warnings or errors are reported.

An `--online` pass looks up entries concurrently — `-j/--concurrency N`
(default 8) controls how many provider lookups run at once. Output is
identical at any concurrency: reports, applied field updates, and the
progress bar all follow the library's own entry order, not fetch completion
order.

### Caching provider responses

Nothing is cached to disk unless you ask for it. Every command that can go
online — `verify`, `enrich`, `ref compare`, `ref find`, `ref import`,
`ref add --fetch`, `asset fetch` —
accepts `--cache-file PATH`, and only that flag creates a cache. Without it, provider responses are not persisted. Modifying online commands
can still write bibliography updates and downloaded materials.

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
- repair of arbitrary JabRef linked-file paths (Pinax manifest repair is implemented)

## Next Steps

- [Examples](../examples/index.md)
- [Architecture](architecture.md)
- [API Reference](../api/index.md)
