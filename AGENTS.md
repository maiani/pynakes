# Working on pynakes

Guidance for coding agents (and humans) **developing** this repository.
`CLAUDE.md` is a symlink to this file.

> Looking for how to *use* the `pynakes` CLI from an LLM or automation
> workflow? That's a different audience — see
> [docs/guides/llm-integration.md](docs/guides/llm-integration.md).

## What this project is

`pynakes` is a headless, JabRef-compatible BibTeX/BibLaTeX maintenance toolkit
with a custom parser built for round-trip fidelity. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the design and [DEVPLAN.md](DEVPLAN.md)
for the phased plan.

## Layout

```
src/pynakes/
  model.py            BibEntry, BibLibrary, EntryCollection (duplicate-key tolerant)
  bibtex_parser.py    parse_bib() — custom parser, preserves raw_content
  bibtex_writer.py    write_bib() — raw_content for unmodified, reconstruct for modified
  io.py               load_bib / save_bib / save_text (atomic write + .bak + re-parse validate)
  editing.py          surgical raw-text field/key edits + entry-level helpers
  groups.py keys.py fields.py lint.py        core operations
  authors.py journals.py doi.py normalize.py format/metadata operations
  usage.py            cited-entry detection/tagging from .tex/.aux
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
zensical build               # docs site (needs the docs extra)
```

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
   `BibLibrary`). Keep `fields`/`raw_content` in sync via the `editing.py`
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
   them; `EntryCollection` exposes them via `get_all()` / `duplicate_keys()`.

## Conventions

- Python ≥ 3.11, type hints throughout. Ruff line length 100 (E501 ignored).
- CLI: Typer sub-apps (`groups`, `keys`, `fields`, `doi`); one operation module
  per concern, kept small and unit-testable independent of the CLI.
- Keep a single source of truth: name parsing lives in `authors.py`, DOI
  validation in `doi.py`, key uniquing in `keys.py`. Don't re-derive them.
- Add tests and a `CHANGELOG.md` entry with each behavioral change.

## Don't

- Don't add `bibtexparser` or another parsing dependency — the custom parser is
  deliberate (round-trip fidelity).
- Don't introduce nondeterminism (time, randomness, ordering) in core logic;
  `doi import` is the only sanctioned network call.
- Don't let a command emit a traceback — route failures through `_safe`.
- Don't claim a feature is implemented when it is a stub (keep capabilities,
  README, and DEVPLAN honest).
