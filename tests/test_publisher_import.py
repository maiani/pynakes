"""Import coverage for publisher article URLs and ISBN book catalogues.

Covers the publisher URL rules that carry a DOI in their path or query, the
Elsevier PII-to-DOI resolution path, and the Open Library ISBN client.
"""

from __future__ import annotations

import json

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.importer import (
    DOI,
    ISBN,
    PII,
    DuplicateReferenceError,
    UnsupportedIdentifierError,
    looks_like_isbn,
    prepare_imported_reference,
    resolve_identifier,
)
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import crossref, elsevier, openlibrary
from pynakes.providers.registry import get_import_provider
from pynakes.providers.url_resolvers import (
    extract_publisher_doi,
    resolve_reference_url,
    url_resolution_hint,
)

ELSEVIER_BIBTEX = """@article{Euclid300,
  author = {Euclid},
  title = {On the Ratios of Straight Lines},
  journal = {Reports on Ancient Geometry},
  year = {300},
  doi = {10.5555/ancient.geometry.1}
}
"""

OPEN_LIBRARY_JSON = json.dumps(
    {
        "ISBN:9780000000002": {
            "url": "https://openlibrary.org/books/OL1M/The_Elements",
            "title": "The Elements",
            "subtitle": "Books I to XIII",
            "authors": [{"name": "Euclid"}, {"name": "Thomas Heath"}],
            "publishers": [{"name": "Ancient Press"}],
            "publish_places": [{"name": "Alexandria"}, {"name": "London"}],
            "publish_date": "March 3, 1908",
            "number_of_pages": 432,
            "series": ["Classics of Geometry"],
            "edition_name": "2nd ed.",
            "identifiers": {"isbn_13": ["9780000000002"]},
        }
    }
)


# --- publisher URL rules ---------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://link.springer.com/article/10.5555/springer.article.1",
            (DOI, "10.5555/springer.article.1"),
        ),
        (
            "https://link.springer.com/chapter/10.5555/978-3-000-00000-0_7",
            (DOI, "10.5555/978-3-000-00000-0_7"),
        ),
        (
            "https://link.springer.com/book/10.5555/978-3-000-00000-0",
            (DOI, "10.5555/978-3-000-00000-0"),
        ),
        # Percent-encoded slash, as produced by some Springer search results.
        (
            "https://link.springer.com/article/10.5555%2Fspringer.encoded.1",
            (DOI, "10.5555/springer.encoded.1"),
        ),
        (
            "https://onlinelibrary.wiley.com/doi/10.5555/wiley.article.1",
            (DOI, "10.5555/wiley.article.1"),
        ),
        (
            "https://onlinelibrary.wiley.com/doi/abs/10.5555/wiley.article.2",
            (DOI, "10.5555/wiley.article.2"),
        ),
        (
            "https://onlinelibrary.wiley.com/doi/epdf/10.5555/wiley.article.3?utm_source=x",
            (DOI, "10.5555/wiley.article.3"),
        ),
        # Society-hosted Wiley subdomains use the same path layout.
        (
            "https://agupubs.onlinelibrary.wiley.com/doi/full/10.5555/wiley.article.4",
            (DOI, "10.5555/wiley.article.4"),
        ),
        (
            "https://journals.plos.org/plosone/article?id=10.5555/journal.pone.0000001",
            (DOI, "10.5555/journal.pone.0000001"),
        ),
        (
            "https://journals.plos.org/plosbiology/article/file"
            "?id=10.5555/journal.pbio.0000002&type=printable",
            (DOI, "10.5555/journal.pbio.0000002"),
        ),
        # Elsevier addresses articles by PII rather than DOI.
        (
            "https://www.sciencedirect.com/science/article/pii/S0123456789012345",
            (PII, "S0123456789012345"),
        ),
        (
            "https://www.sciencedirect.com/science/article/abs/pii/S0123456789012345",
            (PII, "S0123456789012345"),
        ),
        (
            "https://linkinghub.elsevier.com/retrieve/pii/S0123456789012345",
            (PII, "S0123456789012345"),
        ),
        (
            "https://iopscience.iop.org/article/10.5555/iop.article.1",
            (DOI, "10.5555/iop.article.1"),
        ),
        # IOP hosts other publishers' content under their own DOI prefixes.
        (
            "https://iopscience.iop.org/article/10.5555/hosted.article.1/meta",
            (DOI, "10.5555/hosted.article.1"),
        ),
        (
            "https://iopscience.iop.org/article/10.5555/iop.article.2/pdf",
            (DOI, "10.5555/iop.article.2"),
        ),
        # SciPost URLs come in a DOI form and a bare article-id form.
        (
            "https://scipost.org/10.21468/SciPostPhys.10.1.001",
            (DOI, "10.21468/SciPostPhys.10.1.001"),
        ),
        ("https://scipost.org/SciPostPhys.10.1.001", (DOI, "10.21468/SciPostPhys.10.1.001")),
        (
            "https://scipost.org/SciPostPhysCore.6.1.001/pdf",
            (DOI, "10.21468/SciPostPhysCore.6.1.001"),
        ),
        # JSTOR: a numeric stable id is the suffix of a 10.2307 DOI.
        ("https://www.jstor.org/stable/1171664", (DOI, "10.2307/1171664")),
        ("https://www.jstor.org/stable/1171664?seq=3", (DOI, "10.2307/1171664")),
        # JSTOR book chapters and hosted content put the whole DOI in the path.
        (
            "https://www.jstor.org/stable/10.2307/j.ctt1jkts6b.9",
            (DOI, "10.2307/j.ctt1jkts6b.9"),
        ),
        ("https://www.jstor.org/stable/10.5555/hosted.book.1", (DOI, "10.5555/hosted.book.1")),
        # AIP: only the legacy scitation URLs carry a DOI.
        ("https://aip.scitation.org/doi/10.5555/aip.article.1", (DOI, "10.5555/aip.article.1")),
        (
            "https://aip.scitation.org/doi/pdf/10.5555/aip.article.2",
            (DOI, "10.5555/aip.article.2"),
        ),
        ("https://openlibrary.org/isbn/9780000000002", (ISBN, "9780000000002")),
        ("https://openlibrary.org/isbn/978-0-00-000000-2.json", (ISBN, "9780000000002")),
    ],
)
def test_resolve_identifier_accepts_publisher_and_catalogue_urls(
    url: str, expected: tuple[str, str]
) -> None:
    assert resolve_identifier(url) == expected


@pytest.mark.parametrize(
    "url,fragment",
    [
        # pubs.aip.org addresses articles by volume/issue/page and an internal id.
        (
            "https://pubs.aip.org/aip/jap/article/135/1/012345/9876543/A-Title",
            "pubs.aip.org",
        ),
        # Legacy IOP URLs are ISSN-based rather than DOI-based.
        ("https://iopscience.iop.org/0034-4885/81/1/016501", "iopscience.iop.org/article"),
        # JSTOR stable ids that are neither numeric nor a DOI.
        ("https://www.jstor.org/stable/community.12345", "numeric or already a DOI"),
    ],
)
def test_resolve_identifier_explains_recognized_but_unresolvable_urls(
    url: str, fragment: str
) -> None:
    with pytest.raises(UnsupportedIdentifierError) as exc:
        resolve_identifier(url)

    assert "Cannot resolve" in str(exc.value)
    assert fragment in str(exc.value)


def test_url_resolution_hint_ignores_resolvable_and_unknown_urls() -> None:
    assert url_resolution_hint("https://iopscience.iop.org/article/10.5555/iop.1") is not None
    assert url_resolution_hint("https://example.com/article/1") is None
    # A hinted host still resolves through its working rules.
    assert resolve_identifier("https://iopscience.iop.org/article/10.5555/iop.1") == (
        DOI,
        "10.5555/iop.1",
    )


def test_publisher_url_rules_report_their_source() -> None:
    resolved = resolve_reference_url("https://link.springer.com/article/10.5555/springer.1")

    assert resolved is not None
    assert resolved.source == "Springer Nature"


@pytest.mark.parametrize(
    "url,expected_doi",
    [
        ("https://link.springer.com/article/10.5555/springer.1", "10.5555/springer.1"),
        ("https://onlinelibrary.wiley.com/doi/pdf/10.5555/wiley.1", "10.5555/wiley.1"),
        (
            "https://journals.plos.org/plosone/article?id=10.5555/journal.pone.1",
            "10.5555/journal.pone.1",
        ),
        ("https://iopscience.iop.org/article/10.5555/iop.1", "10.5555/iop.1"),
        ("https://scipost.org/SciPostPhys.10.1.001", "10.21468/SciPostPhys.10.1.001"),
        ("https://www.jstor.org/stable/1171664", "10.2307/1171664"),
        ("https://aip.scitation.org/doi/10.5555/aip.1", "10.5555/aip.1"),
    ],
)
def test_extract_publisher_doi_covers_new_publishers(url: str, expected_doi: str) -> None:
    assert extract_publisher_doi(url) == expected_doi


def test_extract_publisher_doi_skips_non_doi_rules() -> None:
    # A PII is not a DOI, so the DOI-only helper must not return it.
    url = "https://www.sciencedirect.com/science/article/pii/S0123456789012345"

    assert extract_publisher_doi(url) is None
    assert resolve_reference_url(url) is not None


# --- Elsevier PII resolution ----------------------------------------------


def test_crossref_resolves_alternative_id_to_doi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        crossref,
        "fetch_json",
        lambda url, **kwargs: {
            "message": {"items": [{"DOI": "10.5555/ancient.geometry.1"}]},
        },
    )

    assert crossref.fetch_doi_by_alternative_id("S0123456789012345") == (
        "10.5555/ancient.geometry.1"
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"message": {"items": []}},
        {"message": {"items": [{"DOI": "not-a-doi"}]}},
        {"message": {"items": ["unexpected", {"DOI": 12345}]}},
        {"message": {"items": "unexpected"}},
        {"message": {}},
        {},
    ],
)
def test_crossref_alternative_id_returns_none_without_a_usable_doi(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    monkeypatch.setattr(crossref, "fetch_json", lambda url, **kwargs: payload)

    assert crossref.fetch_doi_by_alternative_id("S0123456789012345") is None


def test_crossref_alternative_id_skips_empty_identifier() -> None:
    assert crossref.fetch_doi_by_alternative_id("   ") is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("S0123456789012345", "S0123456789012345"),
        ("s0123456789012345", "S0123456789012345"),
        ("S0123-4567(89)01234-5", "S0123456789012345"),
        ("PII:S0123456789012345", "S0123456789012345"),
    ],
)
def test_elsevier_normalizes_pii_forms(value: str, expected: str) -> None:
    assert elsevier.normalize_identifier(value) == expected


@pytest.mark.parametrize("value", ["S012345678901234", "0123456789012345", "not-a-pii"])
def test_elsevier_rejects_malformed_pii(value: str) -> None:
    with pytest.raises(ValueError, match="Malformed Elsevier PII"):
        elsevier.normalize_identifier(value)


def test_elsevier_metadata_resolves_pii_then_imports_by_doi() -> None:
    metadata = elsevier.fetch_metadata(
        "S0123456789012345",
        fetcher=lambda doi: ELSEVIER_BIBTEX,
        doi_resolver=lambda pii: "10.5555/ancient.geometry.1",
    )

    assert metadata.provider == "Elsevier ScienceDirect"
    assert metadata.entry_type == "article"
    assert metadata.fields["doi"] == "10.5555/ancient.geometry.1"
    assert metadata.identifier("pii") == "S0123456789012345"
    assert metadata.identifier("doi") == "10.5555/ancient.geometry.1"


def test_elsevier_metadata_keeps_a_canonical_url_when_the_doi_record_has_none() -> None:
    metadata = elsevier.fetch_metadata(
        "S0123456789012345",
        fetcher=lambda doi: "@article{Key, title = {A Title}}",
        doi_resolver=lambda pii: "10.5555/ancient.geometry.1",
    )

    assert metadata.fields["url"] == (
        "https://www.sciencedirect.com/science/article/pii/S0123456789012345"
    )


def test_elsevier_metadata_reports_an_unregistered_pii() -> None:
    with pytest.raises(ProviderFetchError, match="No DOI is registered"):
        elsevier.fetch_metadata(
            "S0123456789012345",
            fetcher=lambda doi: ELSEVIER_BIBTEX,
            doi_resolver=lambda pii: None,
        )


def test_pii_provider_is_registered_and_uses_crossref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        elsevier.crossref,
        "fetch_doi_by_alternative_id",
        lambda pii, **kwargs: "10.5555/ancient.geometry.1",
    )
    provider = get_import_provider(PII)

    metadata = provider.load("S0123456789012345", "bibtex", lambda doi: ELSEVIER_BIBTEX)

    assert provider.name == "Elsevier ScienceDirect"
    assert metadata.identifier("pii") == "S0123456789012345"


def test_prepare_imported_reference_imports_a_sciencedirect_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        elsevier.crossref,
        "fetch_doi_by_alternative_id",
        lambda pii, **kwargs: "10.5555/ancient.geometry.1",
    )
    lib = parse_bib("")

    kind, entry = prepare_imported_reference(
        lib,
        "https://www.sciencedirect.com/science/article/pii/S0123456789012345",
        metadata_fetcher=lambda doi: ELSEVIER_BIBTEX,
    )

    assert kind == PII
    assert entry.type == "article"
    assert entry.fields["doi"] == "10.5555/ancient.geometry.1"


def test_prepare_imported_reference_detects_a_pii_duplicate_by_doi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        elsevier.crossref,
        "fetch_doi_by_alternative_id",
        lambda pii, **kwargs: "10.5555/ancient.geometry.1",
    )
    lib = parse_bib("@article{Existing, doi = {10.5555/ancient.geometry.1}, title = {X}}\n")

    with pytest.raises(DuplicateReferenceError) as exc:
        prepare_imported_reference(
            lib,
            "PII:S0123456789012345",
            metadata_fetcher=lambda doi: ELSEVIER_BIBTEX,
        )

    assert exc.value.keys == ["Existing"]


# --- ISBN and Open Library -------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("9780000000002", "9780000000002"),
        ("978-0-00-000000-2", "9780000000002"),
        ("978 0 00 000000 2", "9780000000002"),
        ("ISBN:9780000000002", "9780000000002"),
        ("isbn-13: 978-0-00-000000-2", "9780000000002"),
        ("0-12-345678-9", "0123456789"),
        ("ISBN:0123456789", "0123456789"),
    ],
)
def test_resolve_identifier_accepts_isbn_forms(value: str, expected: str) -> None:
    assert resolve_identifier(value) == (ISBN, expected)


@pytest.mark.parametrize(
    "value",
    [
        # A bare, unseparated ISBN-10 is indistinguishable from other record ids.
        "0123456789",
        # Wrong check digits are rejected rather than looked up.
        "9780000000003",
        "ISBN:9780000000003",
        "ISBN:12345",
    ],
)
def test_resolve_identifier_rejects_ambiguous_or_invalid_isbns(value: str) -> None:
    with pytest.raises(UnsupportedIdentifierError):
        resolve_identifier(value)


@pytest.mark.parametrize("value", ["", "   ", "{}", "0123456789", "not-an-isbn"])
def test_looks_like_isbn_only_accepts_unambiguous_bare_forms(value: str) -> None:
    assert looks_like_isbn(value) is False
    assert looks_like_isbn("978-0-00-000000-2") is True


def test_open_library_builds_a_book_entry_for_bibtex() -> None:
    metadata = openlibrary.parse_json(OPEN_LIBRARY_JSON, "9780000000002", dialect="bibtex")

    assert metadata.provider == "Open Library"
    assert metadata.entry_type == "book"
    assert metadata.fields["title"] == "The Elements: Books I to XIII"
    assert metadata.fields["author"] == "Euclid and Thomas Heath"
    assert metadata.fields["publisher"] == "Ancient Press"
    assert metadata.fields["address"] == "Alexandria"
    assert metadata.fields["year"] == "1908"
    assert metadata.fields["month"] == "mar"
    assert metadata.fields["series"] == "Classics of Geometry"
    assert metadata.fields["edition"] == "2nd ed."
    assert metadata.fields["isbn"] == "9780000000002"
    assert metadata.fields["url"] == "https://openlibrary.org/isbn/9780000000002"
    assert "pagetotal" not in metadata.fields
    assert metadata.identifier("isbn") == "9780000000002"


def test_open_library_builds_a_book_entry_for_biblatex() -> None:
    metadata = openlibrary.parse_json(OPEN_LIBRARY_JSON, "9780000000002", dialect="biblatex")

    assert metadata.fields["title"] == "The Elements"
    assert metadata.fields["subtitle"] == "Books I to XIII"
    assert metadata.fields["location"] == "Alexandria"
    assert metadata.fields["date"] == "1908-03-03"
    assert metadata.fields["pagetotal"] == "432"
    assert "address" not in metadata.fields
    assert "year" not in metadata.fields


def test_open_library_ignores_unexpected_name_shapes() -> None:
    text = json.dumps(
        {
            "ISBN:9780000000002": {
                "title": "The Elements",
                "authors": [42, {"name": "Euclid"}, {"key": "/authors/OL1A"}],
                "publishers": "Ancient Press",
            }
        }
    )

    metadata = openlibrary.parse_json(text, "9780000000002", dialect="bibtex")

    assert metadata.fields["author"] == "Euclid"
    assert "publisher" not in metadata.fields


def test_open_library_accepts_plain_string_name_lists() -> None:
    text = json.dumps(
        {
            "ISBN:9780000000002": {
                "title": "The Elements",
                "authors": ["Euclid"],
                "publishers": ["Ancient Press", "Second House"],
            }
        }
    )

    metadata = openlibrary.parse_json(text, "9780000000002", dialect="bibtex")

    assert metadata.fields["author"] == "Euclid"
    assert metadata.fields["publisher"] == "Ancient Press and Second House"


def test_open_library_reports_a_missing_record() -> None:
    with pytest.raises(ProviderFetchError, match="no record for ISBN"):
        openlibrary.parse_json("{}", "9780000000002", dialect="bibtex")


def test_open_library_reports_invalid_json() -> None:
    with pytest.raises(ProviderFetchError, match="invalid JSON"):
        openlibrary.parse_json("not json", "9780000000002", dialect="bibtex")


def test_open_library_reports_a_record_without_a_title() -> None:
    text = json.dumps({"ISBN:9780000000002": {"publishers": [{"name": "Ancient Press"}]}})

    with pytest.raises(ProviderFetchError, match="no title"):
        openlibrary.parse_json(text, "9780000000002", dialect="bibtex")


def test_open_library_request_url_uses_the_books_api() -> None:
    assert openlibrary.request_url("978-0-00-000000-2") == (
        "https://openlibrary.org/api/books?bibkeys=ISBN%3A9780000000002&format=json&jscmd=data"
    )


def test_isbn_provider_is_registered() -> None:
    provider = get_import_provider(ISBN)

    metadata = provider.load("9780000000002", "bibtex", lambda isbn: OPEN_LIBRARY_JSON)

    assert provider.name == "Open Library"
    assert metadata.entry_type == "book"


def test_prepare_imported_reference_imports_a_bare_isbn() -> None:
    lib = parse_bib("")

    kind, entry = prepare_imported_reference(
        lib, "978-0-00-000000-2", metadata_fetcher=lambda isbn: OPEN_LIBRARY_JSON
    )

    assert kind == ISBN
    assert entry.type == "book"
    assert entry.fields["isbn"] == "9780000000002"
    assert entry.key == "Euclid1908Elements"


def test_prepare_imported_reference_detects_an_isbn_duplicate() -> None:
    lib = parse_bib("@book{Existing, isbn = {978-0-00-000000-2}, title = {The Elements}}\n")

    with pytest.raises(DuplicateReferenceError) as exc:
        prepare_imported_reference(
            lib, "9780000000002", metadata_fetcher=lambda isbn: OPEN_LIBRARY_JSON
        )

    assert exc.value.keys == ["Existing"]


def test_prepare_imported_reference_allows_an_isbn_duplicate_when_requested() -> None:
    lib = parse_bib("@book{Existing, isbn = {9780000000002}, title = {The Elements}}\n")

    _kind, entry = prepare_imported_reference(
        lib,
        "9780000000002",
        allow_duplicate=True,
        metadata_fetcher=lambda isbn: OPEN_LIBRARY_JSON,
    )

    assert entry.fields["isbn"] == "9780000000002"
