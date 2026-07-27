# Import providers

`pynakes ref import` accepts a reference identifier or supported URL, resolves
it to a canonical identifier, fetches metadata through the matching provider,
and converts the response into normalized metadata before creating a
bibliography entry.

This page tracks both the current import surface and the sources being
considered for v0.6. **Covered** means that a user can pass the listed
identifier or URL directly to the current `ref import` command. **Planned**
means that the source is part of the inventory but is not yet an import entry
point.

## Provider inventory

The list is ordered by expected import value: broad scholarly identifiers
first, then repositories and preprint services, followed by publisher-specific
URL resolvers.

| Provider / source | Kind | Identifier or URL path | `ref import` coverage |
| --- | --- | --- | --- |
| DOI content negotiation | Identifier resolver | DOI, `doi.org` URL | **Covered** |
| arXiv | Preprint server | arXiv id, `arxiv.org` URL | **Covered** |
| PubMed / PubMed Central | Bibliographic index / full-text archive | PMID, PMCID, `pubmed.ncbi.nlm.nih.gov`, `pmc.ncbi.nlm.nih.gov` | Planned |
| Europe PMC | Biomedical index / archive | PMID, PMCID, Europe PMC id / URL | Planned |
| ISBN registries and catalogues | Book metadata | ISBN-10/ISBN-13, Open Library, Google Books, Library of Congress | Planned |
| Crossref | DOI registry / metadata index | Crossref work URL and DOI fallback | Planned |
| DataCite | DOI registry / metadata index | DataCite DOI / record URL | Planned |
| OpenAlex | Scholarly metadata index | OpenAlex work id / work URL | Planned |
| Semantic Scholar | Scholarly metadata index | paper id / paper URL | Planned |
| SSRN | Preprint server | SSRN abstract id / URL | Planned |
| NBER | Working-paper archive | NBER working-paper id / URL | Planned |
| bioRxiv / medRxiv | Preprint servers | DOI, manuscript id, or `biorxiv.org` / `medrxiv.org` URL | Planned |
| Zenodo | Research-output repository | Zenodo record id / URL / DOI | Planned |
| OSF Preprints | Preprint repository | OSF preprint id / URL / DOI | Planned |
| HAL | Institutional repository | HAL id / URL / DOI | Planned |
| ChemRxiv | Preprint server | DOI or ChemRxiv URL | Planned |
| Research Square | Preprint server | DOI or Research Square URL | Planned |
| Nature | Publisher | `nature.com/articles/...` URL to DOI | **Covered** |
| American Physical Society | Publisher | `journals.aps.org/.../(abstract\|pdf)/<doi>` URL | **Covered** |
| Elsevier ScienceDirect | Publisher | article URL to DOI | Planned |
| Springer Nature / SpringerLink | Publisher | article URL to DOI | Planned |
| Wiley Online Library | Publisher | article URL to DOI | Planned |
| PLOS | Publisher | article URL to DOI | Planned |
| IEEE Xplore | Publisher / digital library | article number or URL to DOI | Planned |
| ACM Digital Library | Publisher / digital library | DOI or article URL | Planned |
| AIP Publishing | Publisher | article URL to DOI | Planned |
| IOPscience | Publisher | article URL to DOI | Planned |
| Royal Society of Chemistry | Publisher | article URL to DOI | Planned |
| American Chemical Society | Publisher | article URL to DOI | Planned |
| Project Euclid | Publisher platform | article URL to DOI | Planned |

Crossref, OpenAlex, and Semantic Scholar already have clients used by other
workflows. They remain marked Planned until their identifiers or record URLs
can be passed to `ref import`.

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
