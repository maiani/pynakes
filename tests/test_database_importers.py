"""Import coverage for bibliographic databases that publish their own BibTeX.

INSPIRE-HEP, DBLP, the ACL Anthology, and the IACR ePrint Archive answer with
a BibTeX record, so these clients share the parse-and-relabel step in
:mod:`pynakes.providers.metadata._bibtex_service`. IACR has no dedicated
citation endpoint: its BibTeX is embedded in the paper's own landing page
HTML and extracted before sharing that step.
"""

from __future__ import annotations

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.importer import (
    ACL,
    DBLP,
    IACR,
    INSPIRE,
    DuplicateReferenceError,
    prepare_imported_reference,
    resolve_identifier,
)
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.metadata import acl_anthology, dblp, iacr, inspire
from pynakes.providers.registry import get_import_provider

INSPIRE_BIBTEX = """@article{Euclid:0300abc,
    author = "Euclid",
    title = "{On the Ratios of Straight Lines}",
    eprint = "hist-ph/0300001",
    archivePrefix = "arXiv",
    reportNumber = "ALEX-300-A1",
    doi = "10.5555/ancient.geometry.1",
    journal = "Reports on Ancient Geometry",
    volume = "2",
    pages = "231--252",
    year = "300"
}
"""

DBLP_BIBTEX = """@article{DBLP:journals/rag/Euclid300,
  author       = {Euclid},
  title        = {On the Ratios of Straight Lines},
  journal      = {Reports on Ancient Geometry},
  volume       = {2},
  pages        = {231--252},
  year         = {300},
  url          = {https://doi.org/10.5555/ancient.geometry.1},
  doi          = {10.5555/ancient.geometry.1},
  timestamp    = {Fri, 24 Mar 2023 16:31:07 +0100},
  biburl       = {https://dblp.org/rec/journals/rag/Euclid300.bib},
  bibsource    = {dblp computer science bibliography, https://dblp.org}
}
"""

ACL_BIBTEX = """@inproceedings{euclid-300-ratios,
    title = "On the Ratios of Straight Lines",
    author = "Euclid",
    editor = "Heath, Thomas",
    booktitle = "Proceedings of the Alexandria Conference on Geometry",
    year = "300",
    address = "Alexandria",
    publisher = "Ancient Press",
    doi = "10.5555/ancient.geometry.1",
    pages = "231--252"
}
"""

IACR_PAGE = """<!doctype html>
<html><body>
<h3>On the Ratios of Straight Lines</h3>
<p class="mt-4"><strong>BibTeX</strong> <button id="bibcopy"></button></p>
<pre id="bibtex">
@misc{cryptoeprint:0300/1234,
      author = {Euclid},
      title = {On the Ratios of Straight Lines},
      howpublished = {Cryptology {ePrint} Archive, Paper 0300/1234},
      year = {300},
      doi = {10.5555/ancient.geometry.1},
      url = {https://eprint.iacr.org/0300/1234}
}
</pre>
</body></html>
"""


# --- identifier and URL resolution -----------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("INSPIRE:451647", (INSPIRE, "451647")),
        # A texkey keeps its case: INSPIRE texkeys are used verbatim as cite keys.
        ("INSPIRE:Euclid:0300abc", (INSPIRE, "Euclid:0300abc")),
        ("https://inspirehep.net/literature/451647", (INSPIRE, "451647")),
        ("https://inspirehep.net/api/literature/451647", (INSPIRE, "451647")),
        ("DBLP:journals/cacm/Codd70", (DBLP, "journals/cacm/Codd70")),
        ("https://dblp.org/rec/journals/cacm/Codd70.html", (DBLP, "journals/cacm/Codd70")),
        ("https://dblp.org/rec/conf/nips/Author17.bib", (DBLP, "conf/nips/Author17")),
        (
            "https://dblp.uni-trier.de/rec/journals/cacm/Codd70",
            (DBLP, "journals/cacm/Codd70"),
        ),
        ("ACL:N19-1423", (ACL, "N19-1423")),
        # Legacy ids are upper-cased and modern ids lower-cased.
        ("ACL:n19-1423", (ACL, "N19-1423")),
        ("ACL:2023.ACL-long.1", (ACL, "2023.acl-long.1")),
        ("https://aclanthology.org/N19-1423/", (ACL, "N19-1423")),
        ("https://aclanthology.org/2023.acl-long.1.pdf", (ACL, "2023.acl-long.1")),
        ("https://www.aclweb.org/anthology/P17-1001", (ACL, "P17-1001")),
        ("IACR:0300/1234", (IACR, "0300/1234")),
        ("https://eprint.iacr.org/0300/1234", (IACR, "0300/1234")),
        ("https://eprint.iacr.org/0300/1234.pdf", (IACR, "0300/1234")),
    ],
)
def test_resolve_identifier_accepts_database_identifiers(
    value: str, expected: tuple[str, str]
) -> None:
    assert resolve_identifier(value) == expected


@pytest.mark.parametrize(
    "normalize,value",
    [
        (inspire.normalize_identifier, "not a texkey"),
        (inspire.normalize_identifier, "Euclid:300"),
        (dblp.normalize_identifier, "journals"),
        (dblp.normalize_identifier, "journals/cacm"),
        (acl_anthology.normalize_identifier, "N19"),
        (acl_anthology.normalize_identifier, "2023.acl-long"),
        (iacr.normalize_identifier, "1234"),
        (iacr.normalize_identifier, "300/1234"),
        (iacr.normalize_identifier, "not-an-id"),
    ],
)
def test_database_clients_reject_malformed_identifiers(normalize, value: str) -> None:
    with pytest.raises(ValueError, match="Malformed"):
        normalize(value)


# --- INSPIRE-HEP -----------------------------------------------------------


def test_inspire_requests_a_record_id_directly() -> None:
    assert inspire.request_url("451647") == (
        "https://inspirehep.net/api/literature/451647?format=bibtex"
    )
    assert inspire.record_url("451647") == "https://inspirehep.net/literature/451647"


def test_inspire_requests_a_texkey_through_a_search() -> None:
    assert inspire.request_url("Euclid:0300abc") == (
        "https://inspirehep.net/api/literature?q=texkeys%3AEuclid%3A0300abc&format=bibtex&size=1"
    )


def test_inspire_metadata_keeps_the_texkey_as_the_provider_key() -> None:
    metadata = inspire.fetch_metadata("451647", fetcher=lambda identifier: INSPIRE_BIBTEX)

    assert metadata.provider == "INSPIRE-HEP"
    assert metadata.provider_key == "Euclid:0300abc"
    assert metadata.fields["eprint"] == "hist-ph/0300001"
    assert metadata.fields["reportnumber"] == "ALEX-300-A1"
    assert metadata.fields["url"] == "https://inspirehep.net/literature/451647"
    assert metadata.identifier("inspire") == "451647"
    assert metadata.identifier("doi") == "10.5555/ancient.geometry.1"


def test_inspire_record_url_rejects_a_texkey() -> None:
    with pytest.raises(ValueError, match="record ids, not texkeys"):
        inspire.record_url("Euclid:0300abc")


def test_inspire_metadata_omits_a_search_url_for_a_texkey_lookup() -> None:
    metadata = inspire.fetch_metadata("Euclid:0300abc", fetcher=lambda identifier: INSPIRE_BIBTEX)

    assert "url" not in metadata.fields
    assert metadata.identifier("inspire") == "Euclid:0300abc"


def test_inspire_reports_an_empty_search_result() -> None:
    with pytest.raises(ProviderFetchError, match="no record"):
        inspire.fetch_metadata("Euclid:0300abc", fetcher=lambda identifier: "\n")


# --- DBLP ------------------------------------------------------------------


def test_dblp_requests_the_bibtex_record() -> None:
    assert dblp.request_url("journals/cacm/Codd70") == (
        "https://dblp.org/rec/journals/cacm/Codd70.bib"
    )
    assert dblp.record_url("journals/cacm/Codd70") == (
        "https://dblp.org/rec/journals/cacm/Codd70.html"
    )


def test_dblp_metadata_drops_service_bookkeeping_fields() -> None:
    metadata = dblp.fetch_metadata("journals/rag/Euclid300", fetcher=lambda identifier: DBLP_BIBTEX)

    assert metadata.provider == "DBLP"
    assert metadata.fields["doi"] == "10.5555/ancient.geometry.1"
    for dropped in dblp.DROPPED_FIELDS:
        assert dropped not in metadata.fields
        assert dropped not in metadata.field_expressions
    assert metadata.identifier("dblp") == "journals/rag/Euclid300"


def test_dblp_metadata_discards_its_own_unusable_citation_key() -> None:
    metadata = dblp.fetch_metadata("journals/rag/Euclid300", fetcher=lambda identifier: DBLP_BIBTEX)

    # "DBLP:journals/rag/Euclid300" is not usable as a citation key.
    assert metadata.provider_key is None


def test_prepare_imported_reference_generates_a_key_for_dblp() -> None:
    lib = parse_bib("")

    kind, entry = prepare_imported_reference(
        lib,
        "DBLP:journals/rag/Euclid300",
        key_source="provider",
        metadata_fetcher=lambda identifier: DBLP_BIBTEX,
    )

    # --key-source provider falls back to generation because DBLP's key is unusable.
    assert kind == DBLP
    assert entry.key == "EuclidRatios"
    assert not entry.key.startswith("DBLP:")


# --- ACL Anthology ---------------------------------------------------------


def test_acl_requests_the_anthology_bibtex() -> None:
    assert acl_anthology.request_url("2023.acl-long.1") == (
        "https://aclanthology.org/2023.acl-long.1.bib"
    )
    assert acl_anthology.record_url("N19-1423") == "https://aclanthology.org/N19-1423/"


def test_acl_metadata_keeps_venue_details_the_doi_record_omits() -> None:
    metadata = acl_anthology.fetch_metadata("N19-1423", fetcher=lambda identifier: ACL_BIBTEX)

    assert metadata.provider == "ACL Anthology"
    assert metadata.entry_type == "inproceedings"
    assert metadata.fields["editor"] == "Heath, Thomas"
    assert metadata.fields["address"] == "Alexandria"
    assert metadata.fields["booktitle"] == "Proceedings of the Alexandria Conference on Geometry"
    assert metadata.fields["url"] == "https://aclanthology.org/N19-1423/"
    assert metadata.provider_key == "euclid-300-ratios"
    assert metadata.identifier("acl") == "N19-1423"


# --- IACR ePrint Archive -----------------------------------------------------


def test_iacr_requests_the_landing_page() -> None:
    assert iacr.request_url("0300/1234") == "https://eprint.iacr.org/0300/1234"
    assert iacr.record_url("0300/1234") == "https://eprint.iacr.org/0300/1234"


def test_iacr_metadata_is_extracted_from_the_embedded_bibtex_block() -> None:
    metadata = iacr.fetch_metadata("0300/1234", fetcher=lambda identifier: IACR_PAGE)

    assert metadata.provider == "IACR ePrint Archive"
    assert metadata.entry_type == "misc"
    assert metadata.fields["title"] == "On the Ratios of Straight Lines"
    assert metadata.fields["author"] == "Euclid"
    assert metadata.fields["doi"] == "10.5555/ancient.geometry.1"
    assert metadata.fields["url"] == "https://eprint.iacr.org/0300/1234"
    assert metadata.identifier("iacr") == "0300/1234"
    assert metadata.identifier("doi") == "10.5555/ancient.geometry.1"


def test_iacr_metadata_discards_its_own_unusable_citation_key() -> None:
    metadata = iacr.fetch_metadata("0300/1234", fetcher=lambda identifier: IACR_PAGE)

    # "cryptoeprint:0300/1234" is service bookkeeping, not a citation-key convention.
    assert metadata.provider_key is None


def test_iacr_accepts_a_trailing_pdf_suffix() -> None:
    assert iacr.normalize_identifier("0300/1234.pdf") == "0300/1234"


def test_iacr_reports_a_page_with_no_embedded_bibtex() -> None:
    with pytest.raises(ProviderFetchError, match="no record"):
        iacr.fetch_metadata("0300/1234", fetcher=lambda identifier: "<html></html>")


def test_prepare_imported_reference_generates_a_key_for_iacr() -> None:
    lib = parse_bib("")

    kind, entry = prepare_imported_reference(
        lib,
        "IACR:0300/1234",
        key_source="provider",
        metadata_fetcher=lambda identifier: IACR_PAGE,
    )

    # --key-source provider falls back to generation because IACR's key is unusable.
    assert kind == IACR
    assert entry.key == "EuclidRatios"
    assert not entry.key.startswith("cryptoeprint")


# --- registry and duplicate detection --------------------------------------


@pytest.mark.parametrize(
    "kind,name,identifier,bibtex",
    [
        (INSPIRE, "INSPIRE-HEP", "451647", INSPIRE_BIBTEX),
        (DBLP, "DBLP", "journals/rag/Euclid300", DBLP_BIBTEX),
        (ACL, "ACL Anthology", "N19-1423", ACL_BIBTEX),
        (IACR, "IACR ePrint Archive", "0300/1234", IACR_PAGE),
    ],
)
def test_database_providers_are_registered(
    kind: str, name: str, identifier: str, bibtex: str
) -> None:
    provider = get_import_provider(kind)

    metadata = provider.load(identifier, "bibtex", lambda value: bibtex)

    assert provider.name == name
    assert metadata.identifier(kind) == identifier


@pytest.mark.parametrize(
    "identifier,bibtex",
    [
        ("INSPIRE:451647", INSPIRE_BIBTEX),
        ("DBLP:journals/rag/Euclid300", DBLP_BIBTEX),
        ("ACL:N19-1423", ACL_BIBTEX),
        ("IACR:0300/1234", IACR_PAGE),
    ],
)
def test_database_imports_detect_a_duplicate_by_doi(identifier: str, bibtex: str) -> None:
    lib = parse_bib("@article{Existing, doi = {10.5555/ancient.geometry.1}, title = {X}}\n")

    with pytest.raises(DuplicateReferenceError) as exc:
        prepare_imported_reference(lib, identifier, metadata_fetcher=lambda value: bibtex)

    assert exc.value.keys == ["Existing"]


def test_inspire_import_detects_a_duplicate_by_eprint() -> None:
    lib = parse_bib("@misc{Existing, eprint = {hist-ph/0300001}, archivePrefix = {arXiv}}\n")

    with pytest.raises(DuplicateReferenceError):
        prepare_imported_reference(
            lib, "INSPIRE:451647", metadata_fetcher=lambda value: INSPIRE_BIBTEX
        )
