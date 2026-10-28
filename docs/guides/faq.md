# FAQ

Short answers, with links to the page that covers each topic in full.

## Installation and setup

### Which Python versions are supported?

Python 3.12 or later, on Linux, macOS, and Windows. See the
[installation guide](installation.md), which also covers development installs.

### Can I use pynakes in CI or pre-commit?

Yes. The read-only checks are offline and deterministic, and `--strict` turns
findings into a non-zero exit code. See [Git workflows](git-workflows.md) for
hooks and a GitHub Actions job, and [Exit codes](llm-integration.md#exit-codes)
for what each code means.

## Everyday use

### How do I preview a change?

Add `--dry-run --diff` to any modifying command. It reports what would change
without writing; run the same command without `--dry-run` to apply it.

### Does pynakes create a `.bak` file?

Not by default. Writes are atomic (write-to-temp-then-rename) and
re-parse-validated, so the original is never left half-written. Pass `--backup`
to keep a `<file>.bak` copy of the previous contents. An existing backup is
never overwritten: while `<file>.bak` exists, the next backup is
`<file>.bak.1`, then `<file>.bak.2`, and so on.

### Can I undo a change?

Use version control. If you ran the command with `--backup`, restore the most
recent copy (the highest-numbered `.bak.N`, or `.bak` if there is none):

```sh
cp refs.bib.bak refs.bib
```

### Can I use pynakes with BibLaTeX?

Yes. pynakes parses and preserves BibLaTeX fields such as `journaltitle` and
`date`, follows the bibliography's `dialect` setting, and converts between
conventions with `pynakes convert refs.bib --to biblatex` (or `--to bibtex`).

### What about entry types and fields pynakes does not recognize?

They are preserved unchanged, as are comments and unknown metadata. pynakes
validates required fields for the standard BibTeX and BibLaTeX types; the
[parser conformance baseline](architecture.md#parser-conformance-baseline)
names the toolchain versions it targets.

### Why does a diff show an entry I did not change?

It should not: unmodified entries are written back byte-for-byte. Only
explicit whole-file commands such as `format` rewrite layout. If you see one,
please report it with a minimal example.

## Errors and conflicts

### I get "ParseError: malformed entry at line X"

Check that line for a missing closing brace, mismatched quotes, or invalid
field syntax, fix it, and retry.

### pynakes reports a conflict. What do I do?

A conflict (exit code `2`) means the operation has more than one valid outcome
and nothing was written. The envelope lists `options`; choose one and retry
with the flag it names, such as `--allow-duplicate` when importing a DOI that is
already present. See [Errors and conflicts](llm-integration.md#errors-and-conflicts).

## Features

### Does pynakes work with JabRef?

Yes. JabRef metadata, groups, citation-key patterns and save actions are read
and preserved, and a JabRef-tracked file stays readable in JabRef. See
[JabRef compatibility](jabref-compatibility.md) and the
[metadata reference](metadata-reference.md).

### Can pynakes check linked PDFs?

`asset check` validates JabRef `file` fields and, in a [pinax](pinax.md), the
material directory and its manifest. See [asset](usage.md#asset).

### Can pynakes fetch metadata and PDFs?

Yes, when asked: `ref import` resolves DOIs, repository identifiers, ISBNs and
supported URLs ([Import providers](import-providers.md)); `verify` and `enrich`
compare and fill metadata with `--online`; `asset fetch` downloads PDFs and
arXiv sources into a pinax. pynakes does not extract text from PDFs. See
[Network and privacy](network-and-privacy.md) for what each command sends.

### Can I use pynakes with Claude or other LLM agents?

Yes. The CLI is the agent interface: `pynakes capabilities --json`, the JSON
envelope, exit codes and `--dry-run`. See
[LLM & automation integration](llm-integration.md), or the
[API reference](../api/index.md) for in-process Python use.

### Is there an MCP server?

Not yet. A query-only MCP companion, started as `pynakes mcp`, is planned in
the [development plan](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md);
until then an agent calls the CLI as a tool.

## Performance

### How large a bibliography can pynakes handle?

No supported maximum or performance guarantee is published. pynakes keeps the
parsed data and the source text in memory. The repository's
`scripts/bench_scale.py` times parsing, writing, checks, bounded reads and
analysis on synthetic bibliographies (1,000 to 20,000 entries by default);
its timings are observations for finding slow paths, not guarantees. Large
bibliographies may still expose slow paths, especially in fuzzy deduplication.

## Contributing and support

### How do I report a bug or request a feature?

Open an issue on [GitHub Issues](https://github.com/maiani/pynakes/issues) with
your pynakes version (`pynakes --version`), the command you ran, a minimal
`.bib` that reproduces the problem, and the expected and actual behavior.
Questions and ideas are welcome on
[GitHub Discussions](https://github.com/maiani/pynakes/discussions); the
[development plan](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md)
shows what is planned. To contribute code, see
[CONTRIBUTING.md](https://github.com/maiani/pynakes/blob/main/CONTRIBUTING.md).

You can also write to [dev@andreamaiani.com](mailto:dev@andreamaiani.com).

### What license is pynakes under?

MIT, which permits use, modification and distribution, including in commercial
projects. See [LICENSE](https://github.com/maiani/pynakes/blob/main/LICENSE).
