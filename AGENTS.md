# Working on pynakes

Guidance for coding agents (and humans) **developing** this repository.
`CLAUDE.md` is a symlink to this file.

> Looking for how to *use* the `pynakes` CLI from an LLM or automation
> workflow? That's a different audience — see
> [docs/guides/llm-integration.md](docs/guides/llm-integration.md).

## What this project is

`pynakes` is a headless BibTeX/BibLaTeX maintenance toolkit with a
custom parser built for round-trip fidelity. At the file layer it interoperates
losslessly with JabRef and the BibTeX/BibLaTeX toolchain — that compatibility is
a guarantee it keeps, not its identity. Its optional **Pinax** mode manages a
`.bib` together with the materials it points to, addressed by citation key.
See [docs/guides/architecture.md](docs/guides/architecture.md) for the design,
[docs/vision.md](docs/vision.md) for the design philosophy,
[DEVPLAN.md](DEVPLAN.md) for the phased plan, and
[docs/guides/pinax.md](docs/guides/pinax.md) for the Pinax model and behavior.

## Layout

```
src/pynakes/
  model.py            BibEntry, BibFile, EntryStore (duplicate-key tolerant)
  bibtex_parser.py    parse_bib() — custom parser, preserves raw_content
  bibtex_writer.py    write_bib() — raw_content for unmodified, reconstruct for modified
  io.py               load_bib / save_bib / save_text / save_plain_text (atomic writes)
  editing.py          surgical raw-text field/key edits + entry-level helpers
  engine.py           Bibliography lifecycle: open, stage, preview/diff, commit, reload
  _engine_*.py        focused Bibliography operation mixins/helpers
  canonical.py        explicit, whole-file canonical layout formatting
  groups.py group_tree.py keys.py fields.py files.py lint.py
  authors.py journals.py normalize.py
  importer.py         resolve + import references by DOI / arXiv id or supported URL
  integrity.py        verify / enrich / published (opt-in --online lookups)
  metadata/           jabref-meta + pynakes-meta parsing, schemas, safe updates
  filestore.py        Pinax paths, manifests, validation, and material transactions
  fetch.py providers/ explicit network-backed material and metadata providers
  interchange/       CSL-JSON, RIS, MODS, EndNote, and CSV codecs
  cli_commands/       command callbacks grouped by concern
  usage.py            cited-entry detection/tagging and TeX citation-key rewrites
  capabilities.py     machine-readable capability description
  batch.py setops.py diff.py cli.py cli_common.py cli_discovery.py
tests/                pytest suite, conformance fixtures, and opt-in agent eval
editor/               VS Code extension companion (TypeScript, own toolchain)
```

`editor/` is a separate client, not part of the Python distribution: it has its
own `npm` toolchain, is excluded from the sdist and wheel, and is not touched by
`pytest` or `ruff check src tests`. It must stay a thin consumer of the engine's
JSON envelope — no BibTeX parser or metadata schema of its own. See
[editor/README.md](editor/README.md).

When work on `editor/` reveals a gap in the engine — a command that does not
exist, a value missing from an envelope, two failures the client cannot tell
apart — close the gap in `pynakes` itself: implement it, or document the
intended behavior. Do not work around it on the TypeScript side. A workaround
in the client puts bibliography logic exactly where it must never live, and it
hides a gap that every other consumer of the JSON envelope shares.

`editor/` is the **project-scoped** client: a bibliography belonging to a
document or repository being edited. VS Code hands a custom editor a single owned
`TextDocument`, so this is imposed by the host, not chosen. Library-scoped work —
exploring a collection that belongs to no project and outlives any workspace — is
the future Bimas application's job, not something to grow the extension into. The
axis is project versus library, not one file versus many: a master library is
often a single `.bib`, and `tex ... scan` spans one `.bib` with many `.tex` files.
The extension may *read* library-scoped things; it never owns or curates them.
Avoid "corpus" when naming this axis — that word already denotes the multi-file
`combine`/`split`/`batch` group. Until Bimas starts, the CLI and the extension are
developed concurrently in this repository; a second client is what would justify
splitting them apart. See
[docs/vision.md](docs/vision.md#graphical-clients-and-their-scope).

## Setup & checks

```bash
pip install -e ".[dev,docs]" # complete development and documentation toolchain
pre-commit install           # enable ruff hooks on commit
pytest --cov --cov-fail-under=90
ruff check src tests         # lint
ruff format --check src tests
mkdocs build --strict
mkdocs serve                 # live-preview the docs at localhost:8000
python -m build              # release artifact check
python -m twine check dist/*
```

The API reference is generated from docstrings by `mkdocstrings`
([docs/api/reference.md](docs/api/reference.md)); keep public-module docstrings
accurate rather than hand-maintaining a symbol list.

For code changes, run the test suite and both Ruff checks before considering the
change done. Changes under `editor/` run their own checks instead
(`npm run compile && npm test` in that directory, or `pixi run test-extension`
from the root). `pixi.toml` provides Node plus a pinned Python 3.11 for building
the extension — `pixi run build-extension` — and does not replace the pip
workflow above for engine work. Run the strict docs build when documentation or public APIs change;
run the artifact checks for packaging or release work. CI runs Python 3.11–3.13,
the 90% coverage gate, strict docs, and wheel/sdist checks.

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
   go through the shared `_finish_mod` / `_safe` helpers in `cli_common.py`. The
   contract is documented in
   [docs/guides/llm-integration.md](docs/guides/llm-integration.md) and guarded
   by tests in `tests/test_cli.py`.
5. **Duplicate citation keys are tolerated, not an error** — the parser keeps
   them; `EntryStore` exposes them via `get_all()` / `duplicate_keys()`.

## Conventions

- Python ≥ 3.11, type hints throughout. Ruff line length 100 (E501 ignored).
- CLI: top-level transforms/checks plus Typer resource families (`ref`,
  `groups`, `keys`, `fields`, `dedupe`, `metadata`, `tex`, `asset`, `corpus`).
  Command callbacks live in `cli_commands/`; operation modules stay independently
  unit-testable. Keep `capabilities` synchronized with the live command surface.
- Try to limit file length preferably to ~500 lines, with a maximum limit of 1000.
- Add tests and a `CHANGELOG.md` entry with each behavioral change.
- Use generic invented references or old, famous historical works in code,
  tests, comments, docstrings, and `CHANGELOG.md`. Never commit examples derived
  from private data, recent bug reports, or user-provided `.bib` entries;
  reproduce with the real entry locally, then commit only a generic equivalent.

## Don't

- Don't replace or bypass the custom parser; it is deliberate and preserves
  round-trip fidelity.
- Don't introduce time, randomness, or unstable ordering in core logic.
  Network access must remain explicit: `ref import`, `ref ... --fetch`,
  `asset fetch`, or opt-in `--online` integrity operations. Everything else
  stays offline and performs no hidden network I/O.
- Don't let a command emit a traceback — route failures through `_safe`.
- Don't claim a feature is implemented when it is a stub. Keep `capabilities`,
  README, and docs honest; keep DEVPLAN forward-looking and put completed work
  in `CHANGELOG.md`.
- Don't work around a missing engine capability inside `editor/`. If the
  extension needs something pynakes does not expose, add it to pynakes — see
  the `editor/` note under [Layout](#layout).
