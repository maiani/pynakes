"""Import coverage for metadata indexes that answer with a JSON record.

Crossref, DataCite, OpenAlex, Semantic Scholar, and zbMATH Open each publish
their own JSON metadata format instead of BibTeX or XML, so these clients
share the fetch-decode-unwrap step in
:mod:`pynakes.providers.metadata._json_service`.
"""

from __future__ import annotations

import json

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.importer import (
    CROSSREF,
    DATACITE,
    OPENALEX,
    SEMANTIC_SCHOLAR,
    ZBMATH,
    DuplicateReferenceError,
    prepare_imported_reference,
    resolve_identifier,
)
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import crossref, datacite, openalex, semantic_scholar, zbmath
from pynakes.providers.registry import IMPORT_PROVIDERS, get_import_provider

S2_ID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

CROSSREF_WORK = {
    "message": {
        "type": "journal-article",
        "title": ["On the Ratios of Straight Lines"],
        "author": [{"given": "Euclid", "family": ""}, {"given": "", "family": "Theon"}],
        "container-title": ["Reports on Ancient Geometry"],
        "volume": "2",
        "issue": "3",
        "page": "231-252",
        "DOI": "10.5555/ancient.geometry.1",
        "published": {"date-parts": [[1607, 4]]},
    }
}

DATACITE_RECORD = {
    "data": {
        "id": "10.5061/dryad.euclid1",
        "type": "dois",
        "attributes": {
            "doi": "10.5061/dryad.euclid1",
            "titles": [{"title": "Measurements from the Elements of Geometry"}],
            "creators": [
                {"name": "Euclid"},
                {
                    "name": "Theon of Alexandria",
                    "givenName": "Theon",
                    "familyName": "of Alexandria",
                },
            ],
            "publisher": "Ancient Data Archive",
            "publicationYear": 1607,
            "types": {"resourceTypeGeneral": "Dataset"},
            "url": "https://datadryad.org/stash/dataset/doi:10.5061/dryad.euclid1",
        },
    }
}

OPENALEX_WORK = {
    "title": "On the Ratios of Straight Lines",
    "type": "journal-article",
    "authorships": [
        {"author": {"display_name": "Euclid"}},
        {"author": {"display_name": "Theon of Alexandria"}},
    ],
    "primary_location": {"source": {"display_name": "Reports on Ancient Geometry"}},
    "publication_year": 1607,
    "doi": "https://doi.org/10.5555/ancient.geometry.1",
}

SEMANTIC_SCHOLAR_PAPER = {
    "title": "On the Ratios of Straight Lines",
    "authors": [{"name": "Euclid of Alexandria"}],
    "venue": "Reports on Ancient Geometry",
    "year": 1607,
    "publicationTypes": ["JournalArticle"],
    "externalIds": {"DOI": "10.5555/ancient.geometry.1"},
    "url": f"https://www.semanticscholar.org/paper/euclid-ratios/{S2_ID}",
}

ZBL_NUMBER = "1607.53082"

ZBMATH_DOCUMENT = {
    "result": {
        "id": 6642421,
        "identifier": ZBL_NUMBER,
        "title": {"title": "On the Ratios of Straight Lines"},
        "contributors": {"authors": [{"name": "Euclid"}, {"name": "Theon of Alexandria"}]},
        "year": "1607",
        "document_type": {"code": "j", "description": "journal article"},
        "source": {
            "series": [
                {
                    "title": "Reports on Ancient Geometry",
                    "short_title": "Rep. Anc. Geom.",
                    "volume": "2",
                    "issue": "3",
                }
            ],
            "pages": "231-252",
        },
        "links": [
            {
                "identifier": "10.5555/ancient.geometry.1",
                "type": "doi",
                "url": "https://doi.org/10.5555/ancient.geometry.1",
            }
        ],
        "zbmath_url": "https://zbmath.org/6642421",
    }
}


# --- identifier and URL resolution -----------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Crossref:10.5555/ancient.geometry.1", (CROSSREF, "10.5555/ancient.geometry.1")),
        (
            "https://api.crossref.org/works/10.5555/ancient.geometry.1",
            (CROSSREF, "10.5555/ancient.geometry.1"),
        ),
        ("DataCite:10.5061/dryad.euclid1", (DATACITE, "10.5061/dryad.euclid1")),
        (
            "https://api.datacite.org/dois/10.5061/dryad.euclid1",
            (DATACITE, "10.5061/dryad.euclid1"),
        ),
        ("OpenAlex:W123456", (OPENALEX, "W123456")),
        ("openalex:w123456", (OPENALEX, "W123456")),
        ("https://openalex.org/W123456", (OPENALEX, "W123456")),
        ("https://api.openalex.org/works/w123456", (OPENALEX, "W123456")),
        (f"SemanticScholar:{S2_ID}", (SEMANTIC_SCHOLAR, S2_ID)),
        (
            f"https://www.semanticscholar.org/paper/euclid-ratios/{S2_ID}",
            (SEMANTIC_SCHOLAR, S2_ID),
        ),
        (
            f"https://semanticscholar.org/paper/{S2_ID.upper()}",
            (SEMANTIC_SCHOLAR, S2_ID),
        ),
        (f"zbMATH:{ZBL_NUMBER}", (ZBMATH, ZBL_NUMBER)),
        ("zbMATH:6642421", (ZBMATH, "6642421")),
        (f"https://zbmath.org/{ZBL_NUMBER}", (ZBMATH, ZBL_NUMBER)),
        ("https://zbmath.org/6642421", (ZBMATH, "6642421")),
    ],
)
def test_resolve_identifier_accepts_json_metadata_index_identifiers(
    value: str, expected: tuple[str, str]
) -> None:
    assert resolve_identifier(value) == expected


@pytest.mark.parametrize(
    "normalizer,value",
    [
        (crossref.normalize_identifier, "not-a-doi"),
        (datacite.normalize_identifier, "not-a-doi"),
        (openalex.normalize_identifier, "X123456"),
        (openalex.normalize_identifier, "W12a34"),
        (semantic_scholar.normalize_identifier, "not-hex"),
        (semantic_scholar.normalize_identifier, "a" * 39),
        (zbmath.normalize_identifier, "not-a-zbl-number"),
        (zbmath.normalize_identifier, "12.34567"),
    ],
)
def test_json_metadata_clients_reject_malformed_identifiers(normalizer, value: str) -> None:
    with pytest.raises(ValueError, match="Malformed"):
        normalizer(value)


def test_json_metadata_normalizers_accept_the_bare_form() -> None:
    assert crossref.normalize_identifier("10.5555/ancient.geometry.1") == (
        "10.5555/ancient.geometry.1"
    )
    assert datacite.normalize_identifier("10.5061/dryad.euclid1") == "10.5061/dryad.euclid1"
    assert openalex.normalize_identifier("w123456") == "W123456"
    assert semantic_scholar.normalize_identifier(S2_ID.upper()) == S2_ID
    assert zbmath.normalize_identifier(ZBL_NUMBER) == ZBL_NUMBER
    assert zbmath.normalize_identifier("6642421") == "6642421"


# --- Crossref ----------------------------------------------------------------


def test_crossref_requests_the_works_json_record() -> None:
    assert crossref.API_URL == "https://api.crossref.org/works/"


def test_crossref_metadata_maps_container_volume_issue_and_pages() -> None:
    metadata = crossref.fetch_metadata(
        "10.5555/ancient.geometry.1", fetcher=lambda _identifier: json.dumps(CROSSREF_WORK)
    )
    assert metadata.provider == "CrossRef"
    assert metadata.entry_type == "article"
    assert metadata.fields["title"] == "On the Ratios of Straight Lines"
    assert metadata.fields["author"] == "Euclid and Theon"
    assert metadata.fields["journal"] == "Reports on Ancient Geometry"
    assert metadata.fields["volume"] == "2"
    assert metadata.fields["number"] == "3"
    # Crossref spells the range with one hyphen; the record renders it the way
    # BibTeX does (see ReferenceMetadata.__post_init__).
    assert metadata.fields["pages"] == "231--252"
    assert metadata.fields["year"] == "1607"
    assert metadata.fields["doi"] == "10.5555/ancient.geometry.1"
    assert metadata.identifier("crossref") == "10.5555/ancient.geometry.1"
    assert metadata.identifier("doi") == "10.5555/ancient.geometry.1"


def test_crossref_uses_article_number_when_page_is_absent() -> None:
    work = dict(CROSSREF_WORK["message"])
    work.pop("page")
    work["article-number"] = "L180501"

    metadata = crossref.metadata_from_work(work, "10.5555/ancient.geometry.1", "bibtex")

    assert metadata.fields["pages"] == "L180501"


@pytest.mark.parametrize(
    "crossref_type,entry_type",
    [
        ("journal-article", "article"),
        ("book-chapter", "inbook"),
        ("proceedings-article", "inproceedings"),
        ("dataset", "misc"),
        (None, "misc"),
    ],
)
def test_crossref_type_mapping(crossref_type: str | None, entry_type: str) -> None:
    work = dict(CROSSREF_WORK["message"])
    work["type"] = crossref_type
    metadata = crossref.metadata_from_work(work, "10.5555/ancient.geometry.1", "bibtex")
    assert metadata.entry_type == entry_type


def test_crossref_reports_an_empty_record() -> None:
    with pytest.raises(ProviderFetchError, match="CrossRef has no record"):
        crossref.fetch_metadata(
            "10.5555/ancient.geometry.1", fetcher=lambda _identifier: json.dumps({})
        )


def test_crossref_reports_invalid_json() -> None:
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        crossref.fetch_metadata("10.5555/ancient.geometry.1", fetcher=lambda _identifier: "{")


# --- DataCite ----------------------------------------------------------------


def test_datacite_requests_the_dois_json_api_record() -> None:
    assert datacite.request_url("10.5061/dryad.euclid1") == (
        "https://api.datacite.org/dois/10.5061/dryad.euclid1"
    )


def test_datacite_metadata_maps_creators_publisher_and_type() -> None:
    metadata = datacite.fetch_metadata(
        "10.5061/dryad.euclid1", fetcher=lambda _identifier: json.dumps(DATACITE_RECORD)
    )
    assert metadata.provider == "DataCite"
    assert metadata.fields["title"] == "Measurements from the Elements of Geometry"
    assert metadata.fields["author"] == "Euclid and Theon of Alexandria"
    assert metadata.fields["publisher"] == "Ancient Data Archive"
    assert metadata.fields["type"] == "Dataset"
    assert metadata.fields["year"] == "1607"
    assert metadata.fields["doi"] == "10.5061/dryad.euclid1"
    assert metadata.fields["url"] == (
        "https://datadryad.org/stash/dataset/doi:10.5061/dryad.euclid1"
    )
    assert metadata.identifier("datacite") == "10.5061/dryad.euclid1"
    assert metadata.identifier("doi") == "10.5061/dryad.euclid1"


def test_datacite_reports_an_empty_record() -> None:
    with pytest.raises(ProviderFetchError, match="DataCite has no record"):
        datacite.fetch_metadata(
            "10.5061/dryad.euclid1", fetcher=lambda _identifier: json.dumps({"data": {}})
        )


def test_datacite_reports_invalid_json() -> None:
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        datacite.fetch_metadata("10.5061/dryad.euclid1", fetcher=lambda _identifier: "{")


# --- OpenAlex ----------------------------------------------------------------


def test_openalex_metadata_maps_authors_venue_and_doi() -> None:
    metadata = openalex.fetch_metadata(
        "W123456", fetcher=lambda _identifier: json.dumps(OPENALEX_WORK)
    )
    assert metadata.provider == "OpenAlex"
    assert metadata.entry_type == "article"
    assert metadata.fields["title"] == "On the Ratios of Straight Lines"
    assert metadata.fields["author"] == "Euclid and Theon of Alexandria"
    assert metadata.fields["journal"] == "Reports on Ancient Geometry"
    assert metadata.fields["year"] == "1607"
    assert metadata.fields["doi"] == "10.5555/ancient.geometry.1"
    assert metadata.fields["url"] == "https://openalex.org/W123456"
    assert metadata.identifier("openalex") == "W123456"
    assert metadata.identifier("doi") == "10.5555/ancient.geometry.1"


@pytest.mark.parametrize(
    "openalex_type,entry_type",
    [
        ("journal-article", "article"),
        ("book-chapter", "inbook"),
        ("proceedings-article", "inproceedings"),
        ("dataset", "misc"),
    ],
)
def test_openalex_reuses_the_crossref_type_mapping(openalex_type: str, entry_type: str) -> None:
    work = dict(OPENALEX_WORK)
    work["type"] = openalex_type
    metadata = openalex.metadata_from_work(work, "W123456", "bibtex")
    assert metadata.entry_type == entry_type


def test_openalex_reports_an_empty_record() -> None:
    with pytest.raises(ProviderFetchError, match="OpenAlex has no record"):
        openalex.fetch_metadata("W123456", fetcher=lambda _identifier: json.dumps({}))


def test_openalex_reports_invalid_json() -> None:
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        openalex.fetch_metadata("W123456", fetcher=lambda _identifier: "{")


# --- Semantic Scholar --------------------------------------------------------


def test_semantic_scholar_id_fetch_requests_an_explicit_field_list() -> None:
    requested_fields = set(semantic_scholar.PAPER_FIELDS.split(","))
    assert {
        "title",
        "authors",
        "venue",
        "year",
        "publicationTypes",
        "journal",
        "externalIds",
    } <= requested_fields


def test_semantic_scholar_metadata_does_not_split_flat_author_names() -> None:
    metadata = semantic_scholar.fetch_metadata(
        S2_ID, fetcher=lambda _identifier: json.dumps(SEMANTIC_SCHOLAR_PAPER)
    )
    assert metadata.provider == "Semantic Scholar"
    assert metadata.entry_type == "article"
    assert metadata.fields["title"] == "On the Ratios of Straight Lines"
    assert metadata.fields["author"] == "Euclid of Alexandria"
    assert metadata.fields["journal"] == "Reports on Ancient Geometry"
    assert metadata.fields["year"] == "1607"
    assert metadata.fields["doi"] == "10.5555/ancient.geometry.1"
    assert metadata.identifier("semantic_scholar") == S2_ID
    assert metadata.identifier("doi") == "10.5555/ancient.geometry.1"


@pytest.mark.parametrize(
    "publication_types,entry_type",
    [
        (["JournalArticle"], "article"),
        (["Conference"], "inproceedings"),
        (["Review"], "misc"),
        (None, "misc"),
    ],
)
def test_semantic_scholar_publication_type_mapping(
    publication_types: list[str] | None, entry_type: str
) -> None:
    paper = dict(SEMANTIC_SCHOLAR_PAPER)
    paper["publicationTypes"] = publication_types
    metadata = semantic_scholar.metadata_from_paper(paper, S2_ID, "bibtex")
    assert metadata.entry_type == entry_type


def test_semantic_scholar_falls_back_to_journal_name_when_venue_is_absent() -> None:
    paper = dict(SEMANTIC_SCHOLAR_PAPER)
    del paper["venue"]
    paper["journal"] = {"name": "Reports on Ancient Geometry"}
    metadata = semantic_scholar.metadata_from_paper(paper, S2_ID, "bibtex")
    assert metadata.fields["journal"] == "Reports on Ancient Geometry"


def test_semantic_scholar_reports_an_empty_record() -> None:
    with pytest.raises(ProviderFetchError, match="Semantic Scholar has no record"):
        semantic_scholar.fetch_metadata(S2_ID, fetcher=lambda _identifier: json.dumps({}))


def test_semantic_scholar_reports_invalid_json() -> None:
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        semantic_scholar.fetch_metadata(S2_ID, fetcher=lambda _identifier: "{")


def test_semantic_scholar_fetch_paper_by_id_takes_no_api_key() -> None:
    """The Graph API must stay usable with no key; a key only raises rate limits."""
    import inspect

    parameters = inspect.signature(semantic_scholar.fetch_paper_by_id).parameters
    assert "api_key" not in parameters
    assert "key" not in parameters


# --- zbMATH Open --------------------------------------------------------------


def test_zbmath_requests_a_search_for_a_zbl_number_and_a_lookup_for_a_de_number() -> None:
    assert zbmath.request_url(ZBL_NUMBER) == (
        f"https://api.zbmath.org/v1/document/_search?search_string=an%3A{ZBL_NUMBER}"
    )
    assert zbmath.request_url("6642421") == "https://api.zbmath.org/v1/document/6642421"


def test_zbmath_record_url_works_for_either_identifier_form() -> None:
    assert zbmath.record_url(ZBL_NUMBER) == f"https://zbmath.org/{ZBL_NUMBER}"
    assert zbmath.record_url("6642421") == "https://zbmath.org/6642421"


def test_zbmath_metadata_maps_authors_journal_and_doi() -> None:
    metadata = zbmath.fetch_metadata(
        ZBL_NUMBER, fetcher=lambda _identifier: json.dumps(ZBMATH_DOCUMENT)
    )
    assert metadata.provider == "zbMATH Open"
    assert metadata.entry_type == "article"
    assert metadata.fields["title"] == "On the Ratios of Straight Lines"
    assert metadata.fields["author"] == "Euclid and Theon of Alexandria"
    assert metadata.fields["journal"] == "Reports on Ancient Geometry"
    assert metadata.fields["volume"] == "2"
    assert metadata.fields["number"] == "3"
    # Crossref spells the range with one hyphen; the record renders it the way
    # BibTeX does (see ReferenceMetadata.__post_init__).
    assert metadata.fields["pages"] == "231--252"
    assert metadata.fields["year"] == "1607"
    assert metadata.fields["doi"] == "10.5555/ancient.geometry.1"
    assert metadata.fields["url"] == "https://zbmath.org/6642421"
    assert metadata.identifier("zbmath") == ZBL_NUMBER
    assert metadata.identifier("doi") == "10.5555/ancient.geometry.1"


def test_zbmath_metadata_addressed_by_de_number_keeps_that_form_as_the_identifier() -> None:
    metadata = zbmath.fetch_metadata(
        "6642421", fetcher=lambda _identifier: json.dumps(ZBMATH_DOCUMENT)
    )
    assert metadata.identifier("zbmath") == "6642421"


@pytest.mark.parametrize(
    "document_type,entry_type",
    [
        ({"code": "j", "description": "journal article"}, "article"),
        ({"code": "b", "description": "book"}, "book"),
        ({"code": "a", "description": "article in a collection"}, "misc"),
        (None, "misc"),
    ],
)
def test_zbmath_document_type_mapping(document_type: dict | None, entry_type: str) -> None:
    record = json.loads(json.dumps(ZBMATH_DOCUMENT))["result"]
    record["document_type"] = document_type
    metadata = zbmath.metadata_from_record(record, ZBL_NUMBER, "bibtex")
    assert metadata.entry_type == entry_type


def test_zbmath_reports_an_empty_record_for_an_unknown_de_number() -> None:
    with pytest.raises(ProviderFetchError, match="zbMATH Open has no record"):
        zbmath.fetch_metadata("6642421", fetcher=lambda _identifier: json.dumps({"result": None}))


def test_zbmath_reports_an_empty_record_for_an_unmatched_search() -> None:
    with pytest.raises(ProviderFetchError, match="zbMATH Open has no record"):
        zbmath.fetch_metadata(ZBL_NUMBER, fetcher=lambda _identifier: json.dumps({"result": []}))


def test_zbmath_reports_invalid_json() -> None:
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        zbmath.fetch_metadata(ZBL_NUMBER, fetcher=lambda _identifier: "{")


# --- registry and duplicate detection --------------------------------------


@pytest.mark.parametrize(
    "kind,name,identifier,payload",
    [
        (CROSSREF, "CrossRef", "10.5555/ancient.geometry.1", CROSSREF_WORK),
        (DATACITE, "DataCite", "10.5061/dryad.euclid1", DATACITE_RECORD),
        (OPENALEX, "OpenAlex", "W123456", OPENALEX_WORK),
        (SEMANTIC_SCHOLAR, "Semantic Scholar", S2_ID, SEMANTIC_SCHOLAR_PAPER),
        (ZBMATH, "zbMATH Open", ZBL_NUMBER, ZBMATH_DOCUMENT),
    ],
)
def test_json_metadata_providers_are_registered(
    kind: str, name: str, identifier: str, payload: dict
) -> None:
    provider = get_import_provider(kind)

    metadata = provider.load(identifier, "bibtex", lambda _value: json.dumps(payload))

    assert provider.name == name
    assert metadata.identifier(kind) == identifier


def test_all_json_metadata_providers_are_registered() -> None:
    assert {CROSSREF, DATACITE, OPENALEX, SEMANTIC_SCHOLAR, ZBMATH} <= IMPORT_PROVIDERS.keys()


@pytest.mark.parametrize(
    "identifier,payload",
    [
        ("Crossref:10.5555/ancient.geometry.1", CROSSREF_WORK),
        ("DataCite:10.5061/dryad.euclid1", DATACITE_RECORD),
        ("OpenAlex:W123456", OPENALEX_WORK),
        (f"SemanticScholar:{S2_ID}", SEMANTIC_SCHOLAR_PAPER),
        (f"zbMATH:{ZBL_NUMBER}", ZBMATH_DOCUMENT),
    ],
)
def test_json_metadata_imports_detect_a_duplicate_by_doi(identifier: str, payload: dict) -> None:
    lib = parse_bib("@article{Existing, doi = {10.5555/ancient.geometry.1}, title = {X}}\n")
    # DataCite is addressed by its own DOI, so seed that case with a matching library DOI too.
    if identifier.startswith("DataCite:"):
        lib = parse_bib("@article{Existing, doi = {10.5061/dryad.euclid1}, title = {X}}\n")

    with pytest.raises(DuplicateReferenceError) as exc:
        prepare_imported_reference(
            lib, identifier, metadata_fetcher=lambda _value: json.dumps(payload)
        )

    assert exc.value.keys == ["Existing"]


def test_prepare_imported_reference_generates_a_key_for_crossref() -> None:
    kind, entry = prepare_imported_reference(
        parse_bib(""),
        "Crossref:10.5555/ancient.geometry.1",
        metadata_fetcher=lambda _value: json.dumps(CROSSREF_WORK),
    )
    assert kind == CROSSREF
    assert entry.fields["title"] == "On the Ratios of Straight Lines"


def test_prepare_imported_reference_generates_a_key_for_zbmath() -> None:
    kind, entry = prepare_imported_reference(
        parse_bib(""),
        f"zbMATH:{ZBL_NUMBER}",
        metadata_fetcher=lambda _value: json.dumps(ZBMATH_DOCUMENT),
    )
    assert kind == ZBMATH
    assert entry.fields["title"] == "On the Ratios of Straight Lines"


def test_datacite_creators_without_a_name_use_given_and_family_parts() -> None:
    """DataCite spells its person parts ``givenName``/``familyName``.

    Many members deposit those alone, with no combined ``name``, so the shared
    person helper must recognize them rather than dropping the creator.
    """
    record = json.loads(json.dumps(DATACITE_RECORD))
    record["data"]["attributes"]["creators"] = [
        {"givenName": "Galileo", "familyName": "Galilei"},
        {"name": "Anonymous Scribe"},
    ]
    metadata = datacite.fetch_metadata(
        "10.5061/dryad.euclid1", fetcher=lambda _identifier: json.dumps(record)
    )
    assert metadata.fields["author"] == "Galileo Galilei and Anonymous Scribe"


@pytest.mark.parametrize(
    ("work_type", "entry_type"),
    [
        ("article", "article"),
        ("book", "book"),
        ("monograph", "book"),
        ("edited-book", "book"),
        ("reference-book", "book"),
        ("book-part", "inbook"),
        ("book-section", "inbook"),
        ("proceedings", "proceedings"),
        ("preprint", "misc"),
    ],
)
def test_openalex_native_type_vocabulary_is_mapped(work_type: str, entry_type: str) -> None:
    """OpenAlex says ``article`` where Crossref says ``journal-article``.

    Only targets spelled identically in BibTeX and BibLaTeX are mapped; the
    rest stay ``misc`` instead of guessing a dialect-specific type.
    """
    work = dict(OPENALEX_WORK)
    work["type"] = work_type
    assert openalex.metadata_from_work(work, "W123456", "bibtex").entry_type == entry_type
