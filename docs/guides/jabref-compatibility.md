# JabRef compatibility

pynakes is a deterministic `.bib`/`.bib`latex maintenance engine first. It
interoperates losslessly with JabRef — parsing and preserving JabRef's own
metadata comments, understanding JabRef's value grammars, and keeping a
JabRef-tracked file readable in JabRef — but that compatibility is a guarantee
it keeps, not its identity. pynakes is not a JabRef clone or a JabRef-only
tool: it defines its own canonical metadata schema, and JabRef support is a
translation layer at the edge of that schema, not something domain logic
(normalization, linting, integrity checks) reaches through directly.

## The layering

Two structurally identical top-level comment namespaces can appear in a
`.bib` file:

- `@comment{jabref-meta: key:value;}` — JabRef's own settings.
- `@comment{pynakes-meta: key: value}` — pynakes' superset, for settings
  JabRef cannot represent, and increasingly for pynakes' own *native* spelling
  of a concept JabRef also has an encoding for.

`pynakes-meta` is the source of truth for pynakes' own canonical schema;
`jabref-meta` is a compatibility projection kept in sync so JabRef keeps
working with the file. Internally, this split is implemented as the
`pynakes.metadata` package:

| Module | Owns |
| --- | --- |
| `pynakes.metadata.core` | Namespace-neutral comment mechanics: parsing, formatting, surgical set/remove, consolidation. Knows nothing about which keys mean what. |
| `pynakes.metadata.schema` | pynakes' own key registry and the *pure* native reads for keys that also have a JabRef counterpart. Never imports JabRef's vocabulary. |
| `pynakes.metadata.jabref` | JabRef's key vocabulary and value grammars (`saveActions`, `saveOrderConfig`, `databaseType`), the JabRef group parsers/serializers (`parse_jabref_grouping`, `format_jabref_grouping`, `parse_jabref_groups_lines`), the owner/namespace arbitration, and the fallback-aware accessors domain code should call. |

Domain modules (`normalize.py`, `lint.py`, `integrity.py`, the engine) call the
fallback-aware accessors in `pynakes.metadata.jabref` (re-exported from
`pynakes.metadata`) — never JabRef's literal key names. This is what keeps
JabRef knowledge concentrated at one boundary instead of leaking into every
module that cares about, say, the library's dialect.

## Native keys with a JabRef alias

Concepts that used to be exposed only through JabRef's encoding now have a
pynakes-native spelling. All are read native-first, JabRef-second:

| Native key (`pynakes-meta`) | JabRef equivalent (`jabref-meta`) | Accessor |
| --- | --- | --- |
| `dialect` (`bibtex` or `biblatex`) | `databaseType` | `library_dialect(lib)` |
| `sort-order` (same token grammar as `--sort-by`, e.g. `year:desc,author`) | `saveOrderConfig` (only its `specified` form) | `library_sort_order(lib)` |
| `key-pattern` / `key-pattern-<entrytype>` (e.g. `[auth][year]`) | `keypatterndefault` / `keypattern_<entrytype>` | `library_key_pattern(lib, entry_type)` |

Each accessor returns the native value when set, else the JabRef value
(tolerating its trailing `;`), else a safe default: `library_dialect` →
`"bibtex"` (`@misc` is valid in both dialects); `library_sort_order` → the
JabRef criteria only when its type is `specified`, else `None`;
`library_key_pattern` → `None` (callers then use the built-in `AuthorYearTitle`
default). A lone `original`/`none` token in `sort-order` means "keep current
order".

### Mirror-on-write and drift

Setting an aliased key writes to `pynakes-meta` — all three are pynakes-owned
keys (see [Namespace routing](#namespace-routing-and-tracking)), so `metadata
set refs.bib dialect biblatex` always lands there. On a **JabRef-tracked** file,
the write is additionally *mirrored* into the matching `jabref-meta` key so
JabRef never sees a stale value; on a pynakes-native file (no `jabref-meta`)
nothing is mirrored, so the file gains no JabRef section it did not ask for.
`metadata set` reports the mirror in its summary and its JSON `mirrored` field.

If an aliased pair ends up disagreeing anyway — e.g. JabRef rewrote
`databaseType` after pynakes set `dialect` — pynakes still uses the native value
(reads are native-first) and `metadata list` surfaces the divergence as a drift
warning; re-setting the native key mirrors it back into `jabref-meta`.

JabRef's `saveActions` has no pynakes-native equivalent; it stays a JabRef-only
input that `normalize` consults directly (via `pynakes.metadata.jabref`) to
seed author-normalization and DOI-cleanup defaults when a library configures
it. Absorbing `saveActions` into native `normalize-*` keys (and a symmetric
"go-native" operation that strips `jabref-meta` when leaving JabRef entirely) is
planned but not yet implemented.

## Namespace routing and tracking

Every metadata key has an *owner*: JabRef-native keys (`databaseType`,
`saveActions`, `keypatterndefault`, …) are understood by JabRef; pynakes-owned
keys (`dialect`, `sort-order`, `normalize-*`, `files-dir`, …) and anything
unrecognized are understood only by pynakes. `default_namespace(key, lib)`
decides where a new key is written:

- A pynakes-owned (or unknown) key always goes to `pynakes-meta`.
- A JabRef-native key goes to `jabref-meta` only when the file is already
  *JabRef-tracked* — i.e. it already carries at least one `jabref-meta` block.
  Otherwise it goes to `pynakes-meta` too, so a greenfield pynakes-native
  library never gains a `jabref-meta` section it didn't ask for.

A fresh `pynakes init` library is pynakes-native by default: its `dialect` and
`key-pattern` are written to `pynakes-meta` and it carries no `jabref-meta`. Pass
`init --jabref` to also emit the JabRef projection at creation time, or run
`pynakes metadata adopt-jabref <file>` later to opt an existing pynakes-native
library into JabRef tracking: it relocates any JabRef-native keys stranded in
`pynakes-meta` and anchors a `databaseType` block, so the library works in
JabRef and future JabRef-native keys route to `jabref-meta` from then on.
Running it again once tracked is a no-op. See the
[LLM integration guide](llm-integration.md#inspect-or-update-jabref-metadata)
for the CLI contract.

## Round-trip fidelity and the JabRef grammars understood

An unmodified entry or metadata comment always writes back byte-for-byte —
this holds regardless of which namespace or accessor was used to read it.
`pynakes.metadata.jabref`'s key-to-category classification is pinned to a
specific JabRef release (JabRef v5.15's `MetaData.java` constants, per the
test suite), the same discipline pynakes' BibTeX/BibLaTeX parser applies to
its own [conformance baseline](architecture.md#parser-conformance-baseline):
pynakes should not claim broader JabRef-format compatibility than the pinned
version exercises. The value-grammar parsers it understands are `saveActions`,
`saveOrderConfig`, and `databaseType`; an unrecognized `jabref-meta` key is
still preserved and round-tripped, just not classified or decoded.
