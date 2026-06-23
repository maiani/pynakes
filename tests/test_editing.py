"""Unit tests for the surgical raw-text editing primitives.

These guard invariant #2: edits touch only the changed field/key, and an entry
without ``raw_content`` falls back to ``modified`` so the writer reconstructs it.
"""

from pynakes.editing import (
    append_delimited_field,
    normalize_raw_field_names,
    raw_field_names,
    remove_entry_field,
    remove_raw_field,
    rename_entry_field,
    rename_raw_field,
    set_entry_field,
    set_entry_type,
    set_raw_field,
    splice_into_text,
)
from pynakes.model import BibEntry

RAW = "@article{k,\n  title = {The {DNA} Helix},\n  year = {1953}\n}"
PAREN_RAW = "@article(k,\n  title = {Original},\n  year = 2024\n)"


class TestRawFieldEdits:
    def test_set_existing_brace_value_in_place(self) -> None:
        out = set_raw_field(RAW, "year", "1954")
        assert "year = {1954}" in out
        assert "title = {The {DNA} Helix}" in out  # untouched, nested braces intact

    def test_set_missing_field_inserts_before_close(self) -> None:
        out = set_raw_field(RAW, "doi", "10.1/x")
        assert "doi = {10.1/x}" in out
        assert out.rstrip().endswith("}")

    def test_set_field_handles_quoted_value(self) -> None:
        raw = '@article{k, title = "Quoted Title", year = {2020}}'
        out = set_raw_field(raw, "title", "New")
        assert "title = {New}" in out
        assert "year = {2020}" in out

    def test_set_field_handles_bare_word_value(self) -> None:
        raw = "@article{k, year = 2020, month = jan}"
        out = set_raw_field(raw, "year", "2021")
        assert "year = {2021}" in out
        assert "month = jan" in out

    def test_set_field_preserves_parenthesized_entry_delimiter(self) -> None:
        out = set_raw_field(PAREN_RAW, "doi", "10.1000/example")
        assert "doi = {10.1000/example}" in out
        assert out.rstrip().endswith(")")

    def test_set_field_without_close_brace_is_noop(self) -> None:
        assert set_raw_field("@article{k, year = {2020}", "doi", "x").startswith("@article")

    def test_remove_absent_field_is_noop(self) -> None:
        assert remove_raw_field(RAW, "doi") == RAW

    def test_rename_absent_field_is_noop(self) -> None:
        assert rename_raw_field(RAW, "doi", "url") == RAW

    def test_rename_keeps_value_and_position(self) -> None:
        out = rename_raw_field(RAW, "year", "date")
        assert "date = {1953}" in out
        assert "year" not in out

    def test_normalize_field_names_touches_only_top_level_assignments(self) -> None:
        raw = '@Article{k,\n  TITLE = {Keep "FIELD =" verbatim},\n  DOI = {10.1/x}\n}'
        normalized, changed = normalize_raw_field_names(raw)
        assert changed == 2
        assert "  title =" in normalized
        assert "  doi =" in normalized
        assert '"FIELD ="' in normalized
        assert raw_field_names(raw) == ["TITLE", "DOI"]


class TestSplice:
    def test_replaces_only_matched_block(self) -> None:
        text = "prefix\n" + RAW + "\nsuffix\n"
        edited = set_raw_field(RAW, "year", "2000")
        out = splice_into_text(text, [(RAW, edited)])
        assert out is not None
        assert "prefix" in out and "suffix" in out
        assert "year = {2000}" in out

    def test_missing_block_returns_none(self) -> None:
        assert splice_into_text("unrelated text", [("not present", "x")]) is None

    def test_noop_edit_is_skipped(self) -> None:
        assert splice_into_text("abc", [("abc", "abc")]) == "abc"


class TestEntryLevelSync:
    def test_edit_without_raw_content_marks_modified(self) -> None:
        entry = BibEntry(key="k", type="article", fields={"year": "2020"}, raw_content=None)
        assert set_entry_field(entry, "title", "T") is True
        assert entry.modified is True
        assert entry.fields["title"] == "T"

    def test_set_same_value_is_noop(self) -> None:
        entry = BibEntry(key="k", type="article", fields={"year": "2020"}, raw_content=RAW)
        assert set_entry_field(entry, "year", "2020") is False

    def test_parenthesized_entry_stays_surgical(self) -> None:
        entry = BibEntry(
            key="k",
            type="article",
            fields={"title": "Original", "year": "2024"},
            raw_content=PAREN_RAW,
        )
        assert set_entry_field(entry, "title", "Updated") is True
        assert entry.raw_content == "@article(k,\n  title = {Updated},\n  year = 2024\n)"

    def test_remove_and_rename_return_false_when_absent(self) -> None:
        entry = BibEntry(key="k", type="article", fields={"year": "2020"}, raw_content=RAW)
        assert remove_entry_field(entry, "doi") is False
        assert rename_entry_field(entry, "doi", "url") is False

    def test_set_entry_type_noop_when_unchanged(self) -> None:
        entry = BibEntry(key="k", type="article", fields={}, raw_content=RAW)
        assert set_entry_type(entry, "article") is False

    def test_append_delimited_dedupes(self) -> None:
        entry = BibEntry(key="k", type="article", fields={"keywords": "a, b"}, raw_content=None)
        assert append_delimited_field(entry, "keywords", "b", ",", ", ") is False
        assert append_delimited_field(entry, "keywords", "c", ",", ", ") is True
        assert entry.fields["keywords"] == "a, b, c"
