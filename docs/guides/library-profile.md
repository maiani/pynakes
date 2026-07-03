# Library profile

`@comment{pynakes-meta: ...}` and `@comment{jabref-meta: ...}` can record a
library's maintenance preferences inside the `.bib` file. `pynakes-meta` is
pynakes' own canonical schema; `jabref-meta` is a JabRef compatibility
projection. pynakes merges both namespaces by key (case-insensitively); when
both define the same key, `pynakes-meta` wins. `normalize` uses these
preferences as its defaults and `lint` verifies the lintable subset without
changing the file.

A fresh `pynakes init` library is **pynakes-native**: its settings live in
`pynakes-meta` and it carries no `jabref-meta` at all. Pass `init --jabref` (or
run `metadata adopt-jabref` later) to also emit the JabRef projection. On a
JabRef-tracked file, changing an aliased native key (see below) is **mirrored**
into its `jabref-meta` counterpart so JabRef never sees a stale value; if the
two ever disagree, `metadata list` reports the drift (pynakes uses the native
value). See the [JabRef compatibility guide](jabref-compatibility.md) for the
full model.

Boolean values accept `true`/`false`, `on`/`off`, `yes`/`no`,
`enabled`/`disabled`, or `1`/`0`. List values are comma- or semicolon-separated.

pynakes writes all `pynakes-meta` keys as a single consolidated comment, one
`key: value` line per setting — JabRef never reads this namespace, so there is no
need to repeat the `@comment{pynakes-meta: …}` prefix per key or keep JabRef's
`;` terminator:

```bibtex
@comment{pynakes-meta:
normalize-journal-style: abbreviated
protected-terms: OpenAI,GPU
lint-required-fields-article: url
}
```

The older one-comment-per-key and `key:value;` layouts are still read;
`normalize` rewrites them into this form on its next pass.

## `pynakes-meta` keys

| Key | Values | Used by |
| --- | --- | --- |
| `dialect` | `bibtex` or `biblatex`; aliases JabRef's `databaseType` (read native-first) | engine, `lint`, importer |
| `sort-order` | Sort criteria, same token grammar as `--sort-by` (e.g. `year:desc,author`); aliases JabRef's `saveOrderConfig` (read native-first) | `normalize` |
| `key-pattern` | Default citation-key pattern (e.g. `[auth][year][veryshorttitle]`); aliases JabRef's `keypatterndefault` (read native-first) | `keys`, `lint` |
| `key-pattern-<entrytype>` | Per-entry-type key pattern; aliases JabRef's `keypattern_<entrytype>` (read native-first) | `keys`, `lint` |
| `normalize-protect-titles` | Boolean; default `true` for `normalize`; `lint` checks it when stored | `normalize`, `lint` |
| `normalize-title-fields` | List; default `title,booktitle,maintitle,subtitle` | `normalize`, `lint` |
| `protected-terms` | List of case-sensitive terms | `normalize`, `lint` |
| `normalize-author-style` | `jabref`, `conservative`, or `none` | `normalize` |
| `normalize-journal-style` | `abbreviated`, `full`, or `none` (default) | `normalize`, `lint` |
| `journal-table` | CSV/TSV path with exact journal mappings | `normalize`, `lint` |
| `ltwa-table` | CSV/TSV path with LTWA word mappings | `normalize`, `lint` |
| `normalize-dois` | Boolean | `normalize` |
| `normalize-identifier-case` | Boolean | `normalize` |
| `normalize-format-metadata` | Boolean | `normalize` |
| `lint-required-fields` | Fields required on every entry | `lint` |
| `lint-required-fields-<entrytype>` | Extra fields required on one entry type | `lint` |
| `tex-sources` | List of TeX files or directories, relative to the `.bib` file | `keys`, `tex scan` |
| `files-dir` | Path to the Pinax materials directory, relative to the `.bib` file | `fetch`, `files`, engine |
| `fetch-policy` | Comma-separated list of: `preprint`, `published`, `source`, `bestpdf` (default `bestpdf`) | `fetch` |

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

## JabRef keys consulted

These JabRef-native keys are read only as **fallbacks** when the pynakes-native
key is absent (or, for `saveActions`, as a JabRef-only input with no native
equivalent). A pynakes-native library needs none of them.

| Key | Read as fallback for | Used by |
| --- | --- | --- |
| `keypatterndefault` | `key-pattern` | Citation-key generation and `lint` key-pattern conformance |
| `keypattern_<entrytype>` | `key-pattern-<entrytype>` | Per-entry-type key generation and `lint` conformance; overrides the default |
| `databaseType` | `dialect` | engine, `lint`, importer |
| `saveOrderConfig` | `sort-order` | `normalize` (only its `specified` form) |
| `saveActions` | *(no native equivalent)* | `normalize` author, DOI, and field-formatter defaults |

JabRef's other metadata is preserved and classified, but it is not part of the
normalization/lint profile. See the [Usage guide](usage.md#metadata) for
metadata inspection and safe updates, and the
[JabRef compatibility guide](jabref-compatibility.md) for the native/JabRef
alias model and the mirror-on-write behavior.

## Lint conformance

When configured, `lint` reports each of the following as a warning:

- A citation key that does not reproduce from `key-pattern` or its matching
  `key-pattern-<entrytype>` (or JabRef's `keypatterndefault`/`keypattern_*` as a
  fallback).
- A known journal title that is not in the configured `normalize-journal-style`.
- An unknown journal title that cannot be resolved by the bundled sources,
  `journal-table`, or `ltwa-table`.
- A missing field named by `lint-required-fields`.
- A title-like field whose case-sensitive terms or acronyms need brace
  protection while `normalize-protect-titles:true` is stored (or
  `protected-terms` is configured).

Unknown journal titles are reported as `unknown_journal` because pynakes cannot
determine their canonical form without a mapping. Add a `journal-table` or
`ltwa-table` when that distinction matters.

The warnings are advisory in a normal run. `pynakes lint --strict` exits `1`
for structural errors and these profile-conformance warnings, allowing a
repository to enforce its own stored profile in CI. Other advisory warnings,
such as a missing DOI, remain non-blocking.

```bibtex
@comment{pynakes-meta:
key-pattern: [auth][year]
normalize-journal-style: abbreviated
protected-terms: LLM,GPU
lint-required-fields-article: url
}
```

```bash
pynakes lint refs.bib --strict
```
