# Git workflows: pre-commit & CI

`pynakes` is built to gate a repository's `.bib` files the same way a linter or
formatter gates source code. Its read-only checks are deterministic, offline,
and report through stable exit codes, so they drop straight into
[pre-commit](https://pre-commit.com/) and CI.

## Keeping a personal Library in Git

A Library can be a private Git repository containing its manifest, member
bibliographies and research notes. Git versions the authoritative files;
`Library` reads them using the same API as an ordinary directory. No Git
backend or database export is needed. A `Bibliography.commit()` saves staged
file edits; it does **not** create a Git commit.

A minimal layout is:

```text
research-library/
  research.library.toml
  references.bib
  notes/
  imports/
```

```toml
pynakes-library = 1
name = "Personal research library"
members = ["references.bib"]
```

Relative membership paths survive a clone or move of this directory. A Library
can later include more `.bib` files without changing the repository model.
Avoid members outside the repository if the clone must contain every reference.
`library add MANIFEST KEY` can select the destination through
[Library routing](library-routing.md). Other CLI writes target individual
bibliographies.

### What belongs in history

| Content | Treatment |
| --- | --- |
| Library manifest and member `.bib` files | Track: these define the collection and reference records. |
| Authored notes and reviewed import reports | Track in the private repository when their history matters. |
| Pinax provenance (`.pinax/manifest.json`) | Track deliberately if using Pinax; it can contain original sources and checksums that cannot be reconstructed from the PDF alone. |
| Catalogue, provider caches and extracted search indexes | Keep outside history by default; a Catalogue is still planned, and derived data should be rebuildable. |
| `.bib.bak`, `.bib.bak.N` and `.pinax/tmp/` | Ignore: local backups and in-flight writes. |
| PDFs, annotations and other materials | Choose a storage/backup policy explicitly; tracking references does not preserve their linked bytes. |

For example, an initial repository using separately stored materials can ignore:

```gitignore
/.cache/
/.pynakes-cache/
/catalogue/
*.bib.bak
*.bib.bak.*
**/.pinax/tmp/
```

Add a material-directory exclusion only if its files are stored and backed up
elsewhere. Do not ignore a whole Pinax directory inadvertently: decide whether
to retain its provenance manifest separately from the material bytes. A
recoverable download URL does not preserve local annotations or revised files.

### Review and merge

Preview engine operations, apply accepted changes, then review `git diff` and
make a scoped Git commit. Keep routine field edits separate from whole-file
formatting: the engine preserves untouched source, which keeps diffs small and
reduces overlapping edits.

Git's text merge does not understand work identity. A clean merge may still
introduce duplicate keys, duplicate works or inconsistent identifiers. After
merging, use the offline lint and duplicate checks below. Resolve Git conflicts
before asking the engine to edit affected files; check `git diff --name-only
--diff-filter=U` and `git diff --check`. Reopen held `Bibliography` and `Library`
objects after switching branches or merging so they read the new bytes.

Project bibliographies remain independently owned files. Exchange selected,
reviewed records rather than publishing the personal Library's entire Git
history. Git synchronization and Library-to-project reconciliation solve
different problems; the latter remains planned.

### Current attachment portability limit

The initial [PDF importer](pdf-import.md) links original PDFs using absolute
paths. A clone preserves those links as text but does not locate or restore the
PDFs on another machine. Existing relative file links and relative Pinax roots
can work when their directory layout is preserved, but PDF import does not yet
offer managed ingestion or a portable attachment-path policy.

The next integration work is to define that policy in the engine, including
source hashes, variant/annotation preservation, relocation and missing-material
diagnostics. Clients can then offer Git review and synchronization around the
same files without making Git a requirement for reference management. No
automatic Git commits, pulls, pushes or semantic merge driver are implemented.

## The gate primitive: `--strict`

By default a check command always exits `0` — it *reports* and never fails a
build. Pass `--strict` to turn a finding into a non-zero exit code:

| Command | `--strict` fails when… |
| --- | --- |
| `pynakes lint --strict` | any finding not suppressed by `lint-ignore`, `--ignore`, or an `ignore` directive |
| `pynakes lint --only duplicate_key --strict` | any citation key is duplicated |
| `pynakes asset check --strict` | any linked file is missing or the wrong type |
| `pynakes dedupe check --strict` | duplicate works (same DOI/arXiv/title) are present |
| `pynakes verify --strict` | any **error or warning** vs. authoritative metadata |
| `pynakes asset fetch --strict` | any requested material failed to download or was unavailable (already-present materials pass) |

`asset fetch --strict` is the one gate on a command that is not read-only and
not offline: it downloads, then gates on completeness, and still emits its full
envelope (see [Pinax](pinax.md#fetch)). It takes one bibliography.

`verify --strict` is intentionally broader: its warnings flag integrity
mismatches against authoritative DOI metadata, which you usually *do* want to
block on. `lint` profile warnings are intentionally gated: they say the
bibliography does not match its declared preferences. Other warnings (e.g. a missing DOI)
remain advisory. See [Metadata Reference](metadata-reference.md).

## Multiple files

The gate checks — `lint`, `verify`, `asset check`,
`dedupe check` — accept one or more `.bib` files:

```bash
pynakes lint refs.bib chapters/*.bib --strict
```

- **One file** emits that command's ordinary envelope.
- **Multiple files** emit an aggregate envelope (specified under
  [JSON contract](llm-integration.md#json-contract)):

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

Four hooks cover the supported workflows:

| Hook | Purpose | Default stage |
| --- | --- | --- |
| `pynakes-fix` | Configured normalization followed by formatting | pre-commit |
| `pynakes-lint` | Read-only quality checks, including duplicate citation keys | pre-commit |
| `pynakes-files-check` | Validate linked material paths | manual |
| `pynakes-dedupe-check` | Detect duplicate works | manual |

The usual setup is fix followed by lint. For read-only checks, omit the fixer.
Add to your repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/maiani/pynakes
    rev: vX.Y.Z  # a released tag that includes pynakes-fix
    hooks:
      - id: pynakes-fix
      - id: pynakes-lint
```

`pynakes-fix` runs `pynakes fix`: ordinary normalization settings and defaults,
then the bibliography's `format-*` layout. It is offline and does not guess
missing data or execute every remedy suggested by lint. Keys are regenerated
only if `normalize-keys` is explicitly enabled; linked TeX and material rename
safeguards still apply. Review any linked-file changes too. Hooks run serially
to avoid concurrent edits to shared linked sources.

For layout alone, use the same hook with an argument:

```yaml
      - id: pynakes-fix
        args: [--mode, layout-only]
```

Or store that policy with `pynakes metadata set references.bib fix-mode layout-only`.
`--mode normalize-and-format` overrides it in the other direction. The Python
API is `Bibliography.fix(mode=None)`, followed by preview/commit as usual.

When the fixer changes files, pre-commit stops the commit. Review the diff,
re-stage the changes, and retry. Lint can still report issues requiring a human
fix. The standalone `format` command remains available for layout-only work;
there is no separate formatting hook.

`pynakes-keys-check` is a deprecated compatibility ID: `pynakes-lint` already
checks duplicate citation keys and follows the same ignore rules. Remove it
when lint is enabled, or use lint with `args: [--only, duplicate_key]` if that
is the only check wanted. The old ID remains through v0.10; removal is no
earlier than v0.11.

The commands also accept several files directly:

```bash
pynakes fix references.bib archive.bib --dry-run --diff
pynakes normalize references.bib archive.bib
pynakes format references.bib archive.bib --check
```

Each file uses its own settings and transaction; successful files may be
written even if another fails. Normalization and formatting within `fix` are
both staged before any write for that file. Multi-file JSON has per-file
`files` results and a `summary`; one input retains its single-file envelope.
Errors return exit 1; `fix` and `normalize` preserve conflicts as exit 2 when
there are no errors. `format --check` writes nothing and returns 1 if any file
needs formatting. `--expect-sha256` requires one input; format's `--out`, stdin
(`-`), and `--recursive` also require one input. With no input, the existing
single-bibliography auto-detection applies.

Then:

```bash
pre-commit install
pre-commit run --all-files
```

The hook runs the release named by `rev`, not the pynakes you may have installed
yourself, so a fix you have tested locally reaches the hook only once a release
includes it and `rev` points at that release. `pre-commit autoupdate` moves
`rev` to the latest release.

pynakes takes its version from git tags, and pre-commit clones only the pinned
commit, without tags. Inside the hook's environment `pynakes --version`
therefore reports a placeholder such as `0.1.0.dev1`. The code is the release
`rev` names; only the label is missing. To check which release a hook runs, read
`rev`, not the version string.

The file and duplicate-work checks use pre-commit's `manual` stage because they have
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

The `pynakes-lint` hook runs `lint --strict --severity warning`: it fails on warnings
and errors, while info findings, such as a field most entries define but one lacks,
are suggestions that do not block a commit. To gate on info findings too, override
the severity; the last `--severity` wins:

```yaml
      - id: pynakes-lint
        args: [--severity, info]
```

Because `lint --strict` fails on any finding it reports, an existing bibliography usually needs
its known, accepted findings recorded before the hook passes — for a group of
entries at once with `ref directive ... --where`, or for the whole bibliography with
`lint-ignore`. New findings then fail the commit that introduces them.

A finding your bibliography can never clear fails the lint hook on every commit. Leave
it out either for the hook alone, with `args`, or for the bibliography itself, with a
`lint-ignore` setting that every `pynakes lint` run then honors (see
[lint](usage.md#lint)):

```yaml
      - id: pynakes-lint
        args: [--ignore, missing_profile_required_field]
```

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
add an online step. Nothing is cached to disk unless you pass `--cache-file`, so a
plain online step leaves no artifact in the checkout:

```yaml
      - name: Verify references online
        run: pynakes verify **/*.bib --online --strict
```

To make repeat runs fast and easy on the providers, point `--cache-file` at a
path and let the runner cache it. Commit it instead if you want the comparison
itself pinned — but remember that a committed cache freezes what "authoritative
metadata" means until you refresh it:

```yaml
      - uses: actions/cache@v4
        with:
          path: .pynakes-cache
          key: pynakes-provider-cache
      - name: Verify references online
        run: pynakes verify **/*.bib --online --strict --cache-file .pynakes-cache
```

## Tips

- Use `--json` in CI when a later step needs to parse results; the human output
  is for logs.
- Parser warnings (e.g. "duplicate citation key … preserving both") go to
  **stderr**, so `--json` on **stdout** is always clean, machine-parsable JSON.
- Pin `rev:` to a released tag so the hook is reproducible.
