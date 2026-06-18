# Usage Guide

Comprehensive guide to all pynakes commands and features.

> **Status — v0.1 in development.** This guide documents the planned command
> surface. Most commands are not yet functional (scaffolded stubs); see
> `DEVPLAN.md` for current build status.

## Overview

All commands support:
- `--help` — Show command help
- `--dry-run` — Preview changes without modifying the file
- `--diff` — Show unified diff of changes
- `--json` — Output results as JSON

## Commands

### inspect

Inspect the structure of a BibTeX file.

```bash
pynakes inspect refs.bib
pynakes inspect refs.bib --json
```

Output includes:
- Total entry count
- Entry types and counts
- Detected encoding
- Any issues found (duplicates, missing fields, etc.)

### lint

Validate entries for common issues.

```bash
pynakes lint refs.bib
pynakes lint refs.bib --json
```

Checks:
- **Duplicate keys** — Same citation key used multiple times
- **Missing required fields** — By entry type (article, book, inproceedings, thesis)
- **Malformed DOI** — Invalid DOI format
- **Missing DOI** — Warning (not error) for entries without DOI
- **Broken group metadata** — Inconsistent group field formatting

### groups

Manage entry groups (JabRef-style organization).

#### List groups

```bash
pynakes groups list refs.bib
pynakes groups list refs.bib --json
```

#### Add entry to group

```bash
pynakes groups add-entry refs.bib KEY "GroupName" --dry-run --diff
pynakes groups add-entry refs.bib KEY "GroupName"  # Apply
```

#### Remove entry from group

```bash
pynakes groups remove-entry refs.bib KEY "GroupName" --dry-run --diff
```

#### List entries in group

```bash
pynakes groups entries refs.bib "GroupName"
```

### keys

Manage citation keys.

#### Check for duplicates

```bash
pynakes keys check refs.bib
pynakes keys check refs.bib --json
```

#### Generate keys for all entries

```bash
pynakes keys generate refs.bib --dry-run --diff
pynakes keys generate refs.bib  # Apply
```

Key format: `[First author last name][4-digit year][first significant title word]`

Example: `Smith2020BigData`

#### Repair duplicate keys

```bash
pynakes keys repair refs.bib --dry-run --diff
```

Automatically renames duplicate keys by appending a suffix (e.g., `Smith2020_2`).

### fields

Edit entry fields.

#### Rename a field

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
```

#### Move a field (rename and preserve original)

```bash
pynakes fields move refs.bib journal journaltitle --dry-run --diff
```

#### Append to a field

```bash
pynakes fields append refs.bib keywords "NewKeyword" --dry-run --diff
```

With a filter condition:

```bash
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"' \
  --dry-run --diff
```

#### Clear a field

```bash
pynakes fields clear refs.bib abstract --dry-run --diff
```

### convert

Convert between BibTeX formats.

```bash
pynakes convert refs.bib --to biblatex --dry-run --diff
```

Mappings:
- `journal` → `journaltitle`
- `address` → `location`
- `school` → `institution`
- `year` + `month` → `date` (if `date` absent)
- `@phdthesis` → `@thesis` with `type = {phdthesis}`
- `@mastersthesis` → `@thesis` with `type = {mathesis}`

### journals

Manage journal name abbreviations.

#### Abbreviate journals

```bash
pynakes journals abbreviate refs.bib --dry-run --diff
```

#### Expand journals

```bash
pynakes journals expand refs.bib --dry-run --diff
```

#### Check journal consistency

```bash
pynakes journals check refs.bib
```

Detects inconsistent or unknown journal names.

### capabilities

Show pynakes capabilities and supported operations.

```bash
pynakes capabilities --json
```

Output includes:
- Tool version
- Safe-by-default guarantees
- Supported features
- Exit codes
- Available commands

## Global Options

### --help

Show help for any command:

```bash
pynakes --help
pynakes inspect --help
pynakes groups --help
```

### --dry-run

Preview changes without modifying the file:

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run
```

Always use this before applying changes to important files.

### --diff

Show unified diff of what will change:

```bash
pynakes keys repair refs.bib --dry-run --diff
```

### --json

Output results as JSON for automation:

```bash
pynakes inspect refs.bib --json | jq .
pynakes lint refs.bib --json | python -m json.tool
```

## Exit Codes

- **0** — Success
- **1** — Error (parse error, I/O error, invalid arguments)
- **2** — Conflict (operation blocked; options returned in JSON)

## Examples

### Workflow: Clean up a bibliography

```bash
# 1. Inspect
pynakes inspect refs.bib --json

# 2. Find issues
pynakes lint refs.bib --json

# 3. Repair duplicate keys
pynakes keys repair refs.bib --dry-run --diff
pynakes keys repair refs.bib

# 4. Convert to BibLaTeX
pynakes convert refs.bib --to biblatex --dry-run --diff
pynakes convert refs.bib --to biblatex

# 5. Verify
pynakes lint refs.bib
```

### Workflow: Organize into groups

```bash
# List current entries
pynakes entries refs.bib --json | jq '.entries | keys'

# Add AI papers to a group
pynakes groups add-entry refs.bib Smith2020 "AI"
pynakes groups add-entry refs.bib Jones2021 "AI"

# Verify
pynakes groups list refs.bib
pynakes groups entries refs.bib "AI"
```

### Workflow: Automate with agents

```bash
# Generate JSON output for agent processing
pynakes inspect refs.bib --json > state.json
pynakes lint refs.bib --json > issues.json

# Agent decides on changes, triggers pynakes
pynakes keys repair refs.bib --dry-run --diff --json
```

## Common Issues

### File not found

```bash
pynakes inspect nonexistent.bib
# Error: File not found: nonexistent.bib
```

### Parse error

```bash
pynakes inspect malformed.bib
# Error: ParseError: Malformed entry at line 42: missing closing brace
```

See the line number for context and fix the syntax error.

### Conflict detected

```bash
pynakes merge refs.bib Key1 Key2 --dry-run
# Conflict: Cannot merge Key1 and Key2 (conflicting author fields)
# Options: keep_both, keep_first, keep_second
```

Either resolve the conflict manually or pass `--resolution keep_first`.

## Best Practices

1. **Always use dry-run first** — Preview before committing
2. **Check backups** — `.bak` files are created automatically
3. **Use JSON for scripts** — Parse output programmatically
4. **Validate after changes** — Run `lint` to ensure correctness
5. **Keep encoding consistent** — Stick with UTF-8

## Next Steps

- [Examples](../examples/index.md)
- [Architecture](architecture.md)
- [API Reference](../api/index.md)
