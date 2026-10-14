"""Bounded-read primitives: projection, truncation, and snapshot-checked pages."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pynakes.bounded import (
    CursorError,
    StaleCursorError,
    decode_cursor,
    encode_cursor,
    paginate,
    parse_field_selection,
    project_fields,
    request_digest,
    truncate_text,
)

SNAPSHOT = "a" * 64
FIELDS = {"Author": "Isaac Newton", "title": "Principia", "year": "1687"}


# --- truncation and projection ---------------------------------------------------


def test_truncation_returns_a_prefix_and_reports_the_cut() -> None:
    text, cut = truncate_text("Philosophiae", 5)

    assert text == "Philo"
    assert cut is not None and cut.to_dict() == {"length": 12, "returned": 5}


def test_a_value_within_the_limit_is_returned_whole() -> None:
    assert truncate_text("Opticks", 7) == ("Opticks", None)
    assert truncate_text("Opticks", None) == ("Opticks", None)


def test_projection_without_selection_keeps_every_field_in_source_order() -> None:
    projection = project_fields(FIELDS)

    assert list(projection.fields) == ["Author", "title", "year"]
    assert projection.missing == [] and projection.omitted == []


def test_projection_distinguishes_missing_from_omitted() -> None:
    projection = project_fields(FIELDS, ("author", "doi"))

    # The stored spelling is kept; the absent field is null and listed as missing.
    assert projection.fields == {"Author": "Isaac Newton", "doi": None}
    assert projection.missing == ["doi"]
    assert projection.omitted == ["title", "year"]


def test_projection_reports_every_truncated_value() -> None:
    projection = project_fields(FIELDS, None, 4)

    assert projection.fields == {"Author": "Isaa", "title": "Prin", "year": "1687"}
    assert set(projection.truncated) == {"Author", "title"}


def test_projection_rejects_a_negative_limit() -> None:
    with pytest.raises(ValueError):
        project_fields(FIELDS, None, -1)


def test_field_selection_splits_folds_and_deduplicates() -> None:
    assert parse_field_selection(None) is None
    assert parse_field_selection(["Title,year", "title", " doi "]) == ("title", "year", "doi")
    with pytest.raises(ValueError):
        parse_field_selection([" , "])


# --- cursors and pages -----------------------------------------------------------


def test_pages_cover_the_selection_exactly_once() -> None:
    items = list(range(7))
    request = request_digest(command="test", keys=items)
    seen: list[int] = []
    cursor = None
    while True:
        page, info = paginate(items, limit=3, cursor=cursor, snapshot=SNAPSHOT, request=request)
        seen += page
        if info.complete:
            break
        cursor = info.next_cursor

    assert seen == items
    assert info.to_dict() == {
        "offset": 6,
        "limit": 3,
        "returned": 1,
        "total": 7,
        "complete": True,
        "next_cursor": None,
    }


def test_no_limit_is_one_complete_page() -> None:
    page, info = paginate([1, 2], limit=None, cursor=None, snapshot=SNAPSHOT, request="r")

    assert page == [1, 2] and info.complete and info.total == 2


def test_limit_zero_only_counts() -> None:
    page, info = paginate([1, 2, 3], limit=0, cursor=None, snapshot=SNAPSHOT, request="r")

    assert page == [] and info.total == 3 and not info.complete
    assert decode_cursor(info.next_cursor, snapshot=SNAPSHOT, request="r") == 0


def test_a_cursor_from_another_snapshot_is_stale() -> None:
    cursor = encode_cursor(snapshot=SNAPSHOT, request="r", offset=2)

    with pytest.raises(StaleCursorError):
        paginate([1, 2, 3], limit=1, cursor=cursor, snapshot="b" * 64, request="r")


def test_a_cursor_from_another_request_is_refused() -> None:
    cursor = encode_cursor(snapshot=SNAPSHOT, request="r", offset=2)

    with pytest.raises(CursorError, match="different selection"):
        decode_cursor(cursor, snapshot=SNAPSHOT, request="other")


@pytest.mark.parametrize(
    "cursor",
    ["", "c2.abc", "c1.!!!", "c1.bnVsbA", "c1.eyJvIjotMSwiciI6InIiLCJzIjoiIn0"],
)
def test_malformed_cursors_are_refused(cursor: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(cursor, snapshot=None, request="r")


def test_a_cursor_past_the_end_reads_an_empty_complete_page() -> None:
    cursor = encode_cursor(snapshot=SNAPSHOT, request="r", offset=9)

    page, info = paginate([1], limit=2, cursor=cursor, snapshot=SNAPSHOT, request="r")

    assert page == [] and info.complete


def test_request_digests_ignore_argument_order_only() -> None:
    assert request_digest(a=1, b=[1, 2]) == request_digest(b=[1, 2], a=1)
    assert request_digest(a=1, b=[1, 2]) != request_digest(a=1, b=[2, 1])


def test_a_negative_limit_is_refused() -> None:
    with pytest.raises(ValueError):
        paginate([1], limit=-1, cursor=None, snapshot=None, request="r")


@given(size=st.integers(0, 40), limit=st.integers(1, 12))
def test_paging_reads_every_item_once_in_order(size: int, limit: int) -> None:
    items = list(range(size))
    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        page, info = paginate(items, limit=limit, cursor=cursor, snapshot=SNAPSHOT, request="r")
        seen += page
        pages += 1
        assert info.total == size and info.returned == len(page) <= limit
        if info.complete:
            break
        cursor = info.next_cursor

    assert seen == items
    assert pages == max(1, -(-size // limit))
