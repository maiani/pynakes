"""Import coverage for repository, preprint, and working-paper providers."""

from __future__ import annotations

import json

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.importer import (
    DuplicateReferenceError,
    existing_keys_for_identifier,
    prepare_imported_reference,
    resolve_identifier,
)
from pynakes.providers._http import ProviderFetchError
from pynakes.providers.records import ReferenceMetadata
from pynakes.providers.registry import IMPORT_PROVIDERS
from pynakes.providers.repositories import (
    biorxiv,
    chemrxiv,
    europe_pmc,
    hal,
    nber,
    osf,
    pubmed,
    research_square,
    ssrn,
    zenodo,
)

CITATION_HTML = """<!doctype html>
<html><head>
<meta name="citation_title" content="On Computable Numbers">
<meta name="citation_author" content="Alan Turing">
<meta name="citation_publication_date" content="1936-11-12">
<meta name="citation_doi" content="10.5555/archive.1">
<meta name="citation_abstract" content="A study of computable numbers.">
</head></html>
"""

SSRN_BIBTEX = """@techreport{Turing1936,
  author = {Alan Turing},
  title = {On Computable Numbers},
  year = {1936},
  doi = {10.2139/ssrn.123456}
}
"""


@pytest.mark.parametrize(
    "value,expected",
    [
        ("PMID:12345", ("pmid", "12345")),
        ("PMCID:12345", ("pmcid", "PMC12345")),
        ("EPMC:MED:12345", ("europe_pmc", "MED:12345")),
        ("SSRN:123456", ("ssrn", "123456")),
        ("NBER:w12345", ("nber", "w12345")),
        ("bioRxiv:10.1101/2020.01.02.123456", ("biorxiv", "10.1101/2020.01.02.123456")),
        ("medRxiv:10.1101/2020.01.02.123456", ("medrxiv", "10.1101/2020.01.02.123456")),
        ("Zenodo:123456", ("zenodo", "123456")),
        ("OSF:abc12", ("osf", "abc12")),
        ("HAL:hal-01234567v2", ("hal", "hal-01234567")),
        ("ChemRxiv:abc-123", ("chemrxiv", "abc-123")),
        ("ResearchSquare:rs-12345/v2", ("research_square", "rs-12345")),
        ("https://pubmed.ncbi.nlm.nih.gov/12345/", ("pmid", "12345")),
        (
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/",
            ("pmcid", "PMC12345"),
        ),
        ("https://europepmc.org/article/MED/12345", ("europe_pmc", "MED:12345")),
        (
            "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=123456",
            ("ssrn", "123456"),
        ),
        ("https://www.nber.org/papers/w12345", ("nber", "w12345")),
        (
            "https://www.biorxiv.org/content/10.1101/2020.01.02.123456v3.full.pdf",
            ("biorxiv", "10.1101/2020.01.02.123456"),
        ),
        (
            "https://www.medrxiv.org/content/10.1101/2020.01.02.123456v1",
            ("medrxiv", "10.1101/2020.01.02.123456"),
        ),
        ("https://zenodo.org/records/123456", ("zenodo", "123456")),
        ("https://osf.io/preprints/socarxiv/abc12/", ("osf", "abc12")),
        ("https://osf.io/preprints/osf/abc12_v2/", ("osf", "abc12_v2")),
        ("https://hal.science/hal-01234567v2", ("hal", "hal-01234567")),
        (
            "https://chemrxiv.org/engage/chemrxiv/article-details/abc-123",
            ("chemrxiv", "abc-123"),
        ),
        (
            "https://www.researchsquare.com/article/rs-12345/v2",
            ("research_square", "rs-12345"),
        ),
        # RFCs have a deterministic, unpadded DOI: 10.17487/rfc<number>. A padded
        # form is only a 301 alias and does not resolve at all for the lowest
        # RFC numbers, so the low numbers below are the important regression case.
        ("RFC:791", ("doi", "10.17487/rfc791")),
        ("RFC:20", ("doi", "10.17487/rfc20")),
        ("RFC:9110", ("doi", "10.17487/rfc9110")),
        ("rfc791", ("doi", "10.17487/rfc791")),
        ("RFC 791", ("doi", "10.17487/rfc791")),
        ("RFC-791", ("doi", "10.17487/rfc791")),
        ("rfc20", ("doi", "10.17487/rfc20")),
        (
            "https://datatracker.ietf.org/doc/rfc9110/",
            ("doi", "10.17487/rfc9110"),
        ),
        (
            "https://datatracker.ietf.org/doc/html/rfc9110",
            ("doi", "10.17487/rfc9110"),
        ),
        (
            "https://datatracker.ietf.org/doc/rfc791/",
            ("doi", "10.17487/rfc791"),
        ),
        ("https://www.rfc-editor.org/info/rfc9110", ("doi", "10.17487/rfc9110")),
        ("https://www.rfc-editor.org/rfc/rfc9110", ("doi", "10.17487/rfc9110")),
        ("https://www.rfc-editor.org/rfc/rfc9110.txt", ("doi", "10.17487/rfc9110")),
        ("https://www.rfc-editor.org/rfc/rfc9110.html", ("doi", "10.17487/rfc9110")),
        ("https://www.rfc-editor.org/info/rfc791", ("doi", "10.17487/rfc791")),
        ("https://tools.ietf.org/html/rfc7231", ("doi", "10.17487/rfc7231")),
        # IACR ePrint ids are the community's canonical identifier, not a DOI.
        ("IACR:2023/1234", ("iacr", "2023/1234")),
        ("https://eprint.iacr.org/2023/1234", ("iacr", "2023/1234")),
        ("https://eprint.iacr.org/2023/1234.pdf", ("iacr", "2023/1234")),
    ],
)
def test_repository_identifier_resolution(value: str, expected: tuple[str, str]) -> None:
    assert resolve_identifier(value) == expected


@pytest.mark.parametrize("rfc_number,doi", [("20", "10.17487/rfc20"), ("791", "10.17487/rfc791")])
def test_rfc_doi_is_not_zero_padded(rfc_number: str, doi: str) -> None:
    """A padded DOI (``10.17487/RFC0020``) is only a 301 alias and, for the
    lowest RFC numbers, does not resolve as a DOI at all — so a naive
    zero-padding implementation would silently break these two cases."""
    assert resolve_identifier(f"RFC:{rfc_number}") == ("doi", doi)
    assert resolve_identifier(f"rfc{rfc_number}") == ("doi", doi)
    # A user-supplied padded number is still accepted, but always normalized
    # to the unpadded canonical form.
    assert resolve_identifier(f"RFC:{rfc_number.zfill(4)}") == ("doi", doi)


PUBMED_XML = """<PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>12345</PMID><Article>
<ArticleTitle>Analytical Engines</ArticleTitle>
<Abstract><AbstractText>A general engine.</AbstractText></Abstract>
<AuthorList><Author><ForeName>Ada</ForeName><LastName>Lovelace</LastName></Author></AuthorList>
<Journal><Title>Historical Computing</Title><JournalIssue>
<PubDate><Year>1843</Year><Month>01</Month></PubDate><Volume>1</Volume><Issue>2</Issue>
</JournalIssue></Journal><Pagination><MedlinePgn>1-10</MedlinePgn></Pagination>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.5555/engine</ArticleId>
<ArticleId IdType="pmc">PMC67890</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""

PMC_XML = """<pmc-articleset><article><front>
<journal-meta><journal-title-group><journal-title>Historical Computing</journal-title>
</journal-title-group></journal-meta><article-meta>
<article-id pub-id-type="pmc">PMC67890</article-id>
<article-id pub-id-type="pmid">12345</article-id>
<article-id pub-id-type="doi">10.5555/engine</article-id>
<title-group><article-title>Analytical Engines</article-title></title-group>
<contrib-group><contrib contrib-type="author"><name><surname>Lovelace</surname>
<given-names>Ada</given-names></name></contrib></contrib-group>
<pub-date pub-type="epub"><year>1843</year><month>01</month><day>01</day></pub-date>
<abstract><p>A general engine.</p></abstract>
</article-meta></front></article></pmc-articleset>"""


def test_pubmed_and_pmc_xml_parsers() -> None:
    pmid = pubmed.parse_xml(PUBMED_XML, "12345", kind="pmid", dialect="bibtex")
    assert pmid.fields["author"] == "Ada Lovelace"
    assert pmid.fields["journal"] == "Historical Computing"
    assert pmid.fields["doi"] == "10.5555/engine"
    assert pmid.fields["pmcid"] == "PMC67890"

    pmcid = pubmed.parse_xml(PMC_XML, "PMC67890", kind="pmcid", dialect="biblatex")
    assert pmcid.fields["pmid"] == "12345"
    assert pmcid.fields["date"] == "1843-01-01"
    assert pmcid.identifiers["doi"] == "10.5555/engine"


def test_europe_pmc_parser() -> None:
    payload = {
        "result": {
            "id": "12345",
            "source": "MED",
            "title": "Analytical Engines",
            "authorList": {"author": [{"firstName": "Ada", "lastName": "Lovelace"}]},
            "firstPublicationDate": "1843-01-01",
            "journalInfo": {
                "volume": "1",
                "journal": {"title": "Historical Computing"},
            },
            "abstractText": "A general engine.",
            "doi": "10.5555/engine",
            "pmid": "12345",
            "pmcid": "PMC67890",
        }
    }
    metadata = europe_pmc.parse_json(json.dumps(payload), "MED:12345", dialect="bibtex")
    assert metadata.fields["author"] == "Ada Lovelace"
    assert metadata.fields["pmid"] == "12345"
    assert metadata.fields["year"] == "1843"
    assert metadata.fields["journal"] == "Historical Computing"


@pytest.mark.parametrize("server", ["biorxiv", "medrxiv"])
def test_biorxiv_api_parser(server: str) -> None:
    payload = {
        "collection": [
            {
                "doi": "10.1101/2020.01.02.123456",
                "title": "A Preprint",
                "authors": "Ada Lovelace; Alan Turing",
                "date": "2020-01-02",
                "abstract": "A useful preprint.",
                "category": "scientific communication",
            }
        ]
    }
    metadata = biorxiv.parse_json(
        json.dumps(payload), "10.1101/2020.01.02.123456", server=server, dialect="bibtex"
    )
    assert metadata.fields["author"] == "Ada Lovelace and Alan Turing"
    assert metadata.fields["doi"] == "10.1101/2020.01.02.123456"
    assert metadata.identifiers[server] == "10.1101/2020.01.02.123456"


def test_biorxiv_falls_back_to_doi_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        biorxiv,
        "fetch_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProviderFetchError("unavailable")),
    )
    monkeypatch.setattr(
        biorxiv.doi_provider,
        "fetch_metadata",
        lambda doi: ReferenceMetadata(
            provider="doi.org",
            entry_type="article",
            fields={
                "author": "Ada Lovelace",
                "title": "A Preprint",
                "year": "2020",
                "doi": doi,
            },
            identifiers={"doi": doi},
        ),
    )
    metadata = biorxiv.fetch_metadata(
        "10.1101/2020.01.02.123456", server="biorxiv", dialect="bibtex"
    )
    assert metadata.provider == "biorxiv"
    assert metadata.fields["archivePrefix"] == "biorxiv"
    assert metadata.identifiers["biorxiv"] == "10.1101/2020.01.02.123456"


def test_zenodo_parser() -> None:
    payload = {
        "metadata": {
            "title": "A Dataset",
            "creators": [{"name": "Lovelace, Ada"}],
            "publication_date": "1843-01-01",
            "description": "<p>Tables.</p>",
            "doi": "10.5281/zenodo.123456",
            "resource_type": {"title": "Dataset"},
        }
    }
    metadata = zenodo.parse_json(json.dumps(payload), "123456", dialect="bibtex")
    assert metadata.fields["author"] == "Lovelace, Ada"
    assert metadata.fields["type"] == "Dataset"
    assert metadata.fields["zenodo"] == "123456"


def test_osf_parser() -> None:
    payload = {
        "data": {
            "attributes": {
                "title": "A Registered Preprint",
                "authors": [{"given": "Ada", "family": "Lovelace"}],
                "date_published": "1843-01-01",
                "description": "A general engine.",
                "doi": "10.5555/osf",
            },
            "links": {"html": "https://osf.io/preprints/abc12/"},
        }
    }
    metadata = osf.parse_json(json.dumps(payload), "abc12", dialect="biblatex")
    assert metadata.fields["author"] == "Ada Lovelace"
    assert metadata.fields["date"] == "1843-01-01"
    assert metadata.fields["osf"] == "abc12"


def test_osf_embedded_bibliographic_contributors_and_doi_link() -> None:
    contributors = {
        "data": [
            {
                "embeds": {
                    "users": {
                        "data": {
                            "attributes": {
                                "full_name": "Ada Lovelace",
                                "given_name": "Ada",
                                "family_name": "Lovelace",
                            }
                        }
                    }
                }
            }
        ]
    }
    preprint = {
        "data": {
            "attributes": {
                "title": "A Registered Preprint",
                "date_published": "1843-01-01",
                "description": "A general engine.",
            },
            "links": {
                "html": "https://osf.io/preprints/abc12_v1/",
                "preprint_doi": "https://doi.org/10.31234/osf.io/abc12_v1",
            },
        }
    }
    authors = osf.parse_contributors(json.dumps(contributors))
    metadata = osf.parse_json(
        json.dumps(preprint), "abc12_v1", dialect="bibtex", contributors=authors
    )
    assert metadata.fields["author"] == "Ada Lovelace"
    assert metadata.fields["doi"] == "10.31234/osf.io/abc12_v1"


def test_hal_parser() -> None:
    payload = {
        "response": {
            "docs": [
                {
                    "title_s": ["A Repository Paper"],
                    "authFullName_s": ["Ada Lovelace"],
                    "producedDate_s": "1843-01-01",
                    "abstract_s": ["A general engine."],
                    "doiId_s": "10.5555/hal",
                    "uri_s": "https://hal.science/hal-01234567",
                }
            ]
        }
    }
    metadata = hal.parse_json(json.dumps(payload), "hal-01234567", dialect="bibtex")
    assert metadata.fields["title"] == "A Repository Paper"
    assert metadata.fields["halid"] == "hal-01234567"
    assert metadata.fields["doi"] == "10.5555/hal"


@pytest.mark.parametrize(
    "module,identifier,field",
    [
        (nber, "w12345", "number"),
        (research_square, "rs-12345", "researchsquare"),
    ],
)
def test_landing_page_providers(module, identifier: str, field: str) -> None:
    metadata = module.fetch_metadata(
        identifier, dialect="bibtex", fetcher=lambda _identifier: CITATION_HTML
    )
    assert metadata.fields["title"] == "On Computable Numbers"
    assert metadata.fields["author"] == "Alan Turing"
    assert metadata.fields["doi"] == "10.5555/archive.1"
    assert metadata.fields[field] == identifier


def test_ssrn_uses_canonical_doi_metadata() -> None:
    metadata = ssrn.fetch_metadata(
        "123456", dialect="bibtex", fetcher=lambda _identifier: SSRN_BIBTEX
    )
    assert metadata.fields["ssrn"] == "123456"
    assert metadata.fields["doi"] == "10.2139/ssrn.123456"
    assert metadata.identifiers == {
        "doi": "10.2139/ssrn.123456",
        "ssrn": "123456",
    }


def test_chemrxiv_public_api_parser() -> None:
    payload = {
        "id": "abc-123",
        "doi": "10.26434/chemrxiv-example-v1",
        "title": "A Chemical Preprint",
        "abstract": "A general chemical engine.",
        "authors": [{"firstName": "Ada", "lastName": "Lovelace"}],
        "publishedDate": "1843-01-01T12:00:00Z",
        "contentType": {"name": "Working Paper"},
        "categories": [{"name": "Chemical Engineering"}],
    }
    metadata = chemrxiv.parse_json(json.dumps(payload), "abc-123", dialect="bibtex")
    assert metadata.fields["author"] == "Ada Lovelace"
    assert metadata.fields["doi"] == "10.26434/chemrxiv-example-v1"
    assert metadata.fields["type"] == "Working Paper"
    assert metadata.fields["chemrxiv"] == "abc-123"


def test_nber_slash_date_is_normalized() -> None:
    metadata = nber.fetch_metadata(
        "w12345",
        dialect="bibtex",
        fetcher=lambda _identifier: CITATION_HTML.replace("1936-11-12", "1936/11/12"),
    )
    assert metadata.fields["year"] == "1936"
    assert metadata.fields["month"] == "nov"


def test_generic_dispatch_and_cross_identifier_duplicate_detection() -> None:
    kind, entry = prepare_imported_reference(
        parse_bib(""),
        "SSRN:123456",
        metadata_fetcher=lambda _identifier: SSRN_BIBTEX,
    )
    assert kind == "ssrn"
    assert entry.key == "Turing1936Computable"

    library = parse_bib("@article{Existing, doi = {10.2139/ssrn.123456}}\n")
    with pytest.raises(DuplicateReferenceError) as exc:
        prepare_imported_reference(
            library,
            "SSRN:123456",
            metadata_fetcher=lambda _identifier: SSRN_BIBTEX,
        )
    assert exc.value.keys == ["Existing"]


def test_generic_identifier_duplicate_detection_before_fetch() -> None:
    library = parse_bib("@misc{Existing, zenodo = {123456}}\n")
    assert existing_keys_for_identifier(library, "zenodo", "123456") == ["Existing"]
    with pytest.raises(DuplicateReferenceError):
        prepare_imported_reference(
            library,
            "Zenodo:123456",
            metadata_fetcher=lambda _identifier: pytest.fail("must not fetch"),
        )


def test_all_major_repository_providers_are_registered() -> None:
    assert {
        "pmid",
        "pmcid",
        "europe_pmc",
        "ssrn",
        "nber",
        "biorxiv",
        "medrxiv",
        "zenodo",
        "osf",
        "hal",
        "chemrxiv",
        "research_square",
    } <= IMPORT_PROVIDERS.keys()


@pytest.mark.parametrize(
    "normalizer",
    [
        lambda: pubmed.canonical_identifier("not-a-number", kind="pmid"),
        lambda: pubmed.canonical_identifier("PMCbad", kind="pmcid"),
        lambda: europe_pmc.normalize_identifier("missing-source"),
        lambda: ssrn.normalize_identifier("abc"),
        lambda: nber.normalize_identifier("12345"),
        lambda: zenodo.normalize_identifier("abc"),
        lambda: osf.normalize_identifier("bad/id"),
        lambda: hal.normalize_identifier("12345"),
        lambda: chemrxiv.normalize_identifier("bad/id"),
        lambda: research_square.normalize_identifier("12345"),
    ],
)
def test_repository_normalizers_reject_malformed_identifiers(normalizer) -> None:
    with pytest.raises(ValueError):
        normalizer()


@pytest.mark.parametrize(
    "parser",
    [
        lambda: biorxiv.parse_json("{", "10.1101/example", server="biorxiv", dialect="bibtex"),
        lambda: europe_pmc.parse_json("{", "MED:1", dialect="bibtex"),
        lambda: zenodo.parse_json("{", "1", dialect="bibtex"),
        lambda: osf.parse_json("{", "abc12", dialect="bibtex"),
        lambda: osf.parse_contributors("{"),
        lambda: hal.parse_json("{", "hal-00000001", dialect="bibtex"),
        lambda: chemrxiv.parse_json("{", "abc123", dialect="bibtex"),
    ],
)
def test_repository_json_parsers_report_malformed_responses(parser) -> None:
    with pytest.raises(ProviderFetchError):
        parser()
