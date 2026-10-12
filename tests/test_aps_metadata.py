"""Tests for American Physical Society Harvest API metadata."""

from pynakes.providers.metadata import aps
from pynakes.providers.preferred_metadata import preferred_metadata_provider


def test_physical_review_b_prefers_aps_metadata() -> None:
    assert preferred_metadata_provider("Physical Review B") == "aps"
    assert aps.request_url("10.1103/q7zt-k2wx", "Physical Review B") == (
        "https://harvest.aps.org/v2/journals/articles/10.1103/q7zt-k2wx"
    )


def test_aps_metadata_preserves_article_id_and_page_count() -> None:
    metadata = aps.fetch_metadata(
        "10.1103/q7zt-k2wx",
        "Physical Review B",
        fetcher=lambda _doi: {
            "title": {"value": "Experimental researches in electricity"},
            "authors": [{"surname": "Faraday", "firstname": "Michael"}],
            "journal": {"abbreviatedName": "Phys. Rev. B"},
            "volume": {"number": "38"},
            "issue": {"number": "8"},
            "pageStart": "L999001",
            "numPages": 7,
            "date": "1931-08-25",
            "identifiers": {"doi": "10.1103/q7zt-k2wx"},
        },
    )

    assert metadata is not None
    assert metadata.fields["number"] == "8"
    assert metadata.fields["pages"] == "L999001"
    assert metadata.fields["numpages"] == "7"
    assert metadata.fields["month"] == "aug"
    assert metadata.fields["author"] == "Faraday, Michael"


def test_aps_metadata_strips_inline_mathml_without_losing_text() -> None:
    metadata = aps.fetch_metadata(
        "10.1103/example",
        "Physical Review Letters",
        fetcher=lambda _doi: {
            "title": {
                "value": ("On the magnetism of <math><mrow><mi>Fe</mi><mi>O</mi></mrow></math>")
            },
            "identifiers": {"doi": "10.1103/example"},
        },
    )

    assert metadata is not None
    assert metadata.fields["title"] == "On the magnetism of FeO"


def test_harvest_uses_institutional_access_without_token(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_json(_url: str, **kwargs: object) -> dict:
        captured.update(kwargs)
        return {"data": {"id": "10.1103/example"}}

    monkeypatch.delenv(aps.TOKEN_ENV_VAR, raising=False)
    monkeypatch.setattr(aps, "fetch_json", fake_fetch_json)

    article = aps.fetch_article("10.1103/example", "Physical Review B")

    assert article == {"id": "10.1103/example"}
    assert captured["headers"] == {"Accept": aps.ARTICLE_JSON}


def test_harvest_reads_optional_bearer_token(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_json(_url: str, **kwargs: object) -> dict:
        captured.update(kwargs)
        return {"data": {"id": "10.1103/example"}}

    monkeypatch.setenv(aps.TOKEN_ENV_VAR, "test-token")
    monkeypatch.setattr(aps, "fetch_json", fake_fetch_json)

    aps.fetch_article("10.1103/example", "Physical Review B")

    assert captured["headers"] == {
        "Accept": aps.ARTICLE_JSON,
        "Authorization": "Bearer test-token",
    }
