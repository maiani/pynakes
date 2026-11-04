# Zotero local API: initial live study

Date: 2026-11-04. Tested Zotero **10.0.7**, Flatpak on Linux, local API v3,
schema 44. These are bounded compatibility observations, not a released adapter,
a supported platform matrix or a complete conformance suite.

## Isolation and method

Use a separate empty profile and data directory with sync disabled, an alternate
loopback port, and synthetic books, collections, notes and PDFs. Confirm its
server identity differs from the normal profile before writes. Authorize writes
through Zotero's own dialog. Requests use public HTTP endpoints only; no database
queries/edits, privileged application APIs or UI automation are required.

Always pass explicit pagination limits: local reads otherwise return unbounded
results. Pin requests to the observed server ID and keep revisions scoped to
that instance. See the official [local API documentation](https://www.zotero.org/support/dev/web_api/v3/local_api)
and [multiple-instance instructions](https://www.zotero.org/support/kb/multiple_instances).

## Observed results

| Case | Result |
| --- | --- |
| Schema discovery | Item types, fields and creator roles available |
| Bounded enumeration | Eight synthetic records across three pages; unique keys and stable revision |
| Native record fidelity | Full date, translator role, literal creator, extra field and overlapping collection memberships preserved |
| Unsynced edits | Local item version advances; stale update rejected with 412 |
| Incremental and conditional reads | `since` identifies the changed record; fresh conditional read returns 304 |
| Instance/authentication guards | Wrong server ID rejected with 412; invalid write key rejected with 401 |
| Partial batch | One valid update persists while one invalid item is reported as failed in the same response |
| Concurrent pagination | Reordering during a scan changes the page revision, allowing the caller to reject the scan |
| Child note | Present in children; excluded from top-level item enumeration |
| Deletion | Deleted synthetic record subsequently returns 404 |
| Linked PDF | Local file URL resolves correctly; original bytes preserved |
| Stored PDF | Three-stage local upload succeeds; stored SHA-256 equals source |
| Restart | Server identity, item data and versions persist; remembered authorization remains usable |

The first twelve-check script passed eleven checks. The initial linked-file test
incorrectly expected a missing file to produce HTTP 404/409: Zotero still returned
302 with its file URL. A follow-up explicitly verified the missing path and
restored the fixture with its hash unchanged. **Resolving a material URL does not
prove its bytes are available.** The adapter must check the selected local file,
report absent/inaccessible bytes and verify identity when copying. It must not
follow arbitrary redirects as HTTP fetches. The initial failure is retained in
the private experiment evidence rather than counted as a passing check.

Stored-file upload and restart were subsequent checks. These synthetic results
justify proceeding with the read adapter and selected material access; successful
write probes do not imply production write support. Client-assigned keys also
require an explicit version/precondition on creation; a bare key is rejected.

## Scope still unverified

- Cross-platform behavior, older versions and future upgrades.
- Actual profile switching, token expiry/revocation and interrupted requests with
  ambiguous write outcomes; wrong-instance and invalid-key rejection alone do
  not cover these cases.
- Group permissions, remote access, unusual item schemas, rich notes and
  annotation transfer.
- Stable common query semantics, projection-loss reports, persisted source-to-
  project mappings and conflicting refreshes through a reusable adapter.
- General throughput/memory bounds. Small synthetic pagination is not a scale
  benchmark; bulk private migration is a separate operational exercise.

The normal profile previously returned 403 while local access was disabled and
200 after it was enabled. That service-level observation is separate from the
isolated synthetic checks. Private migration records, source paths, identifiers,
PDFs and credentials belong outside this repository.

## Consequence for v0.10

Proceed with a thin Zotero-backed Library read/select/project workflow alongside
native PDF ingestion, as specified in [the backend design](library-backends.md).
Retain the stop/restrict criteria. The adapter must isolate loopback transport,
check every batch result, detect changed scan revisions, preserve source-native
records and distinguish attachment preservation from bibliographic recovery.
Neither a one-time migration script nor these tests implement that contract.
