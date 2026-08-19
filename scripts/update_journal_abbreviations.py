#!/usr/bin/env python3
"""Refresh the bundled JabRef journal-abbreviation CSVs from upstream.

Developer-only maintenance tool: it is not part of the pynakes package or its
runtime, and pynakes itself makes no implicit network calls. Run this by hand
to re-sync ``src/pynakes/journal_abbreviations/*.csv`` against
https://github.com/JabRef/abbrv.jabref.org (CC0-licensed) and regenerate
``NOTICE.md`` with the commit that was fetched.

Every ``journals/*.csv`` file in that repo is fetched (the file list is
discovered from the API, not hardcoded) — matching what JabRef itself does:
"At each release of JabRef all available journal lists ... are combined".

Usage: python scripts/update_journal_abbreviations.py
"""

import json
import urllib.request
from pathlib import Path

REPO = "JabRef/abbrv.jabref.org"
BRANCH = "main"
CONTENTS_API = f"https://api.github.com/repos/{REPO}/contents/journals"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/journals"
COMMIT_API = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
TARGET_DIR = Path(__file__).resolve().parent.parent / "src" / "pynakes" / "journal_abbreviations"

NOTICE_TEMPLATE = """\
# Bundled journal abbreviation data

The CSV files in this directory are vendored, unmodified, from
[abbrv.jabref.org](https://github.com/JabRef/abbrv.jabref.org) — the same
journal abbreviation lists JabRef itself ships and uses for its "Manage
journal abbreviations" feature.

- Source: <https://github.com/JabRef/abbrv.jabref.org>
- License: CC0 1.0 Universal (public domain dedication) — see upstream
  `LICENSE.md`. No attribution is legally required; this notice is kept for
  traceability.
- Vendored from commit `{sha}` ({date}), branch `{branch}`.
- Files (see upstream `journals/README.md` for what each list covers):
{file_list}

These are used as-is (including any upstream data quirks, e.g. occasional
unescaped commas in an abbreviation field) — pynakes does not edit them by
hand. Refresh with:

```bash
python scripts/update_journal_abbreviations.py
```
"""


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pynakes-update-script"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read()


def main() -> None:
    commit = json.loads(_fetch(COMMIT_API))
    sha = commit["sha"]
    date = commit["commit"]["author"]["date"]

    listing = json.loads(_fetch(CONTENTS_API))
    names = sorted(item["name"] for item in listing if item["name"].endswith(".csv"))

    for name in names:
        data = _fetch(f"{RAW_BASE}/{name}")
        (TARGET_DIR / name).write_bytes(data)
        print(f"updated {name} ({len(data)} bytes)")

    # Drop any previously-vendored file upstream no longer ships. This never
    # touches pynakes_overrides.csv — it doesn't match the vendored prefix.
    for path in TARGET_DIR.glob("journal_abbreviations_*.csv"):
        if path.name not in names:
            path.unlink()
            print(f"removed stale {path.name}")

    file_list = "\n".join(f"  - `{name}`" for name in names)
    notice = NOTICE_TEMPLATE.format(sha=sha, date=date, branch=BRANCH, file_list=file_list)
    (TARGET_DIR / "NOTICE.md").write_text(notice, encoding="utf-8")
    print(f"vendored {len(names)} file(s) from commit {sha} ({date})")


if __name__ == "__main__":
    main()
