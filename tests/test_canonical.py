"""Golden tests for canonical layout formatting.

Tests cover:
- Basic entry formatting with canonical layout
- Field ordering per entry type
- Trailing commas and blank lines between entries
- Comments, @string, @preamble preservation
- Deterministic and idempotent output
- BibTeX/BibLaTeX-aware wrapping (no brace changes)
- Malformed input handling
"""

from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.canonical import CanonicalLayout, format_entry, write_bib_canonical
from pynakes.engine import Bibliography
from pynakes.model import BibEntry, BibFile
from pynakes.normalize import NormalizeOptions

FIXTURE_BIBS = sorted((Path(__file__).parent / "fixtures").rglob("*.bib"))

# ---------------------------------------------------------------------------
# format_entry tests
# ---------------------------------------------------------------------------


class TestFormatEntry:
    """Tests for canonical entry formatting."""

    def test_article_basic(self) -> None:
        entry = BibEntry(
            key="Smith2020Big",
            type="article",
            fields={
                "author": "Smith, John and Doe, Jane",
                "title": "A Big Discovery",
                "journal": "Nature",
                "year": "2020",
                "volume": "580",
                "pages": "1--5",
            },
        )
        result = format_entry(entry)
        assert "@article{Smith2020Big," in result
        assert "  author = {Smith, John and Doe, Jane}," in result
        assert "  title = {A Big Discovery}," in result
        assert "  journal = {Nature}," in result
        assert "  year = {2020}," in result
        assert "  volume = {580}," in result
        assert "  pages = {1--5}," in result
        assert result.endswith("}")

    def test_article_trailing_comma_disabled(self) -> None:
        entry = BibEntry(
            key="Smith2020",
            type="article",
            fields={"author": "Smith", "title": "Test"},
        )
        layout = CanonicalLayout(trailing_comma=False)
        result = format_entry(entry, layout)
        # Last field should not have trailing comma
        lines = result.split("\n")
        last_field_line = lines[-2]  # Before closing brace
        assert not last_field_line.endswith(",")

    def test_tabular_alignment(self) -> None:
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={"a": "1", "bb": "2", "ccc": "3"},
        )
        layout = CanonicalLayout(tabular=True)
        result = format_entry(entry, layout)
        # Fields should be aligned on =
        assert "a   = {1}," in result
        assert "bb  = {2}," in result
        assert "ccc = {3}," in result

    @pytest.mark.parametrize("indent", ["\t", "    "])
    def test_custom_indent_keeps_one_field_per_line(self, indent: str) -> None:
        entry = BibEntry(key="Test", type="article", fields={"title": "T", "year": "2020"})
        result = format_entry(entry, CanonicalLayout(indent=indent))
        assert result.splitlines()[1:] == [
            f"{indent}title = {{T}},",
            f"{indent}year = {{2020}},",
            "}",
        ]

    def test_structural_fields_first(self) -> None:
        entry = BibEntry(
            key="Child2020",
            type="inproceedings",
            fields={
                "title": "Child Paper",
                "crossref": "Parent2020",
                "author": "Author",
                "year": "2020",
            },
        )
        result = format_entry(entry)
        lines = result.split("\n")
        # crossref should be among the first fields
        field_lines = [line.strip() for line in lines[1:-1]]
        crossref_idx = next(i for i, fl in enumerate(field_lines) if "crossref" in fl)
        assert crossref_idx < 3  # Should be early

    def test_field_ordering_article(self) -> None:
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={
                "pages": "1--10",
                "author": "Author",
                "year": "2020",
                "title": "Title",
                "journal": "Journal",
            },
        )
        result = format_entry(entry)
        lines = result.split("\n")
        field_lines = [line.strip() for line in lines[1:-1]]
        field_names = [fl.split("=")[0].strip() for fl in field_lines]
        # Should be in canonical order: author, title, journal, year, pages
        assert field_names == ["author", "title", "journal", "year", "pages"]

    def test_custom_fields_appended(self) -> None:
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={
                "author": "Author",
                "title": "Title",
                "customfield": "value",
            },
        )
        result = format_entry(entry)
        lines = result.split("\n")
        field_lines = [line.strip() for line in lines[1:-1]]
        field_names = [fl.split("=")[0].strip() for fl in field_lines]
        # customfield should come after known fields
        assert field_names[-1] == "customfield"


# ---------------------------------------------------------------------------
# write_bib_canonical tests
# ---------------------------------------------------------------------------


class TestWriteBibCanonical:
    """Tests for canonical whole-file formatting."""

    def test_basic_entry(self) -> None:
        lib = BibFile(
            entries=[
                BibEntry(
                    key="Test2020",
                    type="article",
                    fields={"author": "Author", "title": "Title"},
                ),
            ]
        )
        result = write_bib_canonical(lib)
        assert "@article{Test2020," in result
        assert "  author = {Author}," in result
        assert "  title = {Title}," in result

    def test_multiple_entries_blank_lines(self) -> None:
        lib = BibFile(
            entries=[
                BibEntry(key="A2020", type="article", fields={"title": "A"}),
                BibEntry(key="B2020", type="article", fields={"title": "B"}),
            ]
        )
        result = write_bib_canonical(lib)
        # Should have blank line between entries
        assert "\n\n@article{B2020," in result

    def test_multiple_entries_no_blank_lines(self) -> None:
        lib = BibFile(
            entries=[
                BibEntry(key="A2020", type="article", fields={"title": "A"}),
                BibEntry(key="B2020", type="article", fields={"title": "B"}),
            ]
        )
        layout = CanonicalLayout(blank_line_entries=False)
        result = write_bib_canonical(lib, layout)
        # Should NOT have blank line between entries
        assert "\n\n" not in result

    def test_strings_sorted_alphabetically(self) -> None:
        lib = BibFile(
            entries=[],
            strings={"zebra": "Zebra", "alpha": "Alpha", "middle": "Middle"},
            raw_strings=[
                "@string{zebra = {Zebra}}",
                "@string{alpha = {Alpha}}",
                "@string{middle = {Middle}}",
            ],
        )
        result = write_bib_canonical(lib)
        lines = result.split("\n")
        string_lines = [line for line in lines if line.startswith("@string{")]
        assert len(string_lines) == 3
        # Should be alphabetical
        assert "@string{alpha" in string_lines[0]
        assert "@string{middle" in string_lines[1]
        assert "@string{zebra" in string_lines[2]

    def test_duplicate_string_declarations_are_not_collapsed(self) -> None:
        source = '@string{x = "First"}\n@string{x = "Second"}\n@article{A, title=x}\n'
        result = write_bib_canonical(parse_bib(source))
        assert result.count("@string{x") == 2
        assert '@string{x = "First"}' in result
        assert '@string{x = "Second"}' in result
        assert write_bib_canonical(parse_bib(result)) == result

    def test_unparsed_source_text_is_preserved_and_idempotent(self) -> None:
        source = (
            "leading source text\n"
            "@string{broken}\n"
            "@article{A, title={A}}\n"
            "between-entry source text\n"
            "@article{B, title={B}}\n"
        )
        result = write_bib_canonical(parse_bib(source))
        assert "leading source text" in result
        assert "@string{broken}" in result
        assert "between-entry source text" in result
        assert write_bib_canonical(parse_bib(result)) == result

    def test_pynakes_meta_first(self) -> None:
        lib = BibFile(
            entries=[BibEntry(key="Test", type="article", fields={})],
            raw_comments=[
                "@comment{jabref-meta: databaseType:bibtex;}",
                "@comment{pynakes-meta: dialect: biblatex}",
            ],
        )
        result = write_bib_canonical(lib)
        pynakes_idx = result.find("pynakes-meta")
        jabref_idx = result.find("jabref-meta")
        assert pynakes_idx < jabref_idx

    def test_deterministic_output(self) -> None:
        lib = BibFile(
            entries=[
                BibEntry(key="B2020", type="article", fields={"title": "B"}),
                BibEntry(key="A2020", type="article", fields={"title": "A"}),
            ]
        )
        result1 = write_bib_canonical(lib)
        result2 = write_bib_canonical(lib)
        assert result1 == result2

    def test_idempotent(self) -> None:
        lib = BibFile(
            entries=[
                BibEntry(key="Test2020", type="article", fields={"title": "Test"}),
            ]
        )
        result1 = write_bib_canonical(lib)
        # Parse the canonical output and re-format
        lib2 = parse_bib(result1)
        result2 = write_bib_canonical(lib2)
        assert result1 == result2

    def test_preserves_brace_grouping(self) -> None:
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={"title": "The {DNA} Helix"},
        )
        lib = BibFile(entries=[entry])
        result = write_bib_canonical(lib)
        assert "{DNA}" in result

    def test_empty_library(self) -> None:
        lib = BibFile(entries=[])
        result = write_bib_canonical(lib)
        # Should be empty or just whitespace
        assert result.strip() == "" or result.strip() == ""

    def test_line_ending_preserved(self) -> None:
        lib = BibFile(
            entries=[BibEntry(key="Test", type="article", fields={})],
            line_ending="\r\n",
        )
        result = write_bib_canonical(lib)
        assert "\r\n" in result
        assert "\n" not in result.replace("\r\n", "")

    def test_source_value_expressions_and_trailing_text_are_preserved(self) -> None:
        source = (
            '@string{aps = "Physical Review"}\n\n'
            '@article{A, journal = aps # " Letters", month = jan, title = "Quoted"}\n'
            "trailing text"
        )
        result = write_bib_canonical(parse_bib(source))
        assert 'journal = aps # " Letters",' in result
        assert "month = jan," in result
        assert 'title = "Quoted",' in result
        assert result.rstrip().endswith("trailing text")
        assert write_bib_canonical(parse_bib(result)) == result

    def test_engine_canonical_render_composes_with_metadata_consolidation(self) -> None:
        coll = Bibliography.from_text(
            "@comment{jabref-meta: keypatterndefault:[auth][year];}\n"
            "@article{A, author={Doe, Jane}, year={2020}}\n"
        )
        coll.normalize(
            NormalizeOptions(
                protect_titles=False,
                author_style="none",
                normalize_dois=False,
                identifier_case=False,
                sort_by=["original"],
            )
        )
        coll.format()
        output = coll.preview()
        assert output.count("@comment{pynakes-meta:") == 1
        assert "key-pattern: [auth][year]" in output

    def test_preamble_preserved(self) -> None:
        lib = BibFile(
            entries=[],
            preamble=['@preamble{"some preamble"}'],
        )
        result = write_bib_canonical(lib)
        assert "@preamble" in result


@pytest.mark.parametrize("path", FIXTURE_BIBS, ids=lambda path: path.name)
def test_every_fixture_is_semantics_preserving_and_idempotent(path: Path) -> None:
    original = parse_bib(path.read_text())
    formatted = write_bib_canonical(original)
    reparsed = parse_bib(formatted)
    before = [(entry.key, entry.type, entry.fields) for entry in original.entries.values()]
    after = [(entry.key, entry.type, entry.fields) for entry in reparsed.entries.values()]
    assert after == before
    assert write_bib_canonical(reparsed) == formatted


@pytest.mark.parametrize(
    "layout",
    [
        CanonicalLayout(indent="\t"),
        CanonicalLayout(indent="    "),
        CanonicalLayout(tabular=True),
        CanonicalLayout(trailing_comma=False),
        CanonicalLayout(blank_line_entries=False),
        CanonicalLayout(sort_fields=False),
    ],
)
def test_every_layout_knob_is_idempotent(layout: CanonicalLayout) -> None:
    source = '@article{A, year={2020}, title="Quoted", month=jan}\n'
    once = write_bib_canonical(parse_bib(source), layout)
    assert write_bib_canonical(parse_bib(once), layout) == once
