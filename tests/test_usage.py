"""Tests for citation-usage detection, tagging, and subset export."""

from pathlib import Path

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.usage import (
    analyze_usage,
    collect_citation_occurrences,
    collect_cited_keys,
    extract_keys_from_aux,
    extract_keys_from_tex,
    rename_citation_key_in_tex,
    rename_citation_keys_in_tex,
    resolve_existing_tex_sources,
    splice_into_text,
    subset_library,
    tag_with_group,
    tag_with_keyword,
    tex_sources_from_metadata,
    validate_tex_sources,
)


def test_tex_sources_from_metadata_resolves_relative_to_base() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: tex-sources:paper.tex, sections/;}\n@article{A,\n  title = {T}\n}\n"
    )

    assert tex_sources_from_metadata(lib, "/proj") == ["/proj/paper.tex", "/proj/sections"]


def test_tex_sources_from_metadata_absolute_kept_and_legacy_alias() -> None:
    lib = parse_bib(
        "@comment{pynakes-meta: tex-sources:/abs/main.tex;}\n@article{A,\n  title = {T}\n}\n"
    )
    assert tex_sources_from_metadata(lib, "/proj") == ["/abs/main.tex"]


def test_tex_sources_from_metadata_absent_is_empty() -> None:
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")
    assert tex_sources_from_metadata(lib, "/proj") == []


def test_validate_tex_sources_all_exist(tmp_path: Path) -> None:
    tex = tmp_path / "paper.tex"
    tex.write_text("")
    assert validate_tex_sources([str(tex)]) == []


def test_validate_tex_sources_missing(tmp_path: Path) -> None:
    existing = tmp_path / "paper.tex"
    existing.write_text("")
    missing = tmp_path / "nonexistent.tex"
    warnings = validate_tex_sources([str(existing), str(missing)])
    assert len(warnings) == 1
    assert warnings[0]["type"] == "missing_tex_source"
    assert warnings[0]["path"] == str(missing)


def test_validate_tex_sources_empty() -> None:
    assert validate_tex_sources([]) == []


def test_resolve_existing_tex_sources_drops_missing_and_warns(tmp_path: Path) -> None:
    existing = tmp_path / "paper.tex"
    existing.write_text("")
    missing = str(tmp_path / "nonexistent.tex")

    resolved, warnings = resolve_existing_tex_sources([str(existing), missing])

    assert resolved == [str(existing)]
    assert len(warnings) == 1
    assert warnings[0]["type"] == "missing_tex_source"
    assert warnings[0]["path"] == missing


def test_resolve_existing_tex_sources_all_exist(tmp_path: Path) -> None:
    existing = tmp_path / "paper.tex"
    existing.write_text("")

    resolved, warnings = resolve_existing_tex_sources([str(existing)])

    assert resolved == [str(existing)]
    assert warnings == []


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


class TestExtraction:
    def test_aux_citations(self) -> None:
        text = "\\citation{Smith2020}\n\\citation{A,B}\n\\bibdata{refs}\n"
        assert extract_keys_from_aux(text) == ["Smith2020", "A", "B"]

    def test_tex_cite_family(self) -> None:
        text = (
            r"\cite{A} \citep{B} \citet{C} \parencite{D} "
            r"\autocite{E} \textcite{F} \nocite{G}"
        )
        assert set(extract_keys_from_tex(text)) == {"A", "B", "C", "D", "E", "F", "G"}

    def test_tex_optional_args_and_multiple_keys(self) -> None:
        text = r"\citep[see][p.~3]{Brown2022, Jones2021}"
        assert set(extract_keys_from_tex(text)) == {"Brown2022", "Jones2021"}

    def test_tex_comments_ignored(self) -> None:
        text = "valid \\cite{Real}\n% commented \\cite{Fake}\nescaped 50\\% \\cite{AlsoReal}"
        keys = set(extract_keys_from_tex(text))
        assert keys == {"Real", "AlsoReal"}

    def test_nocite_star_collected(self, tmp_path: Path) -> None:
        tex = tmp_path / "main.tex"
        tex.write_text(r"\nocite{*}")
        keys, include_all, _ = collect_cited_keys([str(tex)])
        assert include_all is True

    def test_collect_scans_directory(self, fixtures_dir: Path) -> None:
        keys, _, scanned = collect_cited_keys([str(fixtures_dir)])
        # Both paper.tex and paper.aux live in fixtures/.
        assert "Smith2020" in keys
        assert any(s.endswith("paper.aux") for s in scanned)
        assert any(s.endswith("paper.tex") for s in scanned)

    def test_missing_source_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            collect_cited_keys(["does_not_exist.tex"])

    def test_rename_citation_key_in_tex_preserves_comments_and_spacing(self) -> None:
        text = (
            r"\citep[see][p.~3]{ Old ,Other}"
            "\n"
            r"% \cite{Old}"
            "\n"
            r"escaped 50\% \cite{Old}"
        )

        new_text, count = rename_citation_key_in_tex(text, "Old", "New")

        assert count == 2
        assert r"\citep[see][p.~3]{ New ,Other}" in new_text
        assert r"% \cite{Old}" in new_text
        assert r"escaped 50\% \cite{New}" in new_text

    def test_rename_citation_keys_in_tex_is_simultaneous(self) -> None:
        text = r"\cite{A,B}"

        new_text, count = rename_citation_keys_in_tex(text, [("A", "B"), ("B", "C")])

        assert count == 2
        assert new_text == r"\cite{B,C}"


class TestAnalysis:
    def _lib(self):
        return parse_bib("@article{Used,year={2020}}\n@article{Unused,year={2021}}\n")

    def test_used_unused_missing(self) -> None:
        lib = self._lib()
        report = analyze_usage(lib, {"Used", "Ghost"})
        assert report.used == ["Used"]
        assert report.unused == ["Unused"]
        assert report.missing == ["Ghost"]

    def test_include_all_marks_everything_used(self) -> None:
        lib = self._lib()
        report = analyze_usage(lib, set(), include_all=True)
        assert set(report.used) == {"Used", "Unused"}
        assert report.unused == []

    def test_aux_fixture_against_simple_bib(self, fixtures_dir: Path) -> None:
        lib = parse_bib((fixtures_dir / "simple.bib").read_text())
        keys, include_all, _ = collect_cited_keys([str(fixtures_dir / "paper.aux")])
        report = analyze_usage(lib, keys, include_all=include_all)
        assert set(report.used) == {"Smith2020", "Brown2022"}
        assert "Missing2099" in report.missing


class TestSubsetExport:
    def test_subset_keeps_only_requested(self) -> None:
        lib = parse_bib(
            "@string{venue = {Journal}}\n"
            "@article{A,year={1}, journal=venue}\n"
            "@article{B,year={2}}\n"
            "@article{C,year={3}}\n"
        )
        sub = subset_library(lib, ["A", "C"])
        assert sorted(sub.entries.keys()) == ["A", "C"]
        assert sub.raw_strings == ["@string{venue = {Journal}}"]
        # The subset is a valid, parseable library.
        reparsed = parse_bib(write_bib(sub))
        assert sorted(reparsed.entries.keys()) == ["A", "C"]


class TestTagging:
    def test_tag_group_inserts_field(self) -> None:
        lib = parse_bib("@article{A,\n  year = {2020}\n}\n")
        count = tag_with_group(lib, ["A"], "Used")
        assert count == 1
        assert lib.entries["A"].fields["groups"] == "Used"
        # Round-trips through the writer.
        assert "Used" in parse_bib(write_bib(lib)).entries["A"].fields["groups"]

    def test_tag_group_appends_to_existing(self) -> None:
        lib = parse_bib("@article{A,\n  groups = {Existing},\n  year = {2020}\n}\n")
        tag_with_group(lib, ["A"], "Used")
        assert lib.entries["A"].fields["groups"] == "Existing; Used"

    def test_tag_group_is_idempotent(self) -> None:
        lib = parse_bib("@article{A,\n  groups = {Used},\n  year = {2020}\n}\n")
        count = tag_with_group(lib, ["A"], "Used")
        assert count == 0

    def test_tag_preserves_other_fields_verbatim(self) -> None:
        # Surgical edit: only the groups line is added; untouched fields keep
        # their exact original text (no reformatting, no data loss).
        original = "@article{A,\n  title = {The {DNA} Helix},\n  year = {2020}\n}\n"
        lib = parse_bib(original)
        tag_with_group(lib, ["A"], "Used")
        out = write_bib(lib)
        assert "The {DNA} Helix" in out
        assert "groups = {Used}" in out

    def test_tag_keyword(self) -> None:
        lib = parse_bib("@article{A,\n  keywords = {ml},\n  year = {2020}\n}\n")
        tag_with_keyword(lib, ["A"], "used")
        assert lib.entries["A"].fields["keywords"] == "ml, used"

    def test_tag_only_targets_listed_keys(self) -> None:
        lib = parse_bib("@article{A,year={1}}\n@article{B,year={2}}\n")
        tag_with_group(lib, ["A"], "Used")
        assert "groups" in lib.entries["A"].fields
        assert "groups" not in lib.entries["B"].fields


class TestSplice:
    def test_replaces_only_changed_block(self) -> None:
        original = "@article{A,\n  year = {2020}\n}\n\n@article{B,\n  year = {2021}\n}\n"
        lib = parse_bib(original)
        before = lib.entries["A"].raw_content
        tag_with_group(lib, ["A"], "X")
        spliced = splice_into_text(original, [(before, lib.entries["A"].raw_content)])
        # B's block and the blank line between entries are untouched.
        assert spliced is not None
        assert "@article{B,\n  year = {2021}\n}" in spliced
        assert "groups = {X}" in spliced
        # A's prior last field gains a trailing comma; nothing is lost.
        assert "  year = {2020},\n  groups = {X}" in spliced

    def test_returns_none_when_block_absent(self) -> None:
        assert splice_into_text("nothing here", [("@article{Z}", "@article{Z2}")]) is None


# --- citation occurrences --------------------------------------------------


def test_collect_citation_occurrences_locates_every_key(tmp_path: Path) -> None:
    tex = tmp_path / "paper.tex"
    tex.write_text(
        "Intro text.\n"
        r"As shown~\cite{Smith2020} and \citep[see][]{Brown2022,Smith2020}." + "\n",
    )

    occurrences, include_all, scanned = collect_citation_occurrences([str(tex)])

    assert include_all is False
    assert scanned == [str(tex)]
    assert sorted(occurrences) == ["Brown2022", "Smith2020"]
    assert [(m.line, m.macro) for m in occurrences["Smith2020"]] == [(2, "cite"), (2, "citep")]
    assert [m.line for m in occurrences["Brown2022"]] == [2]
    first = occurrences["Smith2020"][0]
    assert first.path == str(tex)
    assert first.text == r"\cite{Smith2020}"
    # One-based column of the macro's backslash: "As shown~" is nine characters.
    assert first.column == 10


def test_collect_citation_occurrences_covers_keys_absent_from_any_library(tmp_path: Path) -> None:
    # A cited-but-missing key is the one a caller most needs to locate, so it is
    # in the map like any other.
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\cite{NotInLibrary}" "\n")

    occurrences, _, _ = collect_citation_occurrences([str(tex)])

    assert [m.line for m in occurrences["NotInLibrary"]] == [1]


def test_collect_citation_occurrences_ignores_commented_out_citations(tmp_path: Path) -> None:
    tex = tmp_path / "paper.tex"
    tex.write_text(r"% \cite{Commented}" "\n" r"\cite{Real}" "\n")

    occurrences, _, _ = collect_citation_occurrences([str(tex)])

    assert sorted(occurrences) == ["Real"]


def test_collect_citation_occurrences_keeps_line_and_column_after_a_comment(
    tmp_path: Path,
) -> None:
    # Comment stripping must not shift what follows on later lines.
    tex = tmp_path / "paper.tex"
    tex.write_text("% a comment\n" "text % trailing\n" r"  \cite{Smith2020}" "\n")

    occurrences, _, _ = collect_citation_occurrences([str(tex)])

    match = occurrences["Smith2020"][0]
    assert (match.line, match.column) == (3, 3)


def test_collect_citation_occurrences_records_nocite_star_without_a_key(tmp_path: Path) -> None:
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\nocite{*}" "\n" r"\cite{Smith2020}" "\n")

    occurrences, include_all, _ = collect_citation_occurrences([str(tex)])

    assert include_all is True
    assert sorted(occurrences) == ["Smith2020"]


def test_collect_citation_occurrences_reads_aux_citations(tmp_path: Path) -> None:
    aux = tmp_path / "paper.aux"
    aux.write_text(r"\citation{Smith2020}" "\n")

    occurrences, _, _ = collect_citation_occurrences([str(aux)])

    assert [(m.line, m.macro) for m in occurrences["Smith2020"]] == [(1, "citation")]


def test_collect_cited_keys_agrees_with_the_occurrence_map(tmp_path: Path) -> None:
    # collect_cited_keys is a projection of the same scan, not a second scanner.
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\cite{A,B}" "\n" r"\nocite{*}" "\n")

    keys, include_all, scanned = collect_cited_keys([str(tex)])
    occurrences, occ_include_all, occ_scanned = collect_citation_occurrences([str(tex)])

    assert keys == set(occurrences)
    assert (include_all, scanned) == (occ_include_all, occ_scanned)


def test_analyze_usage_passes_occurrences_into_the_report(tmp_path: Path) -> None:
    lib = parse_bib("@article{Smith2020,\n  title = {T}\n}\n")
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\cite{Smith2020}" "\n" r"\cite{Missing2099}" "\n")
    occurrences, _, scanned = collect_citation_occurrences([str(tex)])

    report = analyze_usage(lib, set(occurrences), sources=scanned, usages=occurrences)

    assert report.used == ["Smith2020"]
    assert report.missing == ["Missing2099"]
    assert sorted(report.to_dict()["usages"]) == ["Missing2099", "Smith2020"]
    assert report.to_dict()["usages"]["Smith2020"][0] == {
        "path": str(tex),
        "line": 1,
        "text": r"\cite{Smith2020}",
        "column": 1,
        "macro": "cite",
    }


def test_analyze_usage_without_occurrences_reports_an_empty_map() -> None:
    lib = parse_bib("@article{A,\n  title = {T}\n}\n")

    assert analyze_usage(lib, {"A"}).to_dict()["usages"] == {}
