# Import providers

`pynakes ref import` accepts a reference identifier or supported URL, resolves
it to a canonical identifier, fetches metadata through the matching provider,
and converts the response into normalized metadata before creating a
bibliography entry.

This page tracks both the current metadata-import surface and asset-fetch
support. In the **Metadata import** column, **Covered** means that a user can
pass the listed identifier or URL directly to `ref import`; **Partly covered**
means that some of the source's URL shapes work and the rest are described
below; **Planned** means that it is not yet an import entry point; **Not supported**
means that it has been considered and deliberately left out, for the reason the
row or a section below gives. The **Asset fetch** column describes what
`ref import --fetch` or `asset fetch` can retrieve after an entry exists.

**DOI PDF pipeline** means the generic DOI-based published-PDF and
single-supplement resolution path. It is not repository-native fetching and
does not imply that every record has a resolvable PDF. **None** means that no
native or generic asset path is currently available for that source.

## Provider inventory

The list is ordered by expected import value: broad scholarly identifiers
first, then repositories and preprint services, followed by publisher-specific
URL resolvers.

| Provider / source | Kind | Identifier or URL path | Metadata import | Asset fetch |
| --- | --- | --- | --- | --- |
| DOI content negotiation | Identifier resolver | DOI, `doi.org` URL | **Covered** | DOI PDF pipeline |
| arXiv | Preprint server | arXiv id, `arxiv.org` URL | **Covered** | **Native PDF + source**; DOI PDF pipeline when a DOI is present |
| PubMed / PubMed Central | Bibliographic index / full-text archive | PMID, PMCID, `pubmed.ncbi.nlm.nih.gov`, `pmc.ncbi.nlm.nih.gov` | **Covered** | DOI PDF pipeline only; no PMC-native fetch |
| Europe PMC | Biomedical index / archive | Europe PMC source/id or article URL | **Covered** | DOI PDF pipeline only; no Europe-PMC-native fetch |
| INSPIRE-HEP | High-energy-physics database | record id, texkey (`Author:2024abc`), `inspirehep.net/literature/<id>` URL | **Covered** | DOI PDF pipeline; arXiv-native fetch when the record carries an eprint |
| DBLP | Computer-science bibliography | record key, `dblp.org/rec/<key>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| ACL Anthology | Computational-linguistics proceedings | Anthology id (`N19-1423`, `2023.acl-long.1`), `aclanthology.org/<id>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| IACR ePrint | Cryptography preprint archive | `IACR:<year>/<number>`, `eprint.iacr.org/<year>/<number>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| zbMATH Open | Mathematics review database | `zbMATH:<Zbl or DE number>`, `zbmath.org/<id>` URL | **Covered** | None |
| RFC / IETF | Standards-body document archive | `RFC:9110` (also bare `rfc9110`), `datatracker.ietf.org`, `rfc-editor.org`, legacy `tools.ietf.org` URL | **Covered** | DOI PDF pipeline |
| OpenReview | Open peer-review platform | forum id / `openreview.net/forum?id=…` URL | **Not supported** (public API answers a bot challenge to non-browser clients) | None |
| Open Library | Book catalogue | ISBN-10/ISBN-13, `openlibrary.org/isbn/<isbn>` URL | **Covered** | None |
| Google Books | Book catalogue | ISBN / volume id | **Not supported** (needs an API key; Open Library covers ISBN lookups) | None |
| Library of Congress | National library catalogue | LCCN / `lccn.loc.gov` URL | **Not supported** (Open Library covers ISBN-addressed books) | None |
| Crossref | DOI registry / metadata index | `Crossref:<doi>`, `api.crossref.org/works/<doi>` URL | **Covered** | Published-PDF URL fallback for the DOI pipeline |
| DataCite | DOI registry / metadata index | `DataCite:<doi>`, `api.datacite.org/dois/<doi>` URL | **Covered** | None |
| OpenAlex | Scholarly metadata index | `OpenAlex:W<digits>`, `openalex.org` / `api.openalex.org` work URL | **Covered** | OA published-PDF resolver for the DOI pipeline |
| Semantic Scholar | Scholarly metadata index | `SemanticScholar:<paper id>`, `semanticscholar.org/paper/…` URL | **Covered** | None |
| SSRN | Preprint server | SSRN abstract id / URL | **Covered** | DOI PDF pipeline only; no SSRN-native fetch |
| NBER | Working-paper archive | NBER working-paper id / URL | **Covered** | DOI PDF pipeline only; no NBER-native fetch |
| bioRxiv / medRxiv | Preprint servers | DOI or `biorxiv.org` / `medrxiv.org` URL | **Covered** | DOI PDF pipeline only; no native preprint fetch |
| Zenodo | Research-output repository | Zenodo record id / URL / DOI | **Covered** | DOI PDF pipeline only; no Zenodo file fetch |
| OSF Preprints | Preprint repository | OSF preprint id / URL / DOI | **Covered** | DOI PDF pipeline only; no OSF-native fetch |
| HAL | Institutional repository | HAL id / URL / DOI | **Covered** | DOI PDF pipeline only; no HAL-native fetch |
| ChemRxiv | Preprint server | ChemRxiv record id / URL / DOI | **Covered** | DOI PDF pipeline only; no ChemRxiv-native fetch |
| Research Square | Preprint server | manuscript id / URL / DOI | **Covered** | DOI PDF pipeline only; no Research-Square-native fetch |
| Nature | Publisher | `nature.com/articles/...` URL to DOI | **Covered** | DOI PDF pipeline |
| American Physical Society | Publisher | `journals.aps.org/.../(abstract\|pdf)/<doi>` URL | **Covered** | DOI PDF pipeline |
| Elsevier ScienceDirect | Publisher | `sciencedirect.com` / `linkinghub.elsevier.com` article URL, or `PII:` id, resolved to a DOI | **Covered** | DOI PDF pipeline when a DOI is present |
| Springer Nature / SpringerLink | Publisher | `link.springer.com/(article\|chapter\|book\|…)/<doi>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| Wiley Online Library | Publisher | `onlinelibrary.wiley.com/doi/<doi>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| PLOS | Publisher | `journals.plos.org/<journal>/article?id=<doi>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| IOPscience | Publisher | `iopscience.iop.org/article/<doi>` URL, with or without a `/meta`, `/pdf`, or `/fulltext` suffix | **Covered** | DOI PDF pipeline when a DOI is present |
| SciPost | Publisher | `scipost.org/<doi>` or `scipost.org/<article id>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| JSTOR | Digital archive | `jstor.org/stable/<numeric id>` or `jstor.org/stable/<doi>` URL | **Covered** | DOI PDF pipeline when a DOI is present |
| AIP Publishing | Publisher | legacy `aip.scitation.org/doi/<doi>` URL | **Partly covered** | DOI PDF pipeline when a DOI is present |
| ACM Digital Library | Publisher / digital library | `dl.acm.org/doi/<doi>` URL, with or without an `abs`, `full`, `pdf`, `epdf`, or `fullHtml` view segment | **Covered** | DOI PDF pipeline when a DOI is present |
| American Chemical Society | Publisher | `pubs.acs.org/doi/<doi>` URL, with or without an `abs`, `full`, `pdf`, `epdf`, or `book` view segment | **Covered** | DOI PDF pipeline when a DOI is present |
| Royal Society of Chemistry | Publisher | `pubs.rsc.org/en/content/article(landing\|html\|pdf)/<year>/<code>/<suffix>` URL, mapped to `10.1039/<suffix>` | **Covered** | DOI PDF pipeline when a DOI is present |
| Project Euclid | Publisher platform | `projecteuclid.org/journals/…/<doi>` URL, with or without a `.full` or `.short` suffix | **Covered** | DOI PDF pipeline when a DOI is present |
| IEEE Xplore | Publisher / digital library | article number or `ieeexplore.ieee.org` URL | **Not supported** (no offline article-number-to-DOI mapping; recognized and explained) | DOI PDF pipeline when a DOI is present |

Crossref, OpenAlex, and Semantic Scholar have clients that also serve other
workflows; their identifiers and record URLs can now be passed to `ref import`
directly. Crossref remains part of the covered Elsevier path too, where it
resolves a PII to its DOI. None of the four metadata indexes requires an API
key: Crossref's and OpenAlex's `mailto=` parameter is polite-pool courtesy
rather than authentication, and the Semantic Scholar Graph API answers
unauthenticated at low volume — a key only raises its rate limit.

Google Books and the Library of Congress are deliberately out of scope rather
than pending. Google Books needs an API key for dependable quota, and Open
Library already covers ISBN-addressed book lookups, so neither catalogue would
add a field pynakes does not already obtain. Google Scholar stays out because it
has no API and scraping it is against its terms. Any of them may be revisited on
evidence of demand.

## Accepted repository identifiers

Bare numeric and opaque identifiers are ambiguous, so repository ids use an
explicit prefix when they are not supplied as URLs:

```text
PMID:12345678                 PMCID:PMC1234567
EPMC:MED:12345678             SSRN:1234567
NBER:w12345                   Zenodo:1234567
OSF:abc12                     HAL:hal-01234567
bioRxiv:10.1101/2020.01.02.123456
medRxiv:10.1101/2020.01.02.123456
ChemRxiv:record-id            ResearchSquare:rs-123456
ISBN:0123456789               PII:S0123456789012345
INSPIRE:451647                INSPIRE:Author:2024abc
DBLP:journals/cacm/Codd70     ACL:2023.acl-long.1
Crossref:10.1000/example      DataCite:10.5061/dryad.example
OpenAlex:W2741809807          SemanticScholar:<40-hex paper id>
IACR:2023/1234                zbMATH:1607.53082
RFC:9110
```

The four metadata indexes take a prefix for the same reason the repositories do:
a Crossref or DataCite record is addressed by DOI, so `Crossref:` and
`DataCite:` select that index's JSON record instead of DOI content negotiation,
which is the point of naming them explicitly. Their public API record URLs
(`api.crossref.org/works/<doi>`, `api.datacite.org/dois/<doi>`,
`api.openalex.org/works/<id>`) are accepted directly, as is an
`openalex.org/W…` or `semanticscholar.org/paper/…` record URL.

Canonical repository URLs are accepted directly. A bare DOI continues to use
DOI content negotiation; repository-specific URLs select the repository
client, which can retain repository identifiers and archive metadata in
addition to the DOI.

An ISBN may also be given bare when it cannot be confused with another record
id: a hyphenated or spaced ISBN-10/ISBN-13, or a compact ISBN-13 with its
`978`/`979` prefix. A compact ten-digit ISBN-10 needs the `ISBN:` prefix,
because a bare run of ten digits is indistinguishable from other numeric ids.
Check digits are validated before any lookup, so a mistyped ISBN fails locally
rather than as a missing record. The ISBN is kept in the form it was given: no
ISBN-10 to ISBN-13 conversion is performed, so duplicate detection matches an
existing `isbn` field only when both entries use the same ISBN form.

PubMed, PubMed Central, Europe PMC, bioRxiv/medRxiv, Zenodo, OSF, HAL, and
ChemRxiv use structured metadata interfaces. SSRN resolves its canonical DOI;
NBER and Research Square normalize the standard citation metadata exposed by
their record landing pages. Open Library returns edition data, which becomes a
`@book` entry with its publisher, place, edition, and series.

## Databases that publish their own BibTeX

IACR ePrint has no separate citation endpoint: each paper's landing page embeds
a ready-made BibTeX record, which is extracted and parsed like any other
BibTeX-answering service. Its own `cryptoeprint:` key is discarded and a key is
generated instead, as DBLP's is.

INSPIRE-HEP, DBLP, and the ACL Anthology answer with a BibTeX record, which is
richer than the DOI record for their communities: INSPIRE supplies the eprint,
report numbers, and journal reference together, and the Anthology supplies the
venue title, editors, and location. Import uses those records rather than
falling back to content negotiation.

Their citation keys are treated differently because their conventions differ. An
INSPIRE texkey (`Author:2024abc`) is the citation key high-energy physics
already uses, so `--key-source provider` adopts it. DBLP's key is prefixed and
contains path separators, so it is discarded and a key is generated instead.
DBLP's `timestamp`, `biburl`, and `bibsource` bookkeeping fields are dropped.

Because these records carry a DOI, an eprint, or both, duplicate detection works
against entries that were imported from any other provider.

## Publisher URLs, Elsevier's PII, and JSTOR stable ids

Most publisher article URLs carry the DOI in their path or query, so pasting the
page URL is equivalent to importing by DOI — the publisher rule extracts it and
DOI content negotiation supplies the metadata. SciPost and JSTOR extend this to
their own identifier schemes: a SciPost article id becomes a `10.21468` DOI, and
a numeric JSTOR stable id becomes a `10.2307` DOI. JSTOR book chapters and
JSTOR-hosted content already carry the full DOI in the stable path.

ScienceDirect is the exception that needs a lookup: it addresses articles by
Publisher Item Identifier, not DOI. The PII is resolved to a DOI through the
Crossref `alternative-id` index, and the work is then imported by DOI with the
PII kept as identifier evidence. Elsevier deposits the PII as an alternative id,
so an unresolvable PII means no matching Crossref record; `ref import` reports
that and suggests importing by DOI instead of guessing.

## URLs that cannot be resolved

Some platforms publish article URLs that contain no recoverable identifier at
all. IEEE Xplore addresses articles by an internal document number
(`ieeexplore.ieee.org/document/8433652`, and the legacy
`xpl/articleDetails.jsp?arnumber=…` form) that has no published offline mapping
to a DOI; IEEE's metadata API could resolve it but requires a registered key, so
IEEE Xplore is recognized and explained rather than covered. Modern AIP article
URLs on `pubs.aip.org` address articles by volume, issue, page, and an internal
article id; legacy IOPscience URLs are ISSN-based; and JSTOR stable ids that are
neither numeric nor a DOI have no derivable DOI.
Resolving any of them would mean scraping a bot-protected page or guessing, so
`ref import` instead fails with advice to import the DOI shown on the article
page. Only the legacy `aip.scitation.org/doi/<doi>` form is resolvable for AIP.

## Provider organization

Import providers are organized by role:

- `providers.metadata` contains metadata services: DOI content negotiation,
  Crossref, DataCite, OpenAlex, Semantic Scholar, Elsevier, Open Library,
  INSPIRE-HEP, DBLP, the ACL Anthology, IACR ePrint, and zbMATH Open. Services
  that answer with BibTeX
  share the parse-and-relabel step in `providers.metadata._bibtex_service`;
  those that answer with JSON share the fetch-decode-unwrap step in
  `providers.metadata._json_service`.
- `providers._common` holds the record-normalization helpers both trees use —
  text cleaning, person names, date fields, and the shared metadata assembly.
  It sits beside `providers._http` rather than inside either tree, because
  metadata services and repository clients are equally its consumers.
- `providers.repositories` contains repository clients such as arXiv.
- `providers.url_resolvers` contains ordered declarative rules that turn
  supported URLs into canonical identifiers, grouped into identifier authority,
  repository, database, publisher, and catalogue tables. The same module records
  the hosts whose URLs are recognizable but unresolvable, so `ref import` can
  explain them.
- `providers.records.ReferenceMetadata` is the common boundary between
  provider-specific parsing and bibliography entry creation.
- `providers.registry` explicitly maps identifier kinds to import providers.

An external service with its own API, response parser, caching, and error
behavior gets one provider module. An ordinary publisher URL that only exposes
a DOI in its path gets a resolver-table entry rather than a standalone module.
A URL rule resolves to an identifier kind, which need not be a DOI: URL
recognition stays offline and declarative, and any lookup a kind requires — such
as Elsevier's PII-to-DOI step — belongs to its provider module.

The provider registry and resolver tables are explicit rather than dynamically
discovered, keeping precedence and fallback behavior deterministic.
