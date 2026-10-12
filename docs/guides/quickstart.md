# Quick Start

Install the package (this step accesses the package index):

```sh
pip install pynakes
```

Run the following offline walkthrough in an empty directory:

```bash
pynakes init refs.bib
pynakes ref add refs.bib Newton1687 --type book --field author="Isaac Newton" --field title="Principia" --field year=1687 --field publisher="Royal Society"
pynakes inspect refs.bib --json
pynakes metadata list refs.bib --json
pynakes metadata set refs.bib dialect biblatex --dry-run --diff
pynakes lint refs.bib --json
pynakes normalize refs.bib --dry-run --diff
pynakes normalize refs.bib
pynakes normalize refs.bib --author-style conservative
pynakes groups add-group refs.bib Classics
pynakes groups add-entry refs.bib Newton1687 Classics --dry-run --diff
pynakes groups add-entry refs.bib Newton1687 Classics
pynakes groups list refs.bib --json
pynakes fields append refs.bib keywords history --key Newton1687 --dry-run --diff
pynakes fields protect-title refs.bib --dry-run --diff
pynakes asset check refs.bib --json
```

`inspect` reports entries, encoding, line endings, duplicates and metadata.
`lint` diagnoses without modifying the library; `--strict` exits 1 for any
unsuppressed finding. Modifying commands accept `--dry-run --diff` to preview
changes before writing. Backups are opt-in with `--backup`.

The default normalization pass protects title capitalization, normalizes
names, DOI fields and month macros. Journal titles are preserved unless the
stored profile or `--journal-style` chooses a transformation. To abbreviate
using your own local CSV tables:



Save these small example tables beside `refs.bib` before running the recipe:

```csv title="journals.csv"
title,abbreviation
Historical Studies,Hist. Stud.
```

```csv title="ltwa.csv"
Word,Abbreviation
Historical,Hist.
Studies,Stud.
```

```bash
pynakes normalize refs.bib --journal-style abbreviated --journal-table journals.csv --ltwa-table ltwa.csv
```

The CSV schemas accept an optional `issn` column in the journal table; the
[usage guide](usage.md#normalize) describes the table formats.

## Online acquisition

Importing contacts the selected provider, including under `--dry-run`:

```sh
pynakes ref import refs.bib 10.5555/example --dry-run --diff
pynakes ref import refs.bib arXiv:2301.00001 --fetch
```

These invented identifiers illustrate syntax. `--key` assigns a key;
`--key-source provider` uses the provider's key instead of the library's
configured key pattern. `--fetch` downloads configured Pinax materials.
See [Network and privacy](network-and-privacy.md) before sending unpublished
identifiers or free-text references.

## Manuscripts and materials

`tex add FILE PATH` records linked manuscript sources. With existing `.tex`
or `.aux` sources, `tex scan FILE SOURCES... --json` reports cited, unused and
missing keys. Key renames reuse linked sources and move associated Pinax
materials. `asset check` checks linked-file presence and Pinax manifest drift;
it does not recompute stored checksums. `asset repair` previews or applies
manifest reconciliation.

## Next steps

- [Usage and selectors](usage.md)
- [Generated command reference](command-reference.md)
- [Compatibility policy](public-api.md)
- [API reference](../api/index.md)
- [Installation and development checks](installation.md)
