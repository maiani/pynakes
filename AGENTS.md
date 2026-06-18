# Using pynakes with Claude and other agents

This document describes how to integrate pynakes with Claude, other LLMs, and automation workflows.

## Quick summary

`pynakes` is agent-friendly:

- **Deterministic**: Same input always produces the same output.
- **Dry-run by default**: Use `--dry-run` to preview changes without side effects.
- **Structured output**: `--json` for all operations; easy to parse and act on.
- **Safe conflicts**: Conflicts are reported with options, not guesses.
- **Atomic operations**: Each operation is independent and can be composed.

## Capabilities introspection

Get the full list of supported operations:

```bash
pynakes capabilities --json
```

Returns:

```json
{
  "tool": "pynakes",
  "version": "0.1",
  "safe_by_default": true,
  "supports_dry_run": true,
  "supports_json_output": true,
  "supports_backup": true,
  "supports_atomic_write": true,
  "exit_codes": {
    "0": "success",
    "1": "error (parse, validation, I/O)",
    "2": "conflict (operation blocked; options returned)"
  },
  "capabilities": [
    "parse_bibtex",
    "inspect_library",
    "manage_groups",
    "manage_fields",
    "generate_keys",
    "detect_duplicates",
    "lint",
    "convert_formats",
    "abbreviate_journals"
  ],
  "commands": {
    "inspect": "Inspect a .bib file structure",
    "groups": "Manage entry groups",
    "fields": "Edit fields (rename, move, append, clear)",
    "keys": "Generate and check citation keys",
    "lint": "Validate entries",
    "convert": "Convert BibTeX to BibLaTeX",
    "journals": "Abbreviate or expand journal names",
    "entries": "List or show individual entries"
  }
}
```

## Typical agent workflow

### 1. Inspect

Get the current state:

```bash
pynakes inspect refs.bib --json
```

Returns:

```json
{
  "file": "refs.bib",
  "encoding": "utf-8",
  "entry_count": 42,
  "entries": [
    {"key": "Smith2020", "type": "article", "fields": {...}},
    {"key": "Jones2021", "type": "book", "fields": {...}}
  ],
  "issues": [
    {"type": "missing_doi", "key": "Smith2020"},
    {"type": "duplicate_key", "keys": ["Jones2021", "Jones2021b"]}
  ]
}
```

### 2. Plan

Based on the inspection, decide what operations to perform. Common patterns:

- **Lint and report**: Run `pynakes lint --json` to identify issues.
- **Add to group**: Use `pynakes groups add-entry` to organize entries.
- **Rename fields**: Use `pynakes fields rename` for format conversions.
- **Detect duplicates**: Use `pynakes dedupe --json` to find duplicates.

### 3. Dry-run and diff

Before making changes, preview them:

```bash
pynakes fields rename refs.bib journal journaltitle --dry-run --diff --json
```

Returns:

```json
{
  "status": "success",
  "action": "rename_field",
  "file": "refs.bib",
  "would_modify": true,
  "modified_entries": 8,
  "diff": "--- refs.bib\n+++ refs.bib\n@@ -5,7 +5,7 @@\n ...",
  "warnings": [],
  "errors": []
}
```

### 4. Execute or bail

If the dry-run looks good, execute the operation:

```bash
pynakes fields rename refs.bib journal journaltitle --json
```

If there's an issue (conflict or error), report it to the user or try a different approach.

## Exit codes and error handling

### Exit code 0: Success

The operation completed. Check `status` in JSON output or `stdout` in human-readable output.

### Exit code 1: Error

A fatal error occurred (parse error, validation error, I/O error). Example:

```json
{
  "status": "error",
  "error": "ParseError",
  "message": "Malformed entry at line 42: missing closing brace",
  "file": "refs.bib",
  "line": 42
}
```

Agent should: report the error to the user and offer to inspect the file manually.

### Exit code 2: Conflict

An operation could not safely complete due to conflicting data. Example (merge):

```json
{
  "status": "conflict",
  "error": "ConflictError",
  "message": "Cannot merge Smith2020 and Smith2020b: conflicting author fields",
  "options": [
    {
      "id": "keep_both",
      "description": "Keep both entries (rename key to Smith2020b_merge)"
    },
    {
      "id": "keep_first",
      "description": "Keep Smith2020, discard Smith2020b"
    },
    {
      "id": "keep_second",
      "description": "Keep Smith2020b, discard Smith2020"
    }
  ]
}
```

Agent should: ask the user which option to choose, or try a different operation.

## JSON output format

All commands with `--json` return a consistent structure:

```json
{
  "status": "success" | "error" | "conflict",
  "action": "<command_name>",
  "file": "refs.bib",
  "dry_run": true | false,
  "would_modify": true | false,
  "modified_entries": <count>,
  "diff": "<unified_diff_if_--diff_was_passed>",
  "errors": [],
  "warnings": [
    {
      "type": "<warning_type>",
      "message": "<message>",
      "entry_key": "<key_if_applicable>"
    }
  ]
}
```

## Common agent tasks

### Task 1: Identify and fix lint issues

```bash
# 1. Get issues
pynakes lint refs.bib --json

# 2. For each issue, dry-run a fix
pynakes keys repair refs.bib --dry-run --diff --json

# 3. If good, apply
pynakes keys repair refs.bib --json
```

### Task 2: Add entries to a group

```bash
# 1. List current groups
pynakes groups list refs.bib --json

# 2. For each entry to add, dry-run
pynakes groups add-entry refs.bib KEY "GroupName" --dry-run --diff --json

# 3. Apply if OK
pynakes groups add-entry refs.bib KEY "GroupName" --json
```

### Task 3: Convert to BibLaTeX

```bash
# 1. Preview conversion
pynakes convert refs.bib --to biblatex --dry-run --diff --json

# 2. Check for warnings
# Review warnings in JSON output

# 3. Apply
pynakes convert refs.bib --to biblatex --json
```

### Task 4: Find and merge duplicates

```bash
# 1. Detect duplicates
pynakes dedupe refs.bib --json

# 2. For each duplicate pair, dry-run merge
pynakes merge refs.bib KEY1 KEY2 --dry-run --diff --json

# 3. If output looks good, merge
pynakes merge refs.bib KEY1 KEY2 --json

# 4. If conflict, ask user to choose
# Retry with --resolution option
```

### Task 5: Bulk field edit with filtering

```bash
# 1. Preview the edit
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"' \
  --dry-run --diff --json

# 2. Apply
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"' \
  --json
```

## MCP integration (future)

When `pynakes-mcp` is available, Claude can use pynakes operations directly:

```python
# Claude SDK (pseudocode)
client = Anthropic()

tools = load_mcp_server("pynakes-mcp")

response = client.messages.create(
    model="claude-opus-4-8",
    max_tokens=1024,
    tools=tools,
    messages=[{
        "role": "user",
        "content": "Add all papers about CBDC to the 'CBDC' group in my refs.bib"
    }]
)

# Claude calls pynakes tools internally:
# - inspect refs.bib
# - search for CBDC papers
# - dry-run add-entry for each
# - ask user to confirm
# - apply changes
```

## Design for agent safety

pynakes is built with agent use in mind:

1. **Explicit operations**: No monolithic "do whatever" function. Each operation is specific.
2. **Dry-run first**: Agents should preview before committing (`--dry-run`).
3. **Clear conflicts**: If something can't be decided, report options instead of guessing.
4. **Structured output**: JSON makes it easy for agents to parse and reason about results.
5. **Deterministic**: Same input → same output. No randomness or timeouts.
6. **Atomic**: Each operation is independent and composable.
7. **Backups**: By default, a `.bak` file is created before modifications.

## Best practices for agents

### ✅ Do

- **Always dry-run first**: Use `--dry-run --diff --json` to preview.
- **Check exit codes**: Exit code 2 means conflict; don't ignore it.
- **Validate input**: Check that keys, group names, and field names exist before operating on them.
- **Report diffs**: When showing changes to the user, include the unified diff.
- **Create backups**: Pass `--backup` to `pynakes` (default) or manage backups externally.
- **Compose operations**: Chain multiple small operations rather than one big one.

### ❌ Don't

- **Skip dry-run**: Always preview changes first, even in automated workflows.
- **Ignore conflicts**: If an operation returns exit code 2, ask the user to choose.
- **Chain --dry-run with writes**: `--dry-run` never modifies files; you must run without it to apply changes.
- **Assume field names**: Always inspect the file first to see what fields exist.
- **Parse BibTeX yourself**: Let pynakes handle it; it's designed for preservation.

## Example: Claude assistant for bibliography curation

```python
import subprocess
import json

def run_pynakes(command, file, *args, dry_run=True, json_output=True):
    """Run a pynakes command and return parsed JSON."""
    cmd = ["pynakes", command, file]
    cmd.extend(args)
    if dry_run:
        cmd.append("--dry-run")
    if json_output:
        cmd.append("--json")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return json.loads(result.stdout)
    elif result.returncode == 2:
        # Conflict: return for user review
        return json.loads(result.stdout)
    else:
        raise Exception(f"pynakes error: {result.stderr}")

def add_entry_to_group(file, key, group):
    """Add an entry to a group with confirmation."""
    # Dry-run
    dry = run_pynakes("groups", "add-entry", file, key, group, 
                      dry_run=True, json_output=True)
    
    if dry["status"] == "conflict":
        return {"success": False, "conflict": dry}
    
    print(f"Would add {key} to {group}:")
    print(dry["diff"])
    
    # Ask user
    confirmed = input("OK? [y/n] ")
    if confirmed.lower() != "y":
        return {"success": False, "reason": "user cancelled"}
    
    # Apply
    result = run_pynakes("groups", "add-entry", file, key, group, 
                         dry_run=False, json_output=True)
    return result

def curate_bibliography(file, criteria):
    """Curate bibliography based on criteria (e.g., 'add all CBDC papers to group')."""
    # 1. Inspect
    inspect = run_pynakes("inspect", file, dry_run=False)
    entries = inspect["entries"]
    
    # 2. Find matches
    matches = [e for e in entries if criteria(e)]
    
    # 3. For each match, add to group
    results = []
    for entry in matches:
        result = add_entry_to_group(file, entry["key"], "CBDC")
        results.append(result)
    
    return results
```

## Troubleshooting

### pynakes command not found

Ensure pynakes is installed and in `$PATH`:

```bash
pip install -e .
which pynakes
```

### JSON parse error on output

pynakes returns JSON only with `--json` flag. Without it, output is human-readable text.

### Dry-run succeeds but write fails

This can happen if file permissions change between dry-run and write, or if the file is deleted. pynakes will create a backup and report the error.

### Conflict reported with no options

This is a bug. Report it on GitHub with the command and a minimal reproducer.

## See also

- [ARCHITECTURE.md](ARCHITECTURE.md) — internal design
- [README.md](README.md) — user guide and quickstart
- [DEVPLAN.md](DEVPLAN.md) — phased implementation plan
