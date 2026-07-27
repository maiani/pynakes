# Import providers

`pynakes ref import` accepts a reference identifier or supported URL, resolves
it to a canonical identifier, fetches metadata through the matching provider,
and converts the response into normalized metadata before creating a
bibliography entry.

This page tracks both the current metadata-import surface and asset-fetch
support. In the **Metadata import** column, **Covered** means that a user can
pass the listed identifier or URL directly to `ref import`; **Planned** means
that it is not yet an import entry point. The **Asset fetch** column describes
what `ref import --fetch` or `asset fetch` can retrieve after an entry exists.

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
| ISBN registries and catalogues | Book metadata | ISBN-10/ISBN-13, Open Library, Google Books, Library of Congress | Planned | None |
| Crossref | DOI registry / metadata index | Crossref work URL and DOI fallback | Planned | Published-PDF URL fallback for the DOI pipeline |
| DataCite | DOI registry / metadata index | DataCite DOI / record URL | Planned | None |
| OpenAlex | Scholarly metadata index | OpenAlex work id / work URL | Planned | OA published-PDF resolver for the DOI pipeline |
| Semantic Scholar | Scholarly metadata index | paper id / paper URL | Planned | None |
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
| Elsevier ScienceDirect | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| Springer Nature / SpringerLink | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| Wiley Online Library | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| PLOS | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| IEEE Xplore | Publisher / digital library | article number or URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| ACM Digital Library | Publisher / digital library | DOI or article URL | Planned | DOI PDF pipeline when a DOI is present |
| AIP Publishing | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| IOPscience | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| Royal Society of Chemistry | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| American Chemical Society | Publisher | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |
| Project Euclid | Publisher platform | article URL to DOI | Planned | DOI PDF pipeline when a DOI is present |

Crossref, OpenAlex, and Semantic Scholar already have clients used by other
workflows. They remain marked Planned until their identifiers or record URLs
can be passed to `ref import`.

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
```

Canonical repository URLs are accepted directly. A bare DOI continues to use
DOI content negotiation; repository-specific URLs select the repository
client, which can retain repository identifiers and archive metadata in
addition to the DOI.

PubMed, PubMed Central, Europe PMC, bioRxiv/medRxiv, Zenodo, OSF, HAL, and
ChemRxiv use structured metadata interfaces. SSRN resolves its canonical DOI;
NBER and Research Square normalize the standard citation metadata exposed by
their record landing pages.

## Provider organization

Import providers are organized by role:

- `providers.metadata` contains metadata services such as DOI content
  negotiation, Crossref, OpenAlex, and Semantic Scholar.
- `providers.repositories` contains repository clients such as arXiv.
- `providers.url_resolvers` contains ordered declarative rules that turn
  supported URLs into canonical identifiers.
- `providers.records.ReferenceMetadata` is the common boundary between
  provider-specific parsing and bibliography entry creation.
- `providers.registry` explicitly maps identifier kinds to import providers.

An external service with its own API, response parser, caching, and error
behavior gets one provider module. An ordinary publisher URL that only exposes
a DOI in its path gets a resolver-table entry rather than a standalone module.

The provider registry and resolver tables are explicit rather than dynamically
discovered, keeping precedence and fallback behavior deterministic.
