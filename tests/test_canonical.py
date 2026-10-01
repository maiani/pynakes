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
from pynakes.bibtex_writer import write_bib
from pynakes.canonical import (
    CanonicalLayout,
    FormatLintError,
    format_entry,
    format_selected_entries,
    layout_from_metadata,
    write_bib_canonical,
)
from pynakes.engine import Bibliography
from pynakes.group_tree import library_group_tree
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

    def test_equals_alignment(self) -> None:
        entry = BibEntry(
            key="Test2020",
            type="article",
            fields={"a": "1", "bb": "2", "ccc": "3"},
        )
        layout = CanonicalLayout(alignment="equals")
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

    def test_alphabetical_field_policy_keeps_structural_fields_first(self) -> None:
        entry = BibEntry(
            key="Child",
            type="misc",
            fields={"zeta": "Z", "crossref": "Parent", "alpha": "A"},
        )
        result = format_entry(entry, CanonicalLayout(field_order="alphabetical"))
        field_names = [line.strip().split()[0] for line in result.splitlines()[1:-1]]
        assert field_names == ["crossref", "alpha", "zeta"]

    @pytest.mark.parametrize("mode", ["stable", "canonical"])
    def test_safe_value_wrapping_is_idempotent_and_preserves_expressions(self, mode: str) -> None:
        source = (
            '@misc{A, title="An authored\n'
            'line break with {Protected Terms} and $E = mc^2$ that needs safe wrapping", '
            "author={One, A. and Two, B. and Three, C. and Four, D.}, "
            'url={https://example.org/a/very/long/path}, month=jan, note=prefix # " suffix"}\n'
        )
        layout = CanonicalLayout(wrap_values=mode, line_width=50)
        once = write_bib_canonical(parse_bib(source), layout)
        assert write_bib_canonical(parse_bib(once), layout) == once
        assert '"An authored' in once
        assert "{Protected Terms}" in once
        assert "$E = mc^2$" in once
        assert "https://example.org/a/very/long/path" in once
        assert 'prefix # " suffix"' in once
        assert "month = jan" in once
        assert "\n            Three, C." in once

    def test_stable_wrap_retains_an_authored_break_canonical_reflows_it(self) -> None:
        source = "@misc{A, title={An authored\nline break with enough trailing words to wrap}}\n"
        stable = write_bib_canonical(
            parse_bib(source), CanonicalLayout(wrap_values="stable", line_width=60)
        )
        canonical = write_bib_canonical(
            parse_bib(source), CanonicalLayout(wrap_values="canonical", line_width=60)
        )
        assert "title = {An authored\n" in stable
        assert "title = {An authored line break" in canonical


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

    def test_repeated_fields_are_refused_instead_of_collapsed(self) -> None:
        source = "@misc{A, title={First}, title={Second}}\n"
        with pytest.raises(ValueError, match="repeated field"):
            write_bib_canonical(parse_bib(source))
        coll = Bibliography.from_text(source)
        with pytest.raises(FormatLintError) as exc:
            coll.format()
        assert [issue.type for issue in exc.value.issues] == ["duplicate_field"]

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

    def test_pynakes_meta_first_and_jabref_meta_last(self) -> None:
        source = (
            "@comment{jabref-meta: databaseType:bibtex;}\n"
            "@article{Test, title={A Test}}\n"
            "@comment{pynakes-meta: dialect: biblatex}\n"
            "trailing source text\n"
        )
        result = write_bib_canonical(parse_bib(source))
        pynakes_idx = result.find("pynakes-meta")
        entry_idx = result.find("@article{Test")
        trailing_idx = result.find("trailing source text")
        jabref_idx = result.find("jabref-meta")
        assert pynakes_idx < entry_idx < trailing_idx < jabref_idx
        assert result.rstrip().endswith("@comment{jabref-meta: databaseType:bibtex;}")
        assert write_bib_canonical(parse_bib(result)) == result

    def test_multiline_group_tree_with_colon_remains_one_metadata_value(self) -> None:
        source = (
            "@comment{pynakes-meta:\n"
            "group-tree: Papers\n"
            "  Machine Learning: AI|Papers\n"
            "}\n"
            "@article{Test, title={A Test}}\n"
        )

        result = write_bib_canonical(parse_bib(source))
        reparsed = parse_bib(result)
        tree = library_group_tree(reparsed)

        assert len(reparsed.pynakes_metadata_blocks) == 1
        assert reparsed.pynakes_metadata_blocks[0].key == "group-tree"
        assert tree is not None
        assert [(node.name, node.parent) for node in tree] == [
            ("Papers", ""),
            ("Machine Learning: AI", "Papers"),
        ]
        assert "  Machine Learning: AI|Papers" in result
        assert write_bib_canonical(reparsed) == result

    def test_multiline_jabref_grouping_remains_one_trailing_comment(self) -> None:
        source = (
            "@comment{jabref-meta: grouping:\n"
            "0 AllEntriesGroup:;\n"
            "1 StaticGroup:Papers;0;1;;;;\n"
            "2 StaticGroup:Machine Learning\\:AI;1;1;;;;\n"
            "}\n"
            "@article{Test, title={A Test}}\n"
        )

        result = write_bib_canonical(parse_bib(source))
        reparsed = parse_bib(result)
        tree = library_group_tree(reparsed)

        assert len(reparsed.jabref_metadata_blocks) == 1
        assert reparsed.jabref_metadata_blocks[0].key == "grouping"
        assert tree is not None
        assert [(node.name, node.parent) for node in tree] == [
            ("Papers", ""),
            ("Machine Learning:AI", "Papers"),
        ]
        assert result.index("@article{Test") < result.index("jabref-meta: grouping")
        assert write_bib_canonical(reparsed) == result

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

    def test_preserve_block_order_uses_comments_as_entry_sort_barriers(self) -> None:
        source = (
            "@misc{B, title={B}}\n"
            "@misc{A, title={A}}\n"
            "@comment{second section}\n"
            "@misc{D, title={D}}\n"
            "@misc{C, title={C}}\n"
        )
        layout = CanonicalLayout(block_order="preserve", entry_order="key")
        result = write_bib_canonical(parse_bib(source), layout)
        assert result.index("@misc{A") < result.index("@misc{B")
        assert result.index("@misc{B") < result.index("@comment{second section}")
        assert result.index("@comment{second section}") < result.index("@misc{C")
        assert result.index("@misc{C") < result.index("@misc{D")

    def test_portable_format_profile_resolves_with_cli_precedence(self) -> None:
        source = (
            "@comment{pynakes-meta:\n"
            "format-indent: 4\n"
            "format-alignment: equals\n"
            "format-field-order: alphabetical\n"
            "format-entry-order: key\n"
            "format-block-order: preserve\n"
            "format-wrap-values: stable\n"
            "format-line-width: 72\n"
            "format-trailing-comma: false\n"
            "format-blank-lines: false\n"
            "}\n"
            "@misc{A, title={T}}\n"
        )
        lib = parse_bib(source)
        profile = layout_from_metadata(lib)
        assert profile == CanonicalLayout(
            indent="    ",
            alignment="equals",
            trailing_comma=False,
            blank_line_entries=False,
            field_order="alphabetical",
            entry_order="key",
            block_order="preserve",
            wrap_values="stable",
            line_width=72,
        )
        assert layout_from_metadata(lib, line_width=90).line_width == 90

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
    original = parse_bib(path.read_text(encoding="utf-8"))
    formatted = write_bib_canonical(original)
    reparsed = parse_bib(formatted)
    # Entry types are compared case-insensitively: canonical layout lowercases
    # them, which BibTeX treats as the same type.
    before = [(entry.key, entry.type.lower(), entry.fields) for entry in original.entries.values()]
    after = [(entry.key, entry.type.lower(), entry.fields) for entry in reparsed.entries.values()]
    assert after == before
    assert write_bib_canonical(reparsed) == formatted


@pytest.mark.parametrize(
    "layout",
    [
        CanonicalLayout(indent="\t"),
        CanonicalLayout(indent="    "),
        CanonicalLayout(alignment="equals"),
        CanonicalLayout(trailing_comma=False),
        CanonicalLayout(blank_line_entries=False),
        CanonicalLayout(field_order="preserve"),
    ],
)
def test_every_layout_knob_is_idempotent(layout: CanonicalLayout) -> None:
    source = '@article{A, year={2020}, title="Quoted", month=jan}\n'
    once = write_bib_canonical(parse_bib(source), layout)
    assert write_bib_canonical(parse_bib(once), layout) == once


# --- entry-type case -------------------------------------------------------


@pytest.mark.parametrize("source_type", ["Article", "ARTICLE", "aRtIcLe"])
def test_canonical_layout_lowercases_the_entry_type(source_type: str) -> None:
    # Entry types are case-insensitive in BibTeX, so canonical layout emits the
    # lowercase form, matching the field names the parser already lowercases.
    lib = parse_bib(f"@{source_type}{{A,\n  title = {{T}},\n  year = {{2020}}\n}}\n")

    output = write_bib_canonical(lib)

    assert "@article{A," in output
    assert f"@{source_type}{{" not in output or source_type == "article"


def test_canonical_layout_preserves_the_citation_key_case() -> None:
    # Only the type is case-insensitive; a citation key is not.
    lib = parse_bib("@ARTICLE{MixedKey2020,\n  title = {T},\n  year = {2020}\n}\n")

    output = write_bib_canonical(lib)

    assert "@article{MixedKey2020," in output


def test_entry_type_recasing_is_not_a_semantic_change() -> None:
    # The formatter's own safety check must accept type recasing; if it did not,
    # write_bib_canonical would raise here.
    lib = parse_bib("@ARTICLE{A,\n  Title = {T},\n  YEAR = {2020}\n}\n")

    output = write_bib_canonical(lib)
    reparsed = parse_bib(output)

    assert reparsed.entries["A"].type == "article"
    assert reparsed.entries["A"].fields == lib.entries["A"].fields
    assert write_bib_canonical(reparsed) == output


def test_surgical_edits_keep_the_entry_type_spelling() -> None:
    # Only `format` recases types; an ordinary write must not touch an entry it
    # was not asked to change.
    lib = parse_bib("@ARTICLE{A,\n  title = {T},\n  year = {2020}\n}\n")

    assert "@ARTICLE{A," in write_bib(lib)


# ---------------------------------------------------------------------------
# selective (--where) formatting
# ---------------------------------------------------------------------------


_SELECTION_SOURCE = (
    "% a leading comment\n"
    "@article{A,\n"
    "    Title={First},\n"
    "  year={2020}\n"
    "}\n\n\n"
    "@book{B,   title={Second},  publisher={Elsevier}  }\n"
)


def test_format_selected_entries_rewrites_only_matching_entries() -> None:
    lib = parse_bib(_SELECTION_SOURCE)

    matched = format_selected_entries(lib, CanonicalLayout(), lambda entry: entry.type == "book")

    assert matched == 1
    output = write_bib(lib)
    # The unmatched entry, the comment, and the blank runs are byte-identical.
    assert "    Title={First},\n  year={2020}\n}\n\n\n" in output
    assert "% a leading comment" in output
    assert "@book{B,\n  title = {Second},\n  publisher = {Elsevier},\n}" in output


def test_format_selected_entries_is_idempotent() -> None:
    lib = parse_bib(_SELECTION_SOURCE)
    predicate = None  # every entry

    format_selected_entries(lib, CanonicalLayout(), predicate)
    once = write_bib(lib)
    format_selected_entries(lib, CanonicalLayout(), predicate)

    assert write_bib(lib) == once


def test_format_selected_entries_preserves_semantics() -> None:
    lib = parse_bib(_SELECTION_SOURCE)
    before = {key: dict(entry.fields) for key, entry in lib.entries.items()}

    format_selected_entries(lib, CanonicalLayout(field_order="alphabetical"), None)

    reparsed = parse_bib(write_bib(lib))
    assert {key: dict(e.fields) for key, e in reparsed.entries.items()} == before


def test_selective_format_leaves_unmatched_entries_out_of_the_diff() -> None:
    coll = Bibliography.from_text(_SELECTION_SOURCE)

    matched = coll.format(CanonicalLayout(), "type = article")

    assert matched == 1
    diff = coll.diff()
    assert "@book{B," not in diff
    assert "Title={First}" in diff


def test_selective_format_survives_a_later_surgical_edit() -> None:
    # Reformatting an entry replaces its raw_content, so the surgical editors
    # must still find their way around it afterwards.
    coll = Bibliography.from_text(_SELECTION_SOURCE)
    coll.format(CanonicalLayout(), "key = A")
    coll.set_field("note", "checked", "key = A")

    output = coll.preview()
    assert "  year = {2020},\n  note = {checked}\n}" in output
    assert "@book{B,   title={Second},  publisher={Elsevier}  }" in output


def test_format_selected_entries_resolves_string_macros_in_its_safety_check() -> None:
    # An entry's semantic values are @string-interpolated, so the per-entry check
    # must reparse it with the library's macro namespace rather than in isolation
    # (otherwise `journal = NMI # {...}` reads as a changed value and is refused).
    lib = parse_bib(
        "@string{NMI = {Nature Mach. Intell.}}\n\n"
        "@article{A,\n  journal = NMI # { Supplement},\n  title={T}\n}\n"
    )

    assert format_selected_entries(lib, CanonicalLayout(), None) == 1

    output = write_bib(lib)
    assert "journal = NMI # { Supplement}," in output
    assert parse_bib(output).entries["A"].fields["journal"] == "Nature Mach. Intell. Supplement"


def test_format_selected_entries_wrapping_is_idempotent() -> None:
    lib = parse_bib(
        "@article{A,\n"
        "  author = {Ada Example and Bob Example and Cyd Example and Dee Example},\n"
        "  title = {A Long Prose Title That Runs Well Past Any Reasonable Line Width Limit}\n"
        "}\n"
    )
    layout = CanonicalLayout(wrap_values="canonical", line_width=60)

    format_selected_entries(lib, layout, None)
    once = write_bib(lib)
    format_selected_entries(lib, layout, None)

    assert write_bib(lib) == once
    assert "and\n" in once  # the value really was wrapped
