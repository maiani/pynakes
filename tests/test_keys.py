"""Tests for citation-key generation, duplicate detection, and repair."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.bibtex_writer import write_bib
from pynakes.keys import (
    UnsupportedCitationKeyPatternError,
    duplicate_key_counts,
    generate_key,
    generate_key_from_pattern,
    has_duplicate_keys,
    regenerate_key,
    regenerate_keys,
    rename_key,
    repair_duplicate_keys,
)
from pynakes.model import BibEntry


def _entry(**fields) -> BibEntry:
    return BibEntry(key="orig", type="article", fields=fields)


class TestGenerateKey:
    def test_author_year_title(self) -> None:
        e = _entry(author="John Smith", year="2020", title="Big Data Analysis")
        assert generate_key(e) == "Smith2020Big"

    def test_last_comma_first_name_format(self) -> None:
        e = _entry(author="Smith, John", year="2020", title="Data")
        assert generate_key(e) == "Smith2020Data"

    def test_multiple_authors_uses_first(self) -> None:
        e = _entry(author="Jane Doe and John Smith", year="2019", title="Networks")
        assert generate_key(e) == "Doe2019Networks"

    def test_skips_title_stopwords(self) -> None:
        e = _entry(author="Smith", year="2020", title="The Theory of Everything")
        assert generate_key(e) == "Smith2020Theory"

    def test_strips_protective_braces(self) -> None:
        e = _entry(author="{World Bank}", year="2021", title="{GDP} Report")
        assert generate_key(e) == "WorldBank2021GDP"

    @pytest.mark.parametrize("command", (r"\phi", r"\varphi", r"\Phi"))
    def test_converts_leading_tex_math_to_conventional_title_word(self, command: str) -> None:
        e = _entry(
            author="John Smith",
            year="2025",
            title=rf"${command}$-junction effect",
        )

        assert generate_key(e) == "Smith2025Phi"
        assert generate_key_from_pattern(e, "[auth]_[year]_[veryshorttitle]") == ("smith_2025_phi")

    def test_tex_math_wrappers_do_not_become_title_words(self) -> None:
        e = _entry(
            author="John Smith",
            year="2025",
            title=r"{\ensuremath{\phi}}-junction effect",
        )

        assert generate_key_from_pattern(e, "[auth]_[year]_[Veryshorttitle]") == ("smith_2025_Phi")
        assert generate_key_from_pattern(e, "[auth]_[year]_[title]") == (
            "smith_2025_phijunctioneffect"
        )

    def test_falls_back_to_editor_then_anon(self) -> None:
        assert (
            generate_key(_entry(editor="Ann Lee", year="2020", title="Reader")) == "Lee2020Reader"
        )
        assert generate_key(_entry(year="2020", title="Untitled")).startswith("Anon2020")

    def test_year_from_biblatex_date(self) -> None:
        e = _entry(author="Smith", date="2022-07-15", title="Stuff")
        assert generate_key(e) == "Smith2022Stuff"

    def test_deterministic(self) -> None:
        e = _entry(author="Smith", year="2020", title="Data")
        assert generate_key(e) == generate_key(e)

    def test_jabref_default_pattern_from_library_metadata(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear][veryshorttitle];}\n"
            "@article{old,\n"
            "  author = {John Smith},\n"
            "  year = {2024},\n"
            "  title = {A Practical Test}\n"
            "}\n"
        )
        assert generate_key(lib.entries["old"], lib) == "smith24practical"

    def test_jabref_entry_type_pattern_overrides_default(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][year];}\n"
            "@comment{jabref-meta: keypattern_article:[auth][year][veryshorttitle];}\n"
            "@article{old,\n"
            "  author = {John Smith},\n"
            "  year = {2024},\n"
            "  title = {A Practical Test}\n"
            "}\n"
        )
        assert generate_key(lib.entries["old"], lib) == "smith2024practical"

    def test_jabref_pattern_supports_literals_and_field_markers(self) -> None:
        e = _entry(
            author="John Smith", year="2024", title="A Practical Test", journal="Test Journal"
        )
        assert generate_key_from_pattern(e, "[auth]-[YEAR]-[journal:abbr]") == "smith-2024-tj"

    @pytest.mark.parametrize("marker", ["unknownSpecial", "auth.ini", "auth.easy", "author2"])
    def test_unsupported_jabref_pattern_errors(self, marker: str) -> None:
        e = _entry(author="John Smith", year="2024", title="A Practical Test")
        with pytest.raises(UnsupportedCitationKeyPatternError, match="Unsupported") as exc_info:
            generate_key_from_pattern(e, f"[auth][{marker}]")
        assert marker in str(exc_info.value)

    def test_marker_variants(self) -> None:
        e = _entry(
            author="John Smith and Jane Doe and Bob Roe",
            year="2024",
            title="A Practical Study of Things",
        )
        assert generate_key_from_pattern(e, "[auth3]") == "smi"  # truncated, lowercased last name
        assert generate_key_from_pattern(e, "[authors]") == "smithdoeroe"
        assert generate_key_from_pattern(e, "[shortyear]") == "24"
        assert generate_key_from_pattern(e, "[shorttitle]") == "practicalstudythings"
        assert generate_key_from_pattern(e, "[camel2]") == "apractical"
        assert generate_key_from_pattern(e, "[entrytype]") == "article"
        assert generate_key_from_pattern(e, "[authorlast]") == "roe"
        assert generate_key_from_pattern(e, "[Authorlast]") == "Roe"
        assert generate_key_from_pattern(e, "[authIni4]") == "SmDR"
        assert generate_key_from_pattern(e, "[authorIni]") == "SmithDR"
        assert generate_key_from_pattern(e, "[authors2]") == "smithdoeetal"

    def test_mixed_case_marker_only_forces_first_letter(self) -> None:
        # Regression: [Auth]-style markers (capital first letter) used to
        # force the *entire rest* of the value to lowercase too, corrupting
        # legitimately mixed-case values: a compound surname stripped of its
        # hyphen ("Pioro-Ladriere" -> "PioroLadriere") or a title starting
        # with an acronym ("AI for ..."). Real JabRef markers are
        # case-insensitive except for the explicit all-lower/all-upper forms
        # already covered by test_marker_variants; a mixed-case marker should
        # only guarantee an uppercase first letter, not reshape the rest.
        e = _entry(author="Michel Pioro-Ladriere", year="2008", title="Electrically driven spin")
        assert generate_key_from_pattern(e, "[Auth]") == "PioroLadriere"

        e2 = _entry(author="Xin Gao", year="2025", title="AI for materials discovery")
        assert generate_key_from_pattern(e2, "[Veryshorttitle]") == "AI"

    def test_accented_author_names_fold_to_ascii(self) -> None:
        e = _entry(
            author="Šexample, Aa and Øfoo-Bär, Bb",
            year="2020",
            title="Generic Sample Title",
        )
        # The leading accented letter must fold to ASCII (Š → S), not be dropped.
        assert generate_key_from_pattern(e, "[auth]_[year]_[veryshorttitle]") == (
            "sexample_2020_generic"
        )
        assert generate_key_from_pattern(e, "[authors]") == "sexampleofoobar"

    def test_von_particle_dropped_from_comma_form_last_name(self) -> None:
        # BibTeX "von Last, First" names: a leading lowercase particle
        # ("van den", "de la", "von") is not part of the last name.
        e = _entry(author="van den Berg, J. W. G.", year="2013", title="Fast qubit")
        assert generate_key_from_pattern(e, "[Auth]") == "Berg"

        e2 = _entry(author="van Riggelen-Doelman, Floor", year="2024", title="Coherent shuttling")
        assert generate_key_from_pattern(e2, "[Auth]") == "RiggelenDoelman"

        e3 = _entry(author="de la Cruz, Maria", year="2020", title="Sample")
        assert generate_key_from_pattern(e3, "[auth]") == "cruz"

        # An all-lowercase "von Last" segment with no capitalized word at all
        # is kept whole rather than discarded down to nothing.
        e4 = _entry(author="van der berg, jan", year="1990", title="Sample")
        assert generate_key_from_pattern(e4, "[auth]") == "vanderberg"

    def test_modifier_variants(self) -> None:
        e = _entry(
            author="John Smith", year="2024", title="A Practical Study", journal="test journal"
        )
        assert generate_key_from_pattern(e, "[auth:lower]") == "smith"
        assert generate_key_from_pattern(e, "[auth:upper]") == "SMITH"
        assert generate_key_from_pattern(e, "[journal:abbr]") == "tj"
        assert generate_key_from_pattern(e, "[journal:capitalize]") == "TestJournal"
        assert generate_key_from_pattern(e, "[auth:truncate3]") == "smi"

    def test_unsupported_modifier_errors(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study")
        with pytest.raises(UnsupportedCitationKeyPatternError, match="modifier"):
            generate_key_from_pattern(e, "[auth:bogusmod]")

    @pytest.mark.parametrize(
        "marker",
        [
            "authN_M",
            "edtr.edtr.ea",
            "authorsAlpha",
            "authorsAlphaLNI",
            "authorLastForeIni",
            "keywordN",
        ],
    )
    def test_unsupported_combinator_markers_still_error(self, marker: str) -> None:
        # These remain intentionally out of scope; they must keep failing
        # explicitly rather than silently resolving wrong or empty.
        e = _entry(author="John Smith", year="2024", title="A Study")
        with pytest.raises(UnsupportedCitationKeyPatternError, match="Unsupported"):
            generate_key_from_pattern(e, f"[{marker}]")

    def test_editor_marker_variants(self) -> None:
        e = _entry(
            editor="Ada Example and Grace Sample and Rex Fixture",
            year="2024",
            title="A Study",
        )
        assert generate_key_from_pattern(e, "[edtr]") == "example"
        assert generate_key_from_pattern(e, "[Edtr]") == "Example"
        assert generate_key_from_pattern(e, "[EDTR]") == "EXAMPLE"
        assert generate_key_from_pattern(e, "[edtr3]") == "exa"
        assert generate_key_from_pattern(e, "[editors]") == "examplesamplefixture"
        assert generate_key_from_pattern(e, "[editors2]") == "examplesampleetal"
        assert generate_key_from_pattern(e, "[editorlast]") == "fixture"
        assert generate_key_from_pattern(e, "[editorini]") == "exampsf"
        assert generate_key_from_pattern(e, "[edtrini4]") == "exsf"

    def test_editor_marker_does_not_fall_back_to_author(self) -> None:
        # Unlike [auth]/[authors], which fall back to editor when author is
        # absent, [edtr]/[editors] must never read the author field. A leading
        # literal keeps the result from being empty, which would otherwise
        # trigger the unrelated "empty pattern falls back to AuthorYearTitle"
        # behavior and mask what this test checks.
        e = _entry(author="John Smith", year="2024", title="A Study")
        assert generate_key_from_pattern(e, "[edtr]") == "anon"
        assert generate_key_from_pattern(e, "x[editors]") == "x"

    def test_page_markers(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study", pages="7,41,73--97")
        assert generate_key_from_pattern(e, "[firstpage]") == "7"
        assert generate_key_from_pattern(e, "[lastpage]") == "97"
        # See test_editor_marker_does_not_fall_back_to_author for why the
        # empty case needs a non-empty literal wrapper.
        assert generate_key_from_pattern(e, "x[pageprefix]") == "x"

        prefixed = _entry(author="John Smith", year="2024", title="A Study", pages="L7--L9")
        assert generate_key_from_pattern(prefixed, "[Pageprefix]") == "L"

        no_pages = _entry(author="John Smith", year="2024", title="A Study")
        # An empty pattern result falls back to the default AuthorYearTitle key.
        assert generate_key_from_pattern(no_pages, "[firstpage]") == generate_key(no_pages)

    def test_fulltitle_marker_preserves_stopwords_and_spacing(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study of Rare Things")
        # Unlike [title]/[shorttitle], [fulltitle] keeps every word and its
        # original spacing (spaces only disappear at final key sanitization).
        assert generate_key_from_pattern(e, "[fulltitle:truncate3]") == "as"
        assert generate_key_from_pattern(e, "[title]") != generate_key_from_pattern(
            e, "[fulltitle]"
        )

    def test_formatter_modifier_variants(self) -> None:
        # Any registered field formatter is usable directly as a modifier.
        e = _entry(author="John Smith", year="2024", title="A Study", journal="{Sample} Journal")
        assert generate_key_from_pattern(e, "[journal:remove_braces]") == "samplejournal"
        assert generate_key_from_pattern(e, "[journal:sentencecase]") == "samplejournal"

    def test_title_word_modifiers_apply_to_arbitrary_fields(self) -> None:
        # veryshorttitle/shorttitle/camel are markers, but JabRef also exposes
        # them as modifiers applying the same word-selection algorithm to
        # whatever value precedes them in the chain, not just the title field.
        e = _entry(
            author="John Smith",
            year="2024",
            title="A Study",
            journal="the deep learning review quarterly",
        )
        assert generate_key_from_pattern(e, "[journal:veryshorttitle]") == "Deep"
        assert generate_key_from_pattern(e, "[journal:shorttitle]") == "DeepLearningReview"
        # Unlike shorttitle, camel does not filter stopwords.
        assert generate_key_from_pattern(e, "[journal:camel]") == "TheDeepLearningReviewQuarterly"

    def test_regex_modifier(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study", journal="report.etal")
        assert generate_key_from_pattern(e, r'[journal:regex("\.etal","EtAl")]') == "reportEtAl"

    def test_malformed_regex_modifier_errors(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study", journal="x")
        with pytest.raises(UnsupportedCitationKeyPatternError, match="modifier"):
            generate_key_from_pattern(e, "[journal:regex(bogus)]")

    def test_regex_modifier_supports_backreferences(self) -> None:
        # Character classes such as [a-z] inside a regex modifier are outside
        # this pass's scope: the pattern's own [marker] bracket scanner would
        # misread the literal '[' as a marker boundary. Groups without a
        # bracketed class exercise backreference support without hitting that.
        e = _entry(author="John Smith", year="2024", title="A Study", journal="aabb")
        assert generate_key_from_pattern(e, r'[journal:regex("(a+)(b+)","$2$1")]') == "bbaa"

    def test_default_value_modifier(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study")
        assert generate_key_from_pattern(e, "[volume:(nd)]") == "nd"

        with_volume = _entry(author="John Smith", year="2024", title="A Study", volume="12")
        assert generate_key_from_pattern(with_volume, "[volume:(nd)]") == "12"

    def test_default_value_modifier_checks_pre_chain_value(self) -> None:
        # The default only fires when the marker's own resolved value was
        # empty, not when an earlier modifier in the chain made it empty: here
        # regex(...) empties a non-empty "keep", so the default is not applied.
        e = _entry(author="John Smith", year="2024", title="A Study", journal="keep")
        pattern = 'x[journal:regex("keep",""):(fallback)]'
        assert generate_key_from_pattern(e, pattern) == "x"

    def test_truncate_trims_trailing_whitespace(self) -> None:
        e = _entry(author="John Smith", year="2024", title="A Study", journal="ab cd")
        # Truncating "ab cd" (marker-cased to "Ab cd") to 3 chars lands on a
        # trailing space, which JabRef's truncateN strips.
        assert generate_key_from_pattern(e, "[Journal:truncate3]") == "Ab"


class TestDuplicateDetection:
    def test_detects_duplicates(self) -> None:
        lib = parse_bib("@article{A,year={1}}\n@article{A,year={2}}\n@book{B,year={3}}\n")
        assert has_duplicate_keys(lib) is True
        assert duplicate_key_counts(lib) == {"A": 2}

    def test_no_duplicates(self) -> None:
        lib = parse_bib("@article{A,year={1}}\n@book{B,year={2}}\n")
        assert has_duplicate_keys(lib) is False
        assert duplicate_key_counts(lib) == {}


class TestRepair:
    def test_repair_suffixes_later_duplicates(self) -> None:
        lib = parse_bib(
            "@article{A,\n  year = {1}\n}\n\n@article{A,\n  year = {2}\n}\n\n"
            "@article{A,\n  year = {3}\n}\n"
        )
        renames = repair_duplicate_keys(lib)
        assert renames == [("A", "A_2"), ("A", "A_3")]
        assert sorted(lib.entries.keys()) == ["A", "A_2", "A_3"]
        assert not has_duplicate_keys(lib)

    def test_repair_avoids_existing_keys(self) -> None:
        lib = parse_bib("@article{A,year={1}}\n@article{A,year={2}}\n@article{A_2,year={3}}\n")
        renames = repair_duplicate_keys(lib)
        # A_2 is taken, so the duplicate becomes A_3.
        assert renames == [("A", "A_3")]
        assert not has_duplicate_keys(lib)

    def test_repair_round_trips(self) -> None:
        lib = parse_bib(
            "@article{Dup,\n  title = {First}\n}\n\n@article{Dup,\n  title = {Second}\n}\n"
        )
        repair_duplicate_keys(lib)
        out = write_bib(lib)
        assert "@article{Dup," in out
        assert "@article{Dup_2," in out
        assert parse_bib(out).entries.duplicate_keys() == {}


class TestRename:
    def test_rename_single_key(self) -> None:
        lib = parse_bib("@article{Old,\n  title = {T}\n}\n")

        assert rename_key(lib, "Old", "New") == 1

        assert "New" in lib.entries
        assert "@article{New," in write_bib(lib)

    def test_rename_rejects_existing_target(self) -> None:
        lib = parse_bib("@article{Old,year={1}}\n@article{New,year={2}}\n")

        with pytest.raises(ValueError, match="target key already exists"):
            rename_key(lib, "Old", "New")

    def test_rename_rejects_duplicated_source_key(self) -> None:
        lib = parse_bib("@article{Old,year={1}}\n@article{Old,year={2}}\n")

        with pytest.raises(ValueError, match="repair duplicates"):
            rename_key(lib, "Old", "New")


class TestRegenerate:
    def test_regenerate_one_uses_pattern_without_changing_other_keys(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear];}\n"
            "@article{old,\n  author = {John Smith},\n  year = {2024},\n  title = {Data}\n}\n"
            "@article{keep,\n  author = {Jane Doe},\n  year = {2023},\n  title = {Other}\n}\n"
        )

        assert regenerate_key(lib, "old") == ("old", "smith24")

        assert "smith24" in lib.entries
        assert "keep" in lib.entries

    def test_regenerate_one_disambiguates_against_existing_keys(self) -> None:
        lib = parse_bib(
            "@article{old,\n  author = {John Smith},\n  year = {2024},\n  title = {Data}\n}\n"
            "@article{Smith2024Data,\n  title = {Existing}\n}\n"
        )

        assert regenerate_key(lib, "old") == ("old", "Smith2024Dataa")

    def test_regenerate_applies_generated_keys(self) -> None:
        lib = parse_bib(
            "@article{old1,\n  author = {John Smith},\n  year = {2020},\n  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        assert renames == [("old1", "Smith2020Data")]
        assert "Smith2020Data" in lib.entries

    def test_regenerate_mints_key_for_empty_key_entry(self) -> None:
        # An entry parsed with an empty key must get a real key on generate,
        # surgically (only the header line changes).
        lib = parse_bib(
            "@article{,\n  author = {Bob White},\n  year = {2022},\n  title = {Findings}\n}\n"
        )
        renames = regenerate_keys(lib)
        assert renames == [("", "White2022Findings")]
        assert "White2022Findings" in lib.entries
        out = write_bib(lib)
        assert out.startswith("@article{White2022Findings,")
        assert "@article{," not in out

    def test_regenerate_disambiguates_collisions(self) -> None:
        lib = parse_bib(
            "@article{x,\n  author = {Smith},\n  year = {2020},\n  title = {Data}\n}\n\n"
            "@article{y,\n  author = {Smith},\n  year = {2020},\n  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        new_keys = [n for _, n in renames]
        assert new_keys == ["Smith2020Data", "Smith2020Dataa"]

    def test_regenerate_uses_jabref_pattern_metadata(self) -> None:
        lib = parse_bib(
            "@comment{jabref-meta: keypatterndefault:[auth][shortyear];}\n"
            "@article{old,\n  author = {John Smith},\n  year = {2024},\n"
            "  title = {Data}\n}\n"
        )
        renames = regenerate_keys(lib)
        assert renames == [("old", "smith24")]

    def test_regenerate_skips_xdata_entries(self) -> None:
        # @xdata entries are referenced by key from other entries via
        # ``xdata = {key}``; renaming them would silently break those refs.
        src = (
            "@xdata{pub, publisher = {Press}, location = {City}}\n"
            "@book{old, xdata = {pub}, title = {T}, author = {Doe, J.}, year = {2020}}\n"
        )
        lib = parse_bib(src)
        renames = regenerate_keys(lib)
        renamed_keys = {old for old, _ in renames}
        assert "pub" not in renamed_keys, "xdata entry key must not be renamed"
        assert lib.entries["pub"].type == "xdata"
        # The @book entry is still renamed normally.
        assert any(new == "Doe2020T" for _, new in renames)
        # The xdata reference in the @book entry still points to the original key.
        from pynakes.bibtex_writer import write_bib

        out = write_bib(lib)
        assert "xdata = {pub}" in out
