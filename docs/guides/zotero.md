# Zotero as a Library

Use the running Zotero application as the authoritative personal Library, and
select references into independent project bibliographies. Zotero keeps its
records and PDFs; pynakes writes only the selected project `.bib`.

The initial backend supports **Zotero 10, local API 3, personal library `users/0`**.
Live checks used Zotero 10.0.7 (Flatpak, Linux) and 10.0.8 (Linux). The latter
covered bounded pagination, native search, collection/material discovery and
guarded project selection/repeat/refresh. The repository's `RELEASE.md` records
the validation details.
Other platforms have synthetic transport coverage only. Enable **Allow other applications on this computer to
communicate with Zotero** in Zotero's advanced settings. Reads require no API key,
cloud account, sync or authorization dialog. The backend refuses other major
versions rather than assuming their revision behavior is equivalent.

## Read and select

```bash
pynakes zotero status --json
pynakes zotero scan --limit 20 --json
pynakes zotero show ABCDEFGH --json
pynakes zotero collections --json
pynakes zotero scan --collection DEFGHJKL --where 'year < 1900' --json
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

### Start a project from a collection

```bash
pynakes init paper.bib --dialect biblatex
pynakes zotero collections --json
pynakes zotero select paper.bib --collection DEFGHJKL --dry-run --diff --json
pynakes zotero select paper.bib --collection DEFGHJKL \
    --expect-revision SOURCE_DIGEST --expect-sha256 PROJECT_DIGEST --json
```

Replace the digests with `source_revision_digest` and `source_sha256` from the
preview. Selection accepts repeatable `--item KEY`, a `--collection KEY`, or both;
repeated identities are selected once. Collection selection includes direct
members only and warns about omitted child collections. Notes and attachments
are skipped. The default `--max-items 1000` bounds collection candidates and
selected references; an oversized collection refuses the entire selection.
Increase the explicit budget to select it. Missing project files point to `init`.

A batch has one source revision, one diff and one atomic project write. Its
`selections` report lists each item's source identity, project key, changes and
projection issues. Missing/unsupported items, duplicate works within the batch,
existing unbound matches and divergent edits produce per-item `findings`; any
unresolved finding refuses the whole batch. No partial subset is written.

```bash
pynakes zotero refresh paper.bib --dry-run --diff --json
pynakes zotero refresh paper.bib --expect-revision SOURCE_DIGEST \
    --expect-sha256 PROJECT_DIGEST --json
```

`refresh` finds every binding to the current Zotero instance in the project,
including references no longer in the original collection. It reports other-source
bindings in `foreign_bindings` and leaves them unchanged. Deleted source items
require review; they do not silently delete project entries. With no current-source
bindings, refresh is an explicit no-op. `--max-items` bounds the binding count.

The project's existing key pattern generates new citation keys; `--key` is
available for one explicit item. Better BibTeX `Citation Key:` lines in `Extra`
are not adopted. After selection, keys remain project-owned and survive refresh.
Automatic source-key adoption and collection-to-group mapping are outside v0.10.

### Resolve a refresh conflict

A conflicting `select` returns `conflicts`: each record names a `field` and
shows `baseline_source`, `baseline_project`, `source` and `project` values.
`null` means a deleted/absent field; `@type` denotes the entry type, separately
from a citation field named `type`. The response includes the current source
revision digest and target `source_sha256`, so a decision can be tied to the
exact pair reviewed. No fields or baselines are written on conflict.

After reviewing those values, choose each conflicting field explicitly:

```bash
pynakes zotero select project.bib --item ABCDEFGH \
  --resolve title=project --resolve year=source \
  --expect-revision SOURCE_DIGEST --expect-sha256 PROJECT_DIGEST \
  --dry-run --diff --json
# Apply the same command without --dry-run after reviewing the diff.
```

Replace both digest placeholders with the values from the conflict response.
`source` accepts the incoming value (including deletion); `project` retains the
local value. All conflicts must be resolved together. Decisions for fields that
are no longer conflicting are rejected, as are duplicate decisions and stale
source/target preconditions. Both preconditions are mandatory with `--resolve`.

Accepted source and target baselines advance together. Repeating ordinary
`select` then leaves the accepted difference unchanged. This is a decision about
one change, not a permanent preference: a later source-only change can refresh
the field, while a later divergent source/project edit requires another review.
Use ordinary `select` after applying; do not replay the old resolution flags.

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

For batches and `refresh`, use `findings[].conflicts` and scope each decision to
the source item, for example `--resolve ABCDEFGH:title=source` and
`--resolve CDEFGHJK:@type=project`. Supply both reviewed preconditions. Resolve all
conflicts before the batch can apply; decisions for unknown items or
nonconflicting fields are rejected. Single explicit-item selection retains the
unscoped `FIELD=source|project` form and its existing top-level report fields.

## Search across pages

```bash
# Local query grammar, evaluated across up to 1000 source items:
pynakes zotero search --where 'year < 1900' --max-items 1000 --json
# Explicit Zotero title/creator/year quick search, optionally filtered locally:
pynakes zotero search 'Newton' --where 'type = book' --json
pynakes zotero search --collection DEFGHJKL --where 'year < 1900' --json
```

`search` pages internally. `max_items` counts raw candidates, including skipped
notes and attachments; returned matches never exceed that budget. `complete`
means the candidate search was exhausted. When false, retain `next_cursor` and
repeat with exactly the same query, collection and budget. Empty results with a
cursor do not establish that there are no matches. `scanned` and `skipped` cover
this invocation; `source_total` counts candidates, not local predicate matches.
`stop_reason` is `budget` or `exhausted`. A changed source rejects continuation.

TEXT explicitly uses Zotero's `q` / `qmode=titleCreatorYear`; `--where` always uses
pynakes predicates over the citation projection. A local-only query does not
silently become native quick search. Zotero's native semantics need not match
pynakes predicates or Zotero cloud search. See the
[Zotero search contract](https://www.zotero.org/support/dev/web_api/v3/basics#searching).

## Bounded reads and freshness

`scan`, `collections` and `materials` read at most 100 source items per page
(default 50). Follow `next_cursor` until it is null. `source_total` includes
non-reference items; a page with no references can still have a next cursor.
`scanned` counts source items in that page; `skipped` counts filtered items.
For these single-page commands, `complete` describes source coverage, not whether
pagination has ended. This differs from the multi-page `search` result above.

`scan --where 'year < 1900'` applies the existing query grammar locally to each
citation projection page. It does not mean Zotero quick search, relevance ranking
or a global match count. Its cursor binds the query and page size as well as the
source revision. Queries see projected citation fields, not native tags or notes.

`scan --collection KEY` reads direct members of one collection, including any
non-reference members in the scanned/skipped counts. It does not recursively
include subcollections. Combine it with `--where`; cursors bind both the
collection and query. A missing collection is an explicit source error, whereas
an empty collection returns an empty completed page. Collection IDs come from
`collections`, whose `parent` field describes the hierarchy. Human-readable
collection and material pages print their next cursor as well as JSON output.

Requests go only to `127.0.0.1` (default port 23119, override with `--port`). No
redirects, ambient HTTP proxies, cloud fallback or retries are used. The Python
API exposes a response byte limit (default 4 MiB) and timeout (default 10 seconds).
Oversized or malformed responses fail explicitly. These transport/read budgets,
port, cursor, collection selection, native expansion and search terms are invocation parameters, not
bibliography editing policies or Zotero settings.

Cursors and guarded selection bind the entire application instance, API/schema,
projection version and observed library revision. Each read checks the library
revision before and after; project commit checks it again. This detects edits
while paging and refuses stale reads. It is optimistic checking, not a distributed
transaction or an atomic snapshot of a running application. Zotero's server ID
identifies its database and persists across ordinary restarts. Restarting the
same database does not itself invalidate a binding. A changed instance or schema
requires a fresh connection; automatic rebinding across instances is deliberately
unsupported. An application version change during a connection also requires
reconnecting. See the [local API's server identity contract](https://www.zotero.org/support/dev/web_api/v3/local_api#server_id).

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

Zotero's `scan(collection="DEFGHJKL", where="year < 1900", limit=20)` exposes
the same bounded collection/query behavior as the CLI. For refresh conflicts,
catch `SelectionConflict` from `pynakes.project_selection` and inspect its
`conflicts` and `source_revision`. Call `prepare_selection` again on the same
unchanged target with `resolutions={"title": "project"}` and
`expected_revision=conflict.source_revision`, preview, then commit. The ordinary
target fingerprint and source commit guard remain active.

Zotero additionally exposes `collections()`, `materials(ref)` and
`material_path(material)`. Collection reads give names and hierarchy; memberships
are available in explicit native item data. Material reads give metadata without
paths. `material_path` resolves an explicitly selected attachment only to an
existing local file and checks current ownership. It does not download, copy,
rename or adopt the file into Pinax; missing files are an explicit error.

Source writes, group libraries, annotation transfer, automatic PDF recognition,
two-way synchronization and automatic rebinding after instance changes are not
implemented. Native PDF ingestion and Pinax adoption remain a separate workflow.

For source-neutral batch staging, use `prepare_selections(source, refs, project)`
from `pynakes.project_selection`. It returns `SelectionBatchPlan` and stages
nothing if any item fails; catch `SelectionBatchConflict` to inspect `findings`.
`project_bindings(project)` enumerates attached source identities. Batch
`resolutions` and optional `keys` mappings are keyed by `ItemRef`; decisions
require `expected_revision`. Keep the source open through the single project
commit. Zotero's `source.search(text=None, where="year < 1900", max_items=1000)`
returns the same resumable `SearchResult` as the CLI.
