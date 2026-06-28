# Git workflows: pre-commit & CI

`pynakes` is built to gate a repository's `.bib` files the same way a linter or
formatter gates source code. Its read-only checks are deterministic, offline,
and report through stable exit codes, so they drop straight into
[pre-commit](https://pre-commit.com/) and CI.

## The gate primitive: `--strict`

By default a check command always exits `0` — it *reports* and never fails a
build. Pass `--strict` to turn a finding into a non-zero exit code:

| Command | `--strict` fails when… |
| --- | --- |
| `pynakes lint --strict` | any **error** or stored-profile deviation; ordinary warnings stay advisory |
| `pynakes keys check --strict` | any citation key is duplicated |
| `pynakes files check --strict` | any linked file is missing or the wrong type |
| `pynakes dedupe check --strict` | duplicate works (same DOI/arXiv/title) are present |
| `pynakes verify --strict` | any **error or warning** vs. authoritative metadata |

`verify --strict` is intentionally broader: its warnings flag integrity
mismatches against authoritative DOI metadata, which you usually *do* want to
block on. `lint` profile warnings are intentionally gated: they say the library
no longer matches its declared preferences. Other warnings (e.g. a missing DOI)
remain advisory. See [Library Profile](library-profile.md).

## Multiple files

The gate checks — `lint`, `verify`, `keys check`, `files check`,
`dedupe check` — accept one or more `.bib` files:

```bash
pynakes lint refs.bib chapters/*.bib --strict
```

- **One file** preserves the historical per-file JSON envelope unchanged.
- **Multiple files** emit an aggregate envelope:

```json
{
  "status": "success",
  "action": "lint",
  "strict": true,
  "files": [ { "action": "lint", "file": "a.bib", "...": "..." } ],
  "summary": { "files": 2, "failed_files": 1, "issues": 9, "errors": 3, "warnings": 6 }
}
```

An unreadable or malformed file becomes a per-file `{"status": "error", ...}`
object and always fails the run (exit `1`), independent of `--strict`. The
top-level `status` is `"error"` if any file could not be read.

> These commands fan out over the files you pass; they do **not** build a
> cross-file index or merge across files. A whole-collection engine is a
> separate, future capability.

## pre-commit

`pynakes` ships a [`.pre-commit-hooks.yaml`](https://github.com/maiani/pynakes/blob/main/.pre-commit-hooks.yaml).
Add it to your repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/maiani/pynakes
    rev: v0.5.0
    hooks:
      - id: pynakes-lint
      - id: pynakes-keys-check
```

Then:

```bash
pre-commit install
pre-commit run --all-files
```

`pynakes-lint` and `pynakes-keys-check` run on every commit. Two more hooks are
defined but gated behind pre-commit's `manual` stage, because they have
preconditions you may not always meet (linked PDFs checked into the repo;
deciding duplicates are truly unwanted):

```yaml
      - id: pynakes-files-check    # validates linked-file paths
      - id: pynakes-dedupe-check   # flags duplicate works
```

Run them on demand with:

```bash
pre-commit run pynakes-dedupe-check --hook-stage manual --all-files
```

Move them into the default stages (drop the `stages: [manual]`) if you want
them on every commit.

## GitHub Actions

A minimal job that gates a paper repository on citation integrity:

```yaml
name: bibliography
on: [push, pull_request]

jobs:
  check-bib:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pynakes
      - name: Lint bibliography
        run: pynakes lint **/*.bib --strict
      - name: Check for duplicate works
        run: pynakes dedupe check **/*.bib --strict
```

To verify entries against authoritative DOI metadata (network access required),
add an online step. Provider responses are cached deterministically next to the
file, so commit the cache to keep CI runs reproducible and fast:

```yaml
      - name: Verify references online
        run: pynakes verify **/*.bib --online --strict
```

## Tips

- Use `--json` in CI when a later step needs to parse results; the human output
  is for logs.
- Parser warnings (e.g. "duplicate citation key … preserving both") go to
  **stderr**, so `--json` on **stdout** is always clean, machine-parsable JSON.
- Pin `rev:` to a released tag so the hook is reproducible.
