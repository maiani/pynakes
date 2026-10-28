# pynakes

**pynakes is a reference management engine for BibTeX and BibLaTeX bibliographies and their research materials.**

Its Python API and CLI help researchers and automation acquire references,
curate BibTeX and BibLaTeX bibliographies, compare and enrich records, track
citations, and optionally manage PDFs and source materials with provenance.
Previewed edits, explicit conflicts and source preservation keep the work
reviewable. JabRef compatibility keeps existing libraries and workflows usable.

The engine works with individual bibliographies and explicit operations across
files. Collection-wide `Library` and `Catalogue` APIs and further clients are
planned in the [roadmap](https://github.com/maiani/pynakes/blob/main/DEVPLAN.md).

> **Development status.** The engine is Beta: the CLI and its JSON envelope
> follow a [deprecation policy](guides/public-api.md#compatibility-policy), and
> the Python API is experimental until 1.0.
> The VS Code editor companion is an unpublished alpha.
> Pin versions for reproducible use.

## What it offers

- **Source preservation.** Untouched entries, comments and JabRef metadata
  write back byte-for-byte; surgical edits keep diffs focused, and whole-file
  formatting is an explicit operation.
- **Review before writing.** Modifying commands preview with `--dry-run --diff`
  and report conflicts instead of guessing.
- **Reference management.** Import by DOI, repository identifier, ISBN or URL;
  search, lint, normalize, format, deduplicate, edit, group, convert and export
  references; track TeX citations; prepare scrubbed public copies.
- **Materials.** [Pinax](guides/pinax.md) keeps PDFs and arXiv sources beside a
  `.bib`, addressed by citation key, with provenance.
- **Automation.** Structured JSON, exit codes, change plans and machine-readable
  capabilities serve scripts, CI and agents. Network access is always explicit.

## Start here

```sh
pip install pynakes
pynakes init refs.bib
pynakes lint refs.bib
pynakes normalize refs.bib --dry-run --diff
```

| To… | Read |
| --- | --- |
| Install, or set up a development checkout | [Installation](guides/installation.md) |
| Try an offline walkthrough | [Quick Start](guides/quickstart.md) |
| Learn what each command does | [Usage](guides/usage.md) |
| Look up every option | [Command Reference](guides/command-reference.md) |
| Drive pynakes from a script or LLM agent | [LLM Integration](guides/llm-integration.md) |
| Gate a repository in pre-commit or CI | [Git Workflows](guides/git-workflows.md) |
| Configure a bibliography through metadata | [Metadata Reference](guides/metadata-reference.md) |
| Manage PDFs and sources | [Pinax](guides/pinax.md) |
| Know what goes over the network | [Network and Privacy](guides/network-and-privacy.md) |
| Use the Python API | [API Overview](api/index.md) and [Public API](guides/public-api.md) |
| Understand the design | [Philosophy](vision.md) and [Architecture](guides/architecture.md) |

## License

MIT License. See `LICENSE` in the repository.
