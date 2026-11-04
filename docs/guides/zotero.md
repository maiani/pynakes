# Zotero as a Library

Use the running Zotero application as the authoritative personal Library, and
select references into independent project bibliographies. Zotero keeps its
records and PDFs; pynakes writes only the selected project `.bib`.

The initial backend supports **Zotero 10, local API 3, personal library `users/0`**.
Live checks used Zotero 10.0.7 (Flatpak, Linux). Other platforms have synthetic
transport coverage only. Enable **Allow other applications on this computer to
communicate with Zotero** in Zotero's advanced settings. Reads require no API key,
cloud account, sync or authorization dialog. The backend refuses other major
versions rather than assuming their revision behavior is equivalent.

## Read and select

```bash
pynakes zotero status --json
pynakes zotero scan --limit 20 --json
pynakes zotero show ABCDEFGH --json
pynakes zotero collections --json
pynakes zotero materials ABCDEFGH --json

# The project file must already exist; the key belongs to the project.
pynakes zotero select project.bib --item ABCDEFGH --key Newton1687 --dry-run --diff --json
pynakes zotero select project.bib --item ABCDEFGH --key Newton1687 --json
```

Replace the illustrative item key with a key from `scan`. Inspect conversion
warnings before applying. For an apply tied to a reviewed preview, pass its
`source_revision_digest` as `--expect-revision` and its target file fingerprint
as `--expect-sha256`. `--backup` is available; ordinary writes are atomic and
re-parse validated.

Repeat `select` with the same item to refresh its existing selection. The project
key is preserved, including after a local rename. Source edits and project edits
to different fields merge. Divergent changes to the same field, including
source deletions, return a conflict (exit 2) without writing. A repeat with no
source changes is idempotent. A potentially matching unbound project record
requires reconciliation rather than being silently adopted or duplicated.

A `% pynakes-source-v1: ...` comment immediately above the entry stores source
identity and accepted source/target fields as base64 JSON. It is **not encrypted**.
It commits with the entry, survives citation-key renames, and moves with attached
comments. Preserve it for refresh; a malformed or duplicate binding requires
review. It contains citation metadata and a local instance identifier, not keys,
credentials, PDF paths, notes or full native Zotero data. Use `scrub` when producing
a public copy; removing these comments also removes the refresh connection.

The selected projection follows the target's BibTeX/BibLaTeX dialect through the
existing conversion engine. Unmapped thesis types and other conversion limits
are warnings. This is citation projection, not a lossless Zotero export:
unsupported item types cannot be selected; unknown fields, non-author/editor
creator roles, `Extra`, tags and relations produce omission warnings. Supported
title markup and page ranges are converted using the existing engine helpers.
Native metadata is available only through `show --native` and can contain private
content. Notes, annotations and standalone attachments never become paper records.

## Bounded reads and freshness

`scan`, `collections` and `materials` read at most 100 source items per page
(default 50). Follow `next_cursor` until it is null. `source_total` includes
non-reference items; a page with no references can still have a next cursor.
`scanned` counts source items in that page; `skipped` counts filtered items.
`complete` describes source coverage, not whether pagination has ended.

`scan --where 'year < 1900'` applies the existing query grammar locally to each
citation projection page. It does not mean Zotero quick search, relevance ranking
or a global match count. Its cursor binds the query and page size as well as the
source revision. Queries see projected citation fields, not native tags or notes.

Requests go only to `127.0.0.1` (default port 23119, override with `--port`). No
redirects, ambient HTTP proxies, cloud fallback or retries are used. The Python
API exposes a response byte limit (default 4 MiB) and timeout (default 10 seconds).
Oversized or malformed responses fail explicitly. These transport/read budgets,
port, cursor, native expansion and search terms are invocation parameters, not
bibliography editing policies or Zotero settings.

Cursors and guarded selection bind the entire application instance, API/schema,
projection version and observed library revision. Each read checks the library
revision before and after; project commit checks it again. This detects edits
while paging and refuses stale reads. It is optimistic checking, not a distributed
transaction or an atomic snapshot of a running application. An application restart
or changed instance requires a fresh connection and reviewed selection; automatic
rebinding across instances is deliberately unsupported.

## Python API

```python
from pynakes import Bibliography, Library
from pynakes.library_backend import BibTeXLibraryBackend
from pynakes.project_selection import prepare_selection
from pynakes.zotero import ZoteroLibraryBackend

with ZoteroLibraryBackend() as source:
    page = source.scan(limit=20)
    reference = source.get(source.item_ref("ABCDEFGH"))
    project = Bibliography.open("project.bib")
    plan = prepare_selection(source, reference.ref, project, key="Newton1687")
    print(project.diff(), plan.issues)
    project.commit()  # Keep the backend open until the guarded commit finishes.

# Same read/selection boundary over the existing native Library:
source = BibTeXLibraryBackend(Library.open("personal.library.toml"))
page = source.scan(limit=20)
```

The common protocol exposes `describe`, `scan`, and `get`; immutable records carry
source identity separately from citation keys and identifiers. Existing
`Library.open`, `Library.from_files` and file operations remain unchanged.
The file wrapper preserves duplicate-key occurrences and incomplete-member
diagnostics. Its IDs are snapshot-scoped file/hash/index occurrences: reopen
on change, and explicitly reconcile identities rather than guessing across
reordered or edited files. File-backed reads still load the existing native
Library; this is not a new index or bounded-memory file parser.

Zotero additionally exposes `collections()`, `materials(ref)` and
`material_path(material)`. Collection reads give names and hierarchy; memberships
are available in explicit native item data. Material reads give metadata without
paths. `material_path` resolves an explicitly selected attachment only to an
existing local file and checks current ownership. It does not download, copy,
rename or adopt the file into Pinax; missing files are an explicit error.

Source writes, group libraries, annotation transfer, automatic PDF recognition,
two-way synchronization and automatic rebinding after instance changes are not
implemented. Native PDF ingestion and Pinax adoption remain a separate workflow.
