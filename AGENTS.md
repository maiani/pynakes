# Working on pynakes

Guidance for coding agents (and humans) **developing** this repository.
`CLAUDE.md` is a symlink to this file.

> Looking for how to *use* the `pynakes` CLI from an LLM or automation
> workflow? That's a different audience — see
> [docs/guides/llm-integration.md](docs/guides/llm-integration.md).

## What this project is

`pynakes` is a headless, agent-safe BibTeX/BibLaTeX maintenance toolkit with a
custom parser built for round-trip fidelity. It interoperates losslessly with
JabRef and the BibTeX/BibLaTeX toolchain — that compatibility is a guarantee it
keeps, not its identity. See
[docs/guides/architecture.md](docs/guides/architecture.md) for the design,
[docs/vision.md](docs/vision.md) for the design philosophy, and
[DEVPLAN.md](DEVPLAN.md) for the phased plan.

## Layout

```
src/pynakes/
  model.py            BibEntry, BibFile, EntryStore (duplicate-key tolerant)
  bibtex_parser.py    parse_bib() — custom parser, preserves raw_content
  bibtex_writer.py    write_bib() — raw_content for unmodified, reconstruct for modified
  io.py               load_bib / save_bib / save_text / save_plain_text (atomic writes)
  editing.py          surgical raw-text field/key edits + entry-level helpers
  engine.py           Bibliography lifecycle: open, stage, preview/diff, commit, reload
  groups.py keys.py fields.py files.py lint.py
  authors.py journals.py normalize.py  format operations
  importer.py         resolve + import references by DOI / arXiv id (metadata only)
  integrity.py        verify / enrich / published (opt-in --online lookups)
  metadata.py         jabref-meta + pynakes-meta parsing, classification, safe updates
  usage.py            cited-entry detection/tagging and TeX citation-key rewrites
  capabilities.py     machine-readable capability description
  diff.py cli.py
tests/                pytest suite + tests/fixtures/*.bib
```

## Setup & checks

```bash
pip install -e ".[dev]"      # or ".[dev,docs]" for the docs site
pytest                       # full suite (fast; deterministic)
ruff check src tests         # lint
ruff format --check src tests
mkdocs build                 # docs site (needs the docs extra)
mkdocs serve                 # live-preview the docs at localhost:8000
```

The API reference is generated from docstrings by `mkdocstrings`
([docs/api/reference.md](docs/api/reference.md)); keep public-module docstrings
accurate rather than hand-maintaining a symbol list.

Run `pytest && ruff check src tests` before considering any change done.

## Invariants to preserve

These are the load-bearing guarantees; breaking them is a regression even if
tests pass:

1. **Round-trip fidelity.** An unmodified entry must write back byte-for-byte.
   The writer uses `raw_content` for untouched entries; do not normalize
   whitespace, reorder fields, or re-quote values on write.
2. **Edits go through `editing.py`.** All field/key mutations use the surgical
   helpers so only the changed line appears in a diff. Do not hand-edit
   `raw_content` or rebuild entries from scratch in operation modules.
3. **Operations mutate in place and return a count/report** (not a new
   `BibFile`). Keep `fields`/`raw_content` in sync via the `editing.py`
   helpers, which handle the "no raw_content → mark modified" fallback.
4. **The JSON envelope + exit-code contract is stable.** Modifying commands emit
   `status, action, file, dry_run, modified, modified_entries, warnings` (+
   command-specific keys, + `diff` when `--diff`). Errors → exit 1
   (`{"status":"error",...}`); conflicts → exit 2 with `options`. New commands
   go through the shared `_finish_mod` / `_safe` helpers in `cli.py`. The
   contract is documented in
   [docs/guides/llm-integration.md](docs/guides/llm-integration.md) and guarded
   by tests in `tests/test_cli.py`.
5. **Duplicate citation keys are tolerated, not an error** — the parser keeps
   them; `EntryStore` exposes them via `get_all()` / `duplicate_keys()`.

## Conventions

- Python ≥ 3.11, type hints throughout. Ruff line length 100 (E501 ignored).
- CLI: Typer sub-apps (`groups`, `keys`, `fields`, `files`, `dedupe`,
  `metadata`, `journals`) plus top-level commands (`add`, `normalize`,
  `convert`, …); one operation module per concern, kept small and unit-testable
  independent of the CLI.
- Try to limit file length preferably to ~400 lines, with a maximum limit of 600.
- Add tests and a `CHANGELOG.md` entry with each behavioral change.
- Use only generic, invented example data in code, tests, comments, docstrings,
  and `CHANGELOG.md` — never names, titles, or entries traceable to real people
  or real publications. When a bug report includes a real `.bib` entry,
  reproduce/fix with it locally but commit only a generic equivalent.

## Don't

- Don't add `bibtexparser` or another parsing dependency — the custom parser is
  deliberate (round-trip fidelity).
- Don't introduce nondeterminism (time, randomness, ordering) in core logic.
  Network access is confined to `add` (DOI/arXiv import) and the opt-in
  `--online` integrity lookups; everything else stays offline and deterministic.
- Don't let a command emit a traceback — route failures through `_safe`.
- Don't claim a feature is implemented when it is a stub (keep capabilities,
  README, and DEVPLAN honest).
