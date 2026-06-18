# Quick Start

Get up and running with pynakes in 5 minutes.

> **Status — v0.1 in development.** Most CLI commands shown here are still
> scaffolded stubs. The commands below reflect the planned interface; see
> `DEVPLAN.md` for what currently works.

## 1. Install

```bash
pip install pynakes
```

Or from source:

```bash
git clone https://github.com/user/pynakes.git
cd pynakes
pip install -e .
```

## 2. Inspect Your Bibliography

Get an overview of your BibTeX file:

```bash
pynakes inspect refs.bib
```

Output shows entry count, encoding, and any issues found.

For JSON output (useful for scripts):

```bash
pynakes inspect refs.bib --json
```

## 3. Check for Issues

Lint your bibliography for common problems:

```bash
pynakes lint refs.bib
```

This checks for:
- Duplicate citation keys
- Missing required fields (by entry type)
- Malformed DOI fields
- Broken group metadata

## 4. Preview Changes (Dry-Run)

Before making changes, preview them with `--dry-run`:

```bash
pynakes keys repair refs.bib --dry-run --diff
```

The `--diff` flag shows exactly what will change.

## 5. Apply Changes

Once you're happy with the preview, run the command without `--dry-run`:

```bash
pynakes keys repair refs.bib
```

A backup (`.bak`) is automatically created.

## 6. Organize with Groups

Add entries to groups:

```bash
pynakes groups add-entry refs.bib Smith2020 "AI-Papers"
pynakes groups add-entry refs.bib Jones2021 "AI-Papers"
```

List all groups:

```bash
pynakes groups list refs.bib
```

## 7. Common Operations

### Rename a field

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
```

### Append a field to entries matching a condition

```bash
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"' \
  --dry-run --diff
```

### Check for duplicate keys

```bash
pynakes keys check refs.bib
```

### Convert to BibLaTeX

```bash
pynakes convert refs.bib --to biblatex --dry-run --diff
```

## 8. Capabilities

See what operations pynakes supports:

```bash
pynakes capabilities --json
```

## Tips

- **Always preview first** — use `--dry-run --diff` before applying changes
- **Check backups** — `.bak` files are created automatically
- **Use JSON output** — for automation and parsing by scripts/agents
- **Check encoding** — ensure your BibTeX file is UTF-8 or compatible

## Next Steps

- [Full Usage Guide](usage.md)
- [Examples](../examples/index.md)
- [API Reference](../api/index.md)
