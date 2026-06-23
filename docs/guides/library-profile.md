# Library profile

`@comment{pynakes-meta: ...}` and `@comment{jabref-meta: ...}` can record a
library's maintenance preferences inside the `.bib` file. pynakes merges both
namespaces by key (case-insensitively); when both define the same key,
`pynakes-meta` wins. `normalize` uses these preferences as its defaults and
`lint` verifies the lintable subset without changing the file.

Use canonical keys for new files. The legacy `pynakes-*` spellings below remain
supported for compatibility, but the canonical key takes precedence if both
are present. Boolean values accept `true`/`false`, `on`/`off`, `yes`/`no`,
`enabled`/`disabled`, or `1`/`0`. List values are comma- or semicolon-separated.

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
| `tex-sources` | List of TeX files or directories, relative to the `.bib` file | `keys`, `used` |

The aliases `pynakes-normalize-<name>` for every `normalize-<name>` key,
`pynakes-protected-terms`, `pynakes-journal-table`, `pynakes-ltwa-table`, and
`required-fields` / `required-fields-<entrytype>` are accepted. They are
deprecated aliases, not additional settings.

`lint-required-fields` values are additive to pynakes' built-in BibTeX/BibLaTeX
requirements. For example, this makes `url` mandatory for every entry and
`pages` mandatory for articles:

```bibtex
@comment{pynakes-meta: lint-required-fields:url;}
@comment{pynakes-meta: lint-required-fields-article:pages;}
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
- A missing field named by `lint-required-fields`.
- A title-like field whose case-sensitive terms or acronyms need brace
  protection while `normalize-protect-titles:true` is stored (or
  `protected-terms` is configured).

Unknown journal titles are not reported as style violations because pynakes
cannot determine their canonical form without a mapping. Add a `journal-table`
when that distinction matters.

The warnings are advisory in a normal run. `pynakes lint --strict` exits `1`
for structural errors and these profile-conformance warnings, allowing a
repository to enforce its own stored profile in CI. Other advisory warnings,
such as a missing DOI, remain non-blocking.

```bibtex
@comment{jabref-meta: keypatterndefault:[auth][year];}
@comment{pynakes-meta: normalize-journal-style:abbreviated;}
@comment{pynakes-meta: protected-terms:OpenAI,DNA;}
@comment{pynakes-meta: lint-required-fields-article:url;}
```

```bash
pynakes lint refs.bib --strict
```
