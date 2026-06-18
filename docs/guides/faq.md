# FAQ

Frequently asked questions about pynakes.

## Installation & Setup

### Q: Can I use pynakes with different Python versions?

A: pynakes requires **Python 3.11 or later**. It uses modern Python features like type hints and pattern matching.

### Q: How do I install pynakes for development?

A: Clone the repo and use editable install:
```bash
git clone https://github.com/user/pynakes.git
cd pynakes
pip install -e ".[dev]"
```

### Q: Can I use pynakes in my CI/CD pipeline?

A: Yes! Use `--json` for programmatic output and check exit codes:
- `0` = success
- `1` = error
- `2` = conflict (needs resolution)

## Usage

### Q: What's the difference between `--dry-run --diff` and just applying changes?

A: `--dry-run` shows what *would* happen without modifying the file. Always use it to preview before committing. After reviewing the diff, run the command without `--dry-run` to apply.

### Q: Why do I get a ".bak" file?

A: pynakes automatically creates backups before modifying files. This is intentional for safety. You can delete `.bak` files after verifying the changes.

### Q: Can I use pynakes with BibLaTeX?

A: Yes, `pynakes` can parse and preserve BibLaTeX-style fields such as
`journaltitle` and `date`. A dedicated BibTeX → BibLaTeX conversion command is
still planned.

### Q: How do I handle entry types that pynakes doesn't recognize?

A: pynakes preserves unknown entry types and fields automatically. As long as the syntax is valid BibTeX, it will work.

### Q: What if I have a very large bibliography?

A: pynakes is designed to handle large files efficiently. Parsing and writing scale linearly. For files with 10k+ entries, operations should complete in seconds.

## Troubleshooting

### Q: I get "ParseError: malformed entry at line X"

A: Check line X in your BibTeX file for syntax errors:
- Missing closing braces `}`
- Mismatched quotes
- Invalid field syntax

Fix the syntax error and retry.

### Q: pynakes says there's a conflict. What do I do?

A: Conflicts happen when an operation has multiple valid outcomes. For example,
DOI import reports a conflict when the DOI is already present:

```json
{
  "status": "conflict",
  "error": "DuplicateDOI",
  "options": [
    {"id": "keep_existing", "description": "Do not import a duplicate reference"},
    {"id": "allow_duplicate", "description": "Retry with --allow-duplicate"}
  ]
}
```

Choose an option and retry with the documented flag, such as
`--allow-duplicate` for DOI import.

### Q: Why does the diff show unchanged entries?

A: If you see entries in the diff that didn't change, it might be due to whitespace or line ending changes. pynakes preserves formatting for unmodified entries, so this shouldn't happen unless the entry was actually modified.

### Q: Can I undo a change?

A: Yes! The `.bak` file is the automatic backup. Restore it:
```bash
cp refs.bib.bak refs.bib
```

Or use git if your file is version controlled.

## Features & Capabilities

### Q: What BibTeX entry types are supported?

A: pynakes supports all standard BibTeX entry types:
- article, book, inproceedings, conference
- phdthesis, mastersthesis, thesis
- misc, techreport, manual
- And any custom entry type

### Q: Can I create custom validation rules?

A: Not yet. This is planned for v0.2. For now, use the standard linting rules.

### Q: Does pynakes support JabRef metadata?

A: Yes. JabRef group metadata is preserved, and `groups` fields can be managed
with `pynakes groups`. `pynakes` also parses JabRef citation-key pattern
metadata such as `keypatterndefault` and `keypattern_<entrytype>` for key
generation and DOI imports. Full structured JabRef metadata editing is still
planned.

### Q: Can I use pynakes to fetch metadata (DOIs, abstracts)?

A: DOI import is implemented:

```bash
pynakes doi import refs.bib 10.5555/example --dry-run --diff
```

Abstract/PDF metadata extraction and provider-specific enrichment are still
planned.

## Agent & Automation

### Q: Can I use pynakes with Claude or other LLMs?

A: Yes. See the [LLM Integration guide](llm-integration.md) for the command surface, JSON envelope, and recommended workflows, or the [API Reference](../api/index.md) for Python usage. The `--json` output is designed for agent integration.

### Q: How do I integrate pynakes with my automation workflow?

A: Use the CLI with `--json` output:
```bash
pynakes inspect refs.bib --json > state.json
pynakes lint refs.bib --json > issues.json
```

Parse the JSON and make decisions in your workflow.

### Q: Can pynakes be used as an MCP server?

A: Not yet. This is planned for v0.3 as `pynakes-mcp`. For now, use the Python API directly.

## Performance

### Q: How fast is pynakes?

A: On typical hardware:
- Parse 1000 entries: ~100ms
- Lint: ~50ms per 1000 entries
- Key repair: ~200ms per 1000 entries
- Write: ~100ms per 1000 entries

### Q: What's the largest bibliography pynakes can handle?

A: Tested up to 100k entries without issues. Memory usage scales linearly with library size.

## Contributing

### Q: How can I contribute?

A: See [CONTRIBUTING.md](https://github.com/user/pynakes/blob/main/CONTRIBUTING.md) for guidelines. Areas we need help:
- Testing with diverse BibTeX files
- New operation implementations
- Documentation and examples
- Feedback on CLI UX

### Q: How do I report a bug?

A: Open an issue on [GitHub Issues](https://github.com/user/pynakes/issues) with:
- Your pynakes version (`pynakes --version`)
- The command you ran
- Your BibTeX file (if possible, a minimal reproducer)
- Expected vs actual behavior

### Q: Can I request a feature?

A: Yes! Open a [GitHub Discussion](https://github.com/user/pynakes/discussions) or create an issue. Check the roadmap in [DEVPLAN.md](https://github.com/user/pynakes/blob/main/DEVPLAN.md) to see what's planned.

## Licensing

### Q: What license is pynakes under?

A: MIT License. See [LICENSE](https://github.com/user/pynakes/blob/main/LICENSE) for details.

### Q: Can I use pynakes in a commercial project?

A: Yes, MIT is permissive. You can use, modify, and distribute pynakes freely, including in commercial projects.

## Support

### Q: Where can I get help?

A: 
- **Quick questions**: Check this FAQ
- **Issues**: Report bugs on [GitHub Issues](https://github.com/user/pynakes/issues)
- **Discussions**: Ask questions on [GitHub Discussions](https://github.com/user/pynakes/discussions)
- **Email**: [andrea.maiani@su.se](mailto:andrea.maiani@su.se)

### Q: Is there a Slack/Discord community?

A: Not yet. As the project grows, we may set up a community channel. For now, use GitHub Discussions.
