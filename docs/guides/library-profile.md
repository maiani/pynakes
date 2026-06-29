# Library profile

`@comment{pynakes-meta: ...}` and `@comment{jabref-meta: ...}` can record a
library's maintenance preferences inside the `.bib` file. pynakes merges both
namespaces by key (case-insensitively); when both define the same key,
`pynakes-meta` wins. `normalize` uses these preferences as its defaults and
`lint` verifies the lintable subset without changing the file.

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

`lint-required-fields` values are additive to pynakes' built-in requirements,
which follow the library's `databaseType` (`bibtex` or `biblatex`). The
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

| Key | Used by |
| --- | --- |
| `keypatterndefault` | Citation-key generation and `lint` key-pattern conformance |
| `keypattern_<entrytype>` | Per-entry-type key generation and `lint` conformance; overrides the default |
| `saveActions` | `normalize` author, DOI, and field-formatter defaults |

JabRef's other metadata is preserved and classified, but it is not part of the
normalization/lint profile. See the [Usage guide](usage.md#metadata) for
metadata inspection and safe updates.

## Lint conformance

When configured, `lint` reports each of the following as a warning:

- A citation key that does not reproduce from `keypatterndefault` or its
  matching `keypattern_<entrytype>`.
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
@comment{jabref-meta: keypatterndefault:[auth][year];}
@comment{pynakes-meta:
normalize-journal-style: abbreviated
protected-terms: OpenAI,GPU
lint-required-fields-article: url
}
```

```bash
pynakes lint refs.bib --strict
```
