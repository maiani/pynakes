# Bibliography metadata reference

`@comment{pynakes-meta: ...}` and `@comment{jabref-meta: ...}` can record a
bibliography's maintenance settings — and, for `group-tree`, actual
bibliography content — inside the `.bib` file. `pynakes-meta` is pynakes' own
canonical schema; `jabref-meta` is a JabRef compatibility projection. pynakes
merges both namespaces by key (case-insensitively); when both define the same
key, `pynakes-meta` wins. `normalize` uses these settings as its defaults and
`lint` verifies the lintable subset without changing the file.

This page is the complete reference: every `pynakes-meta` key pynakes
understands, every `jabref-meta` key it recognizes (whether aliased to a native
key, group storage, or preserved pass-through), and the group-hierarchy schema.
For the *mechanics* of the two namespaces (routing, tracking, mirror-on-write,
round-trip fidelity), see the [JabRef compatibility guide](jabref-compatibility.md);
this page only lists *what* the keys are.

A fresh `pynakes init` library is **pynakes-native**: its settings live in
`pynakes-meta` and it carries no `jabref-meta` at all. Pass `init --jabref` (or
run `metadata adopt-jabref` later) to also emit the JabRef projection. On a
JabRef-tracked file, changing an aliased native key (see below) is **mirrored**
into its `jabref-meta` counterpart so JabRef never sees a stale value; if the
two ever disagree, `metadata list` reports the drift (pynakes uses the native
value).

Boolean values accept `true`/`false`, `on`/`off`, `yes`/`no`,
`enabled`/`disabled`, or `1`/`0`. List values are comma- or semicolon-separated.

pynakes writes all `pynakes-meta` keys as a single consolidated comment, one
`key: value` line per setting — JabRef never reads this namespace, so there is no
need to repeat the `@comment{pynakes-meta: …}` prefix per key or keep JabRef's
`;` terminator:

```bibtex
@comment{pynakes-meta:
normalize-journal-style: abbreviated
normalize-protected-terms: OpenAI,GPU
lint-required-fields-article: url
}
```

The older one-comment-per-key and `key:value;` layouts are still read;
`normalize` rewrites them into this form on its next pass.

## `pynakes-meta` keys

Every category below matches `pynakes.metadata.schema.MetadataCategory`; use it
to find the operation module that owns a key.

| Key | Category | Values | Used by | Jabref equivalent |
| --- | --- | --- | --- | --- |
| `dialect` | library | `bibtex` or `biblatex`; aliases JabRef's `databaseType` (read native-first) | engine, `lint`, importer | `databaseType` |
| `sort-order` | save | Sort criteria, same token grammar as `--sort-by` (e.g. `year:desc,author`); aliases JabRef's `saveOrderConfig` (read native-first) | `normalize` | `saveOrderConfig` |
| `key-pattern` | citation-key | Default citation-key pattern (e.g. `[auth][year][veryshorttitle]`); aliases JabRef's `keypatterndefault` (read native-first) | `keys`, `lint` | `keypatterndefault` |
| `key-pattern-<entrytype>` | citation-key | Per-entry-type key pattern; aliases JabRef's `keypattern_<entrytype>` (read native-first) | `keys`, `lint` | `keypattern_<entrytype>` |
| `normalize-protect-titles` | normalization | Boolean; default `true` for `normalize`; `lint` checks it when stored | `normalize`, `lint` | — |
| `normalize-title-fields` | normalization | List; default `title,booktitle,maintitle,subtitle` | `normalize`, `lint` | — |
| `normalize-protected-terms` | normalization | List of case-sensitive terms | `normalize`, `lint` | — |
| `normalize-drop-fields` | normalization | List of field names to remove from every entry; default none (off) | `normalize` | — |
| `normalize-author-style` | normalization | `jabref`, `conservative`, or `none` | `normalize` | — |
| `normalize-journal-style` | normalization | `abbreviated`, `full`, or `none` (default) | `normalize`, `lint` | — |
| `normalize-journal-source` | normalization | `jabref` (bundled JabRef lists, default) or `none` (rule-based only) | `normalize`, `lint` | — |
| `normalize-journal-table` | normalization | CSV/TSV path with exact journal mappings, layered on top of `normalize-journal-source` | `normalize`, `lint` | — |
| `normalize-ltwa-table` | normalization | CSV/TSV path with LTWA word mappings | `normalize`, `lint` | — |
| `normalize-dois` | normalization | Boolean | `normalize` | — |
| `normalize-identifier-case` | normalization | Boolean | `normalize` | — |
| `normalize-format-metadata` | normalization | Boolean | `normalize` | — |
| `format-indent` | formatting | Positive space count or `tab` (default: `2`) | `format` | — |
| `format-alignment` | formatting | `compact` or `equals` (default: `compact`) | `format` | — |
| `format-trailing-comma` | formatting | Boolean (default: `true`) | `format` | — |
| `format-blank-lines` | formatting | Boolean (default: `true`) | `format` | — |
| `format-field-order` | formatting | `preferred`, `preserve`, or `alphabetical` | `format` | — |
| `format-entry-order` | formatting | `preserve`, `key`, or `profile` | `format` | — |
| `format-block-order` | formatting | `canonical` or `preserve` (default: `canonical`) | `format` | — |
| `format-wrap-values` | formatting | `off`, `stable`, or `canonical` (default: `off`) | `format` | — |
| `format-line-width` | formatting | Integer at least 20 (default: `100`) | `format` wrapping | — |
| `format-entry-type-case` | formatting | `lower` (default) or `preserve` — keep each entry's type spelling, e.g. JabRef's `@Article` | `format`, `normalize`, `lint` | — |
| `lint-required-fields` | lint | Fields required on every entry | `lint` | — |
| `lint-required-fields-<entrytype>` | lint | Extra fields required on one entry type | `lint` | — |
| `lint-ignore` | lint | List of finding types and/or categories the `lint` command leaves out (counted as `suppressed`) | `lint` | — |
| `tex-sources` | usage | List of TeX files or directories, relative to the `.bib` file | `keys`, `tex scan` | — |
| `group-tree` | groups | Pipe-delimited group hierarchy; aliases JabRef's `grouping` (read native-first) — see [Grouping](#grouping) | `groups tree`/`add-group`/`remove-group`/`rename-group`/`move-group`/`update-group` | `grouping` / `groupsTree` / `groups:N...` |
| `scrub-fields` | scrub | List of extra field names/globs `scrub` removes, on top of its default private set | `scrub` | — |
| `scrub-keep-fields` | scrub | List of field names/globs `scrub` keeps despite that set (`*` keeps every field) | `scrub` | — |
| `scrub-comments` | scrub | Boolean; default `true` — whether `scrub` removes free comment blocks | `scrub` | — |
| `scrub-metadata` | scrub | Boolean; default `true` — whether `scrub` removes `jabref-meta`/`pynakes-meta` blocks | `scrub` | — |
| `pinax-files-dir` | pinax | Path to the Pinax materials directory, relative to the `.bib` file | `fetch`, `files`, engine | — |
| `pinax-fetch-policy` | pinax | Comma-separated list of: `preprint`, `published`, `source`, `supplement`, `bestpdf` (default `bestpdf`) | `fetch` | — |

`lint-required-fields` values are additive to pynakes' built-in requirements,
which follow the library's `dialect` (`bibtex` or `biblatex`, aliasing JabRef's
`databaseType`). The
BibLaTeX built-ins are sourced from the official BibLaTeX manual from CTAN,
section 2.1 entry types and aliases:
<https://mirrors.ctan.org/macros/latex/contrib/biblatex/doc/biblatex.pdf>. For
example, this makes `url` mandatory for every entry and `pages` mandatory for
articles:

```bibtex
@comment{pynakes-meta:
lint-required-fields: url
lint-required-fields-article: pages
}
```

## JabRef keys pynakes recognizes

pynakes classifies a `jabref-meta` key one of two ways: **aliased**, where a
pynakes-native key covers the same concept and is read first; or
**JabRef-only**, where pynakes has no native equivalent and either decodes the
value directly or preserves it as an opaque pass-through. An unrecognized
`jabref-meta` key is still parsed, preserved, and round-tripped byte-for-byte —
it is simply reported as `unknown` category by `metadata list`.

### Aliased (native-first, JabRef-second)

These JabRef-native keys are read only as **fallbacks** when the pynakes-native
key is absent (or, for `saveActions`, as a JabRef-only input with no native
equivalent). A pynakes-native library needs none of them.

| Key | Read as fallback for | Used by |
| --- | --- | --- |
| `keypatterndefault` | `key-pattern` | Citation-key generation and `lint` key-pattern conformance |
| `keypattern_<entrytype>` | `key-pattern-<entrytype>` | Per-entry-type key generation and `lint` conformance; overrides the default |
| `databaseType` | `dialect` | engine, `lint`, importer |
| `saveOrderConfig` | `sort-order` (only its `specified` form) | `normalize` |
| `grouping` / `groupsTree` / `groups:N ...` (flat) | `group-tree` | `groups tree`/`add-group`/etc — see [Grouping](#grouping) |
| `saveActions` | *(no native equivalent)* | `normalize` author, DOI, and field-formatter defaults |

### JabRef-only keys (category, no native equivalent)

pynakes recognizes and classifies these; it never invents pynakes-native
settings for them because they have no meaning outside JabRef, or the native
schema does not yet cover them.

| Key | Category | Notes |
| --- | --- | --- |
| `blgFilePath` | library | Path to the `.blg` BibTeX log JabRef associates with the file |
| `protectedFlag` | library | JabRef's "protect this library from external changes" flag |
| `versionDBStructure` | library | JabRef's internal database-structure version marker |
| `fileDirectory` / `fileDirectory-<library>` (prefix `fileDirectory`) | files | Per-library linked-file search path(s) |
| `fileDirectoryLatex` | files | Linked-file search path used when compiling with `\bibliography` |
| `groupsVersion` | groups | Version marker JabRef writes alongside `grouping` |
| `groups-search-syntax-version` | groups | Version marker for the search-group expression syntax |
| `bibdesk static groups` | groups | BibDesk-compatibility static-group marker some libraries carry |
| `selector_<field>` (prefix `selector_`) | selectors | JabRef's per-field autocomplete/selector value lists (e.g. `selector_publisher`) |

## Grouping

pynakes exposes a hierarchical group tree as the native `group-tree` key in
`pynakes-meta`, distinct from the flat per-entry `groups` field (`@Article{...,
groups = {Machine Learning; AI Papers}}`), which every entry already carries
independently of any tree. The tree adds structure *on top of* that field:
parent/child relationships, per-group color/expansion state, and (for JabRef
interop) the aggregation semantics JabRef calls "group context".

### Node schema

Each node in the tree (`pynakes.group_tree.GroupNode`) has:

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | str | Group display name; matched against entries' `groups` field values |
| `parent` | str | Parent node's `name`, or `""` for a root-level group |
| `context` | `0`\|`1`\|`2` | Membership aggregation — see below (default `2`) |
| `color` | str | Hex RGBA color (e.g. `8a8a8aff`), or `""` |
| `expanded` | bool | UI expansion state JabRef persists (default `true`) |
| `description` | str | Free-text note, or `""` |
| `group_type` | str | `StaticGroup` (default), `KeywordGroup`, `SearchGroup`, or `ExplicitGroup` |
| `field` | str | `KeywordGroup` only: the BibTeX field the expression matches against |
| `expression` | str | `KeywordGroup`/`SearchGroup`: the match/search expression |
| `case_sensitive` | bool | `KeywordGroup` only: whether `expression` matching is case-sensitive |
| `separator` | str | `KeywordGroup` only: the field's value separator (e.g. for multi-keyword fields) |
| `search_flags` | str | `SearchGroup` only: JabRef's search-flag string |
| `entries` | tuple[str, ...] | `ExplicitGroup` only: inline citation keys that are members, independent of any `groups` field |

`context` mirrors JabRef's own group-context flag:

- `0` — independent: membership is exactly the entries tagged with this group.
- `1` — refining: membership is the intersection with the parent group's
  membership.
- `2` — including (default): membership is the union with all subgroup
  memberships, so tagging an entry in a subgroup also counts it in the parent.

### Native format

The `group-tree` value is a 13-field pipe-delimited node list:

```
group-tree: name|parent|context|color|expanded|description|group_type|field|expression|case_sensitive|separator|search_flags|entries
```

(`entries` is itself comma-joined citation keys.) Nodes are separated by `; `
on a single line; a tree with more than one node is instead written across
continuation lines (one node per line) inside the consolidated `pynakes-meta`
comment, so a single-node edit stays a one-line diff:

```bibtex
@comment{pynakes-meta:
group-tree: Machine Learning
  Deep Learning|Machine Learning|2|ff0000ff
}
```

Trailing fields may be omitted entirely once every field after them is a
default value — a plain `StaticGroup` root node can be just its `name` (as
`Machine Learning` is above), and `Deep Learning` stops right after `color`
since its `expanded`/`description`/`group_type`/... all take their defaults.
Literal `\`, `|`, and `;` in a name, color, or description are
backslash-escaped (`\\`, `\|`, `\;`).

### JabRef interop

`library_group_tree()` reads, in order: the native `group-tree` key; then
JabRef's modern `grouping` block (or the legacy `groupsTree` spelling); then
JabRef's flat `groups:N name:context;` comments (one per group, depth encoded
as `N`). Editing the tree through any `pynakes groups` tree command (`tree`,
`add-group`, `remove-group`, `rename-group`, `move-group`, `update-group`)
always writes the canonical native `group-tree` key; on a JabRef-tracked file
it additionally projects the tree into `grouping` (plus a `groupsVersion`
marker) so JabRef keeps reading the same hierarchy. All four JabRef group
types round-trip through both the native format and `grouping` without loss of
their type-specific parameters.

**Limitation:** pynakes preserves and round-trips `KeywordGroup`/`SearchGroup`
definitions faithfully, but it does not *evaluate* their expression itself —
`groups list` and `list_entries_in_group_tree` only ever compute membership
from entries' flat `groups` field. A `KeywordGroup`/`SearchGroup` node's
dynamic membership is still something only JabRef computes when it opens the
file; pynakes commands report it as having no explicit members until JabRef
(or a future pynakes feature) evaluates the expression.

`groups add-entry`/`remove-entry` maintain flat per-entry membership, but they
are not fully independent of the tree: when a tree already exists, adding an
entry to a group that has no node registers one, so the tree stays a complete
index of the groups in use. `groups list` reads both views and reports their
union. See the [Usage guide](usage.md#groups) for the full CLI surface,
including the CRUD commands available on the tree.

## Lint conformance

When configured, `lint` reports each of the following as a warning:

- A citation key that does not reproduce from `key-pattern` or its matching
  `key-pattern-<entrytype>` (or JabRef's `keypatterndefault`/`keypattern_*` as a
  fallback).
- A known journal title that is not in the configured `normalize-journal-style`.
- An unknown journal title that cannot be resolved by the `normalize-journal-source`
  bundled table, `normalize-journal-table`, or `normalize-ltwa-table`.
- A missing field named by `lint-required-fields`.
- A title-like field whose case-sensitive terms or acronyms need brace
  protection while `normalize-protect-titles:true` is stored (or
  `normalize-protected-terms` is configured).

Unknown journal titles are reported as `unknown_journal` because pynakes cannot
determine their canonical form without a mapping. Add a
`normalize-journal-table` or `normalize-ltwa-table` when that distinction
matters, or check whether `normalize-journal-source` is set to `none` and the
journal simply isn't in a table you've configured.

The warnings are advisory in a normal run. `pynakes lint --strict` exits `1`
for these metadata-conformance warnings as for any other finding not
suppressed, allowing a repository to enforce its own stored settings in CI.

```bibtex
@comment{pynakes-meta:
key-pattern: [auth][year]
normalize-journal-style: abbreviated
normalize-protected-terms: LLM,GPU
lint-required-fields-article: url
}
```

```bash
pynakes lint refs.bib --strict
```
