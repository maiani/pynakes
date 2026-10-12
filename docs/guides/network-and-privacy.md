# Network and privacy

Bibliography maintenance is offline by default. `inspect`, `search`, `lint`,
`format`, `normalize`, metadata/group/field/key edits, `tex` operations,
`asset check`, `asset repair`, `scrub` and corpus operations make no network
requests. Files and bibliographies are not uploaded to an analytics service.

## Commands that contact services

| Invocation | Data sent | Recipients |
| --- | --- | --- |
| `ref import FILE IDENTIFIER...` | Supplied identifier or URL; a URL resolver may extract a DOI or another identifier before requesting metadata | The selected provider in [Import providers](import-providers.md), DOI resolver and redirected publisher where applicable |
| `ref find REFERENCE --online` | The complete free-text reference, in Crossref's `query.bibliographic` URL parameter, plus result limit | `api.crossref.org` |
| `ref compare FILE KEY --online` | Selected entry's DOI or arXiv identifier | DOI resolver/publisher or arXiv |
| `verify FILE --online` | Each selected entry's DOI or arXiv identifier used for comparison | DOI resolver/publisher and arXiv as applicable |
| `enrich FILE --online` | Selected entries' DOI/arXiv identifiers; journal title selects the preferred provider locally | APS Harvest for recognized APS journals, DOI resolver/publisher as fallback, arXiv as applicable |
| `verify` / `enrich --online --published` | Preprint identifiers; discovered DOI identifiers used for published-version checks | arXiv, Crossref, OpenAlex, DOI resolver/publisher as applicable |
| `asset fetch FILE [KEY]` | Configured material identifiers and URLs; DOI and arXiv identifiers for discovery/backfill | arXiv, OpenAlex, Crossref, DOI resolver, publisher and material hosts as applicable |
| `ref add` / `ref import --fetch` | Import metadata requests where applicable, then the same identifiers and URLs as `asset fetch` for the added entry | The same metadata and material services |

`--dry-run` prevents writes; it does **not** prevent network requests made to
prepare a preview. `ref import` and `asset fetch` authorize requests through
the command itself; `--fetch` authorizes downloads on add/import. Find, compare, verify and enrich use `--online` to authorize remote lookups. Without that opt-in, they do not contact
providers. `ref find` requires it to return candidates.

These are requests for identifiers and records, rather than uploads of the
whole `.bib`. Identifiers, queries and URL paths can still reveal unpublished
work. The destination service sees the caller's IP address, request headers and
query parameters; redirected requests reach additional hosts. A provider's
privacy/retention policy governs its logs. Caller-supplied URLs may themselves
contain sensitive query parameters.

## Headers and credentials

The built-in HTTP client identifies itself as
`pynakes/<installed version> (+https://github.com/maiani/pynakes)` in its
`User-Agent`. Content negotiation adds `Accept` headers for the requested
format. The client does not send a Crossref/OpenAlex `mailto` parameter and has
no configuration option for one.

pynakes does not imitate a browser's `User-Agent`. A publisher's edge (bot
protection, a CDN) may answer this client differently from a browser — a `403`
or an HTML challenge page where a browser gets the PDF. `asset fetch` reports
the HTTP status, content type and final URL of each request in `attempts`, so
such a refusal is visible rather than silent.

`PYNAKES_APS_API_TOKEN` supplies an optional APS-issued bearer token to the APS
Harvest metadata endpoint (`harvest.aps.org`); it is not sent with PDF
downloads. Institutional IP access may work
without a token. Do not put credentials in bibliography fields, example URLs,
committed configuration, or shared cache files. The HTTP client rejects URLs with embedded username/password credentials
and private/local network destinations, including redirect targets.
HTTPS-to-HTTP redirects emit a warning; they are not blocked. `asset fetch`
tries a plain-HTTP material URL's HTTPS form first.
Each HTTP fetch has a bounded overall
deadline, 120 seconds by default.

## Local artifacts

Provider responses are persisted across runs only when `--cache-file PATH` is
supplied. The cache stores queried identifiers (including free-text queries)
and provider results; treat it as research data before sharing or committing
it. Pinax downloads and manifests record local material paths, source URLs,
fetch dates and hashes. A manifest's stored hash is provenance:
`asset check` does not recompute checksums.

`scrub` prepares a public bibliography copy by removing configured private
fields, comments and metadata. Review the result: scrubbing a `.bib` does not
scrub adjacent cache files, downloaded materials or provider logs.
