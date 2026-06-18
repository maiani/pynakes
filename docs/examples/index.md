# Examples

Practical examples for common tasks with pynakes.

> **Status — v0.1 in development.** These examples illustrate the planned
> workflow. Most CLI commands are still scaffolded stubs; treat the examples as
> target design until `DEVPLAN.md` marks them complete.

## Example 1: Clean Up a Bibliography

Clean up a messy bibliography by repairing keys, fixing formatting, and validating.

```bash
# 1. Inspect the current state
pynakes inspect refs.bib

# 2. Check for issues
pynakes lint refs.bib --json

# 3. Preview key repair
pynakes keys repair refs.bib --dry-run --diff

# 4. Apply the fix
pynakes keys repair refs.bib

# 5. Convert to BibLaTeX format
pynakes convert refs.bib --to biblatex --dry-run --diff
pynakes convert refs.bib --to biblatex

# 6. Verify the result
pynakes lint refs.bib
```

## Example 2: Organize Papers by Topic

Use groups to organize papers by research area.

```bash
# View all entries
pynakes entries refs.bib --json | jq '.entries | keys'

# Add papers to groups
pynakes groups add-entry refs.bib Smith2020 "Machine Learning"
pynakes groups add-entry refs.bib Jones2021 "Machine Learning"
pynakes groups add-entry refs.bib Brown2022 "Natural Language Processing"
pynakes groups add-entry refs.bib Green2023 "Natural Language Processing"

# List groups
pynakes groups list refs.bib

# See what's in a group
pynakes groups entries refs.bib "Machine Learning"
```

## Example 3: Add Keywords to Specific Papers

Use conditional field operations to tag papers.

```bash
# Add "CBDC" keyword to papers about digital currency
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"' \
  --dry-run --diff

# Apply
pynakes fields append refs.bib keywords "CBDC" \
  --where 'title contains "digital currency"'

# Add "Blockchain" to papers about blockchain
pynakes fields append refs.bib keywords "Blockchain" \
  --where 'title contains "blockchain" OR abstract contains "distributed ledger"' \
  --dry-run --diff

pynakes fields append refs.bib keywords "Blockchain" \
  --where 'title contains "blockchain" OR abstract contains "distributed ledger"'
```

## Example 4: Convert Journal Names

Standardize journal names across the bibliography.

```bash
# Check current journal names
pynakes journals check refs.bib

# Abbreviate common journals
pynakes journals abbreviate refs.bib --dry-run --diff
pynakes journals abbreviate refs.bib

# Or expand them
pynakes journals expand refs.bib --dry-run --diff
pynakes journals expand refs.bib
```

## Example 5: Automated Bibliography Curation with Claude

Use Claude API to curate your bibliography programmatically.

```python
import json
import subprocess
from anthropic import Anthropic

client = Anthropic()

def run_pynakes(command):
    """Run a pynakes command and return JSON output."""
    result = subprocess.run(
        ["pynakes"] + command.split(),
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    else:
        raise Exception(result.stderr)

def curate_with_claude(refs_file):
    """Use Claude to suggest bibliography improvements."""
    
    # 1. Get current state
    inspect = run_pynakes(f"inspect {refs_file} --json")
    issues = run_pynakes(f"lint {refs_file} --json")
    
    # 2. Ask Claude for recommendations
    conversation = []
    
    # Initial prompt
    conversation.append({
        "role": "user",
        "content": f"""I have a BibTeX bibliography with {inspect['entry_count']} entries.

Issues found:
{json.dumps(issues, indent=2)}

What should I do to improve this bibliography? 
Please suggest 3 specific improvements in order of priority."""
    })
    
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        messages=conversation
    )
    
    suggestions = response.content[0].text
    conversation.append({"role": "assistant", "content": suggestions})
    
    # 3. Apply suggestions
    conversation.append({
        "role": "user",
        "content": "For the first suggestion, what pynakes command should I run? Give me the exact command."
    })
    
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=256,
        messages=conversation
    )
    
    command = response.content[0].text
    print(f"Claude recommends: {command}")
    
    # 4. Preview the change
    # (Extract command and run with --dry-run)
    print(f"\nPreview (--dry-run):")
    print(run_pynakes(f"{command} --dry-run --diff"))
    
    # 5. Ask user to confirm
    confirm = input("\nApply this change? (y/n) ")
    if confirm.lower() == "y":
        print("Applying...")
        print(run_pynakes(command))

if __name__ == "__main__":
    curate_with_claude("refs.bib")
```

## Example 6: Bulk Import and Organization

Import a new bibliography and organize it.

```bash
# Start with a downloaded bibliography (e.g., from Zotero)
# zotero_export.bib

# 1. Inspect to understand structure
pynakes inspect zotero_export.bib

# 2. Detect issues
pynakes lint zotero_export.bib --json | jq '.issues'

# 3. Repair duplicate keys
pynakes keys repair zotero_export.bib --dry-run --diff
pynakes keys repair zotero_export.bib

# 4. Merge with existing bibliography
cat zotero_export.bib >> refs.bib

# 5. Fix any new duplicates
pynakes keys repair refs.bib
pynakes lint refs.bib

# 6. Organize by type
pynakes groups add-entry refs.bib $(pynakes entries refs.bib --json | jq -r '.entries[] | select(.type=="article") | .key') "Articles"
```

## Example 7: Export Specific Group

Extract entries from a group into a new file.

```bash
# List all entries in a group
pynakes groups entries refs.bib "Machine Learning" --json > ml_keys.json

# Create a new file with just those entries
python3 << 'EOF'
import json
import subprocess

with open("ml_keys.json") as f:
    keys = json.load(f)["entries"]

# Load the library and extract entries
lib_json = subprocess.run(
    ["pynakes", "inspect", "refs.bib", "--json"],
    capture_output=True,
    text=True
).stdout

lib = json.loads(lib_json)

# Filter to just the keys we want
filtered = {
    "entries": {k: v for k, v in lib["entries"].items() if k in keys},
    "strings": lib["strings"],
    "preamble": lib["preamble"],
}

# Write to new file
with open("ml_papers.json", "w") as f:
    json.dump(filtered, f, indent=2)

print(f"Exported {len(filtered['entries'])} entries to ml_papers.json")
EOF
```

## Example 8: Detect and Merge Duplicates

Find likely duplicate entries and merge them.

```bash
# Detect duplicates (future feature)
pynakes dedupe refs.bib --json

# Output shows potential duplicates:
# {
#   "status": "success",
#   "duplicates": [
#     {"key1": "Smith2020", "key2": "Smith2020a", "similarity": 0.95}
#   ]
# }

# Merge them
pynakes merge refs.bib Smith2020 Smith2020a --dry-run --diff
pynakes merge refs.bib Smith2020 Smith2020a
```

## Example 9: Batch Field Editing

Rename a field across all entries.

```bash
# Convert from BibTeX to BibLaTeX field names
pynakes fields rename refs.bib journal journaltitle --dry-run --diff
pynakes fields rename refs.bib address location --dry-run --diff
pynakes fields rename refs.bib school institution --dry-run --diff

# Apply all (or pick and choose)
pynakes fields rename refs.bib journal journaltitle
pynakes fields rename refs.bib address location
pynakes fields rename refs.bib school institution
```

## Example 10: CI/CD Integration

Use pynakes in a GitHub Actions workflow.

```yaml
name: Bibliography Validation

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install pynakes
        run: pip install pynakes
      
      - name: Lint bibliography
        run: pynakes lint refs.bib --json > lint_report.json
      
      - name: Check for duplicates
        run: |
          pynakes keys check refs.bib --json
          if [ $? -eq 2 ]; then
            echo "Duplicate keys found!"
            exit 1
          fi
      
      - name: Validate key format
        run: pynakes keys generate refs.bib --dry-run --json
      
      - name: Comment on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v6
        with:
          script: |
            const fs = require('fs');
            const lint_report = JSON.parse(fs.readFileSync('lint_report.json', 'utf8'));
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `📚 Bibliography Check\n\n${lint_report.issues.length} issues found.`
            });
```

## Next Steps

- [Usage Guide](../guides/usage.md)
- [API Reference](../api/index.md)
- [Architecture](../guides/architecture.md)
