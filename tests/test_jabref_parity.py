"""JabRef feature-parity tests (golden vectors).

The input→expected vectors below are lifted from JabRef's own formatter tests
(JabRef, MIT License),
``jablib/src/test/java/org/jabref/logic/formatter/bibtexfields/``:
``NormalizeDateFormatterTest``, ``NormalizeMonthFormatterTest``,
``NormalizePagesFormatterTest``, ``LatexCleanupFormatterTest``,
``LatexToUnicodeFormatterTest``, ``NormalizeNamesFormatterTest``, and
``UnitsToLatexFormatterTest``.

Running JabRef itself in the suite would violate the determinism invariant (JVM,
version drift), so we capture JabRef's behavior as static golden data instead.
Parity is asserted at the field-value level — the only level where it is
meaningful, since JabRef rewrites whole files on save while pynakes preserves
them.
"""

import pytest

from pynakes.authors import normalize_name_list
from pynakes.bibtex_parser import parse_bib
from pynakes.formatters import (
    FIELD_FORMATTERS,
    capitalize,
    first_page,
    html_to_latex,
    html_to_unicode,
    last_page,
    latex_cleanup,
    latex_to_unicode,
    lower_case,
    normalize_date,
    normalize_month,
    normalize_page_numbers,
    ordinals_to_superscript,
    page_prefix,
    sentence_case,
    title_case,
    unicode_to_latex,
    upper_case,
)
from pynakes.normalize import normalize_library

# --- normalize_date --------------------------------------------------------

DATE_VECTORS = [
    ("2015-11-08", "2015-11-08"),
    ("2015-1-08", "2015-01-08"),
    ("2015-1-8", "2015-01-08"),
    ("2015-11", "2015-11"),
    ("2015-1", "2015-01"),
    ("11/15", "2015-11"),
    ("1/15", "2015-01"),
    ("01/15", "2015-01"),
    ("11/2015", "2015-11"),
    ("1/2015", "2015-01"),
    ("01/2015", "2015-01"),
    ("November 08, 2015", "2015-11-08"),
    ("November 8, 2015", "2015-11-08"),
    ("November, 2015", "2015-11"),
    ("08.11.2015", "2015-11-08"),
    ("8.11.2015", "2015-11-08"),
    ("15.11.2015", "2015-11-15"),
    ("08.01.2015", "2015-01-08"),
    ("8.01.2015", "2015-01-08"),
    ("15.01.2015", "2015-01-15"),
    ("08.1.2015", "2015-01-08"),
    ("8.1.2015", "2015-01-08"),
    ("15.1.2015", "2015-01-15"),
    ("29.11.2003", "2003-11-29"),  # getExampleInput()
    ("2020/2021", "2020/2021"),  # year range — kept
]


@pytest.mark.parametrize("value,expected", DATE_VECTORS)
def test_normalize_date_parity(value: str, expected: str) -> None:
    assert normalize_date(value) == expected


# --- normalize_month -------------------------------------------------------

MONTH_VECTORS = [
    ("December", "#dec#"),  # getExampleInput()
    ("#apr#", "#apr#"),
]


@pytest.mark.parametrize("value,expected", MONTH_VECTORS)
def test_normalize_month_parity(value: str, expected: str) -> None:
    assert normalize_month(value) == expected


# --- normalize_page_numbers ------------------------------------------------

PAGE_VECTORS = [
    ("1", "1"),
    ("1-2", "1--2"),
    ("1–2", "1--2"),  # en dash
    ("1—2", "1--2"),  # em dash
    ("1,2,3", "1,2,3"),
    ("43+", "43+"),
    ("   1  - 2 ", "1--2"),
    ("   1  ", "1"),
    ("   1 -- 2  ", "1--2"),
    ("43 -- 103", "43--103"),
    ("1--2", "1--2"),
    ("1---2", "1--2"),
    ("{1}-{2}", "1--2"),
    ("12", "12"),
    ("some-text", "some--text"),
    ("pages 1-50", "pages 1--50"),
    ("-43", "--43"),
    ("some-text-with-dashes", "some-text-with-dashes"),
    ("{A}", "{A}"),
    ("Invalid", "Invalid"),
    ("R1-R50", "R1--R50"),
    ("1 — 50", "1--50"),
    ("p.50", "50"),
    ("pp.50", "50"),
    ("40&50", "40&50"),
    ("2:1-2:33", "2:1--2:33"),
    ("2:1--2:33", "2:1--2:33"),
    ("1 - 2", "1--2"),  # getExampleInput()
    ("R404–R405", "R404--R405"),
]


@pytest.mark.parametrize("value,expected", PAGE_VECTORS)
def test_normalize_page_numbers_parity(value: str, expected: str) -> None:
    assert normalize_page_numbers(value) == expected


# --- firstpage / lastpage / pageprefix (citation-key page markers) ---------

PAGE_RANGE_VECTORS = [
    ("73--97", "73", "97", ""),
    ("7,41,73--97", "7", "97", ""),  # documented example: lowest/highest of all runs
    ("L7--L9", "7", "9", "L"),
    ("12", "12", "12", ""),
    ("", "", "", ""),
]


@pytest.mark.parametrize("value,first,last,prefix", PAGE_RANGE_VECTORS)
def test_page_marker_helpers_parity(value: str, first: str, last: str, prefix: str) -> None:
    assert first_page(value) == first
    assert last_page(value) == last
    assert page_prefix(value) == prefix


# --- latex_cleanup ---------------------------------------------------------

LATEX_CLEANUP_VECTORS = [
    ("$\\alpha$$\\beta$", "$\\alpha\\beta$"),
    ("{VLSI} {DSP}", "{VLSI DSP}"),
    ("\\textbf{VLSI} {DSP}", "\\textbf{VLSI} {DSP}"),
    (
        "A ${\\Delta}$${\\Sigma}$ modulator for {FPGA} {DSP}",
        "A ${\\Delta\\Sigma}$ modulator for {FPGA DSP}",
    ),
    ("%", "\\%"),
    ("\\%", "\\%"),
    ("50\\%", "50\\%"),
]


@pytest.mark.parametrize("value,expected", LATEX_CLEANUP_VECTORS)
def test_latex_cleanup_parity(value: str, expected: str) -> None:
    assert latex_cleanup(value) == expected


# --- latex_to_unicode ------------------------------------------------------

LATEX_TO_UNICODE_VECTORS = [
    ('{\\"{a}}', "ä"),
    ("{\\i}", "ı"),
    ("\\mbox{-}", "\\mbox{-}"),
    ("\\textit{text}", "𝑡𝑒𝑥𝑡"),
    ("\\$", "$"),
    ("$\\sigma$", "σ"),
    ("A 32~{mA} {$\\Sigma\\Delta$}-modulator", "A 32 mA ΣΔ-modulator"),
    ("$\\acute{\\omega}$", "ώ"),
    ("\\aaaa{bbbb}", "\\aaaa{bbbb}"),
    ("Lorem ipsum_lorem ipsum", "Lorem ipsum_lorem ipsum"),
    ("Lorem ipsum_{lorem ipsum}", "Lorem ipsum_(lorem ipsum)"),
    ("1\\textsuperscript{st}", "1ˢᵗ"),
]


@pytest.mark.parametrize("value,expected", LATEX_TO_UNICODE_VECTORS)
def test_latex_to_unicode_parity(value: str, expected: str) -> None:
    assert latex_to_unicode(value) == expected


# --- unicode_to_latex ------------------------------------------------------

UNICODE_TO_LATEX_VECTORS = [
    ("", ""),
    ("abc", "abc"),
    (r"{\aa}{\"{a}}{\"{o}}", "åäö"),
    (r"M{\"{o}}nch", "Mönch"),
    (r"{\i}", "ı"),
    (r"{\i} {\={\i}}", "ı ī"),
    (
        r"Pu{\d{n}}ya-pattana-vidy{\={a}}-p{\={\i}}{\d{t}}h{\={a}}dhi-k{\d{r}}tai{\d{h}} pr{\={a}}-ka{{\'{s}}}ya{\d{m}} n{\={\i}}ta{\d{h}}",
        "Puṇya-pattana-vidyā-pīṭhādhi-kṛtaiḥ prā-kaśyaṃ nītaḥ",
    ),
]


@pytest.mark.parametrize("expected,value", UNICODE_TO_LATEX_VECTORS)
def test_unicode_to_latex_parity(expected: str, value: str) -> None:
    assert unicode_to_latex(value) == expected


# --- html_to_latex ---------------------------------------------------------

HTML_TO_LATEX_VECTORS = [
    ("abc", "abc"),
    (
        "Towards situation-aware adaptive workflows: SitOPT --- A general purpose situation-aware workflow management system",
        "Towards situation-aware adaptive workflows: SitOPT &amp;#x2014; A general purpose situation-aware workflow management system",
    ),
    (r"{{\aa}}{\"{a}}{\"{o}}", "&aring;&auml;&ouml;"),
    (r"{\'{\i}}", "i&#x301;"),
    (r"{\"{a}}", "&auml;"),
    (r"{\"{a}}", "&#228;"),
    (r"{\"{a}}", "&#xe4;"),
    (r"{{$\Epsilon$}}", "&Epsilon;"),
    ("aaa", "<b>aaa</b>"),
    (r"\textsuperscript{k}\textsubscript{k}", "<sup>k</sup><sub>k</sub>"),
    ("(p < 0.01)", "(p < 0.01)"),
]


@pytest.mark.parametrize("expected,value", HTML_TO_LATEX_VECTORS)
def test_html_to_latex_parity(expected: str, value: str) -> None:
    assert html_to_latex(value) == expected


def test_html_to_latex_preserves_literal_dollar_pairs() -> None:
    assert html_to_latex("Cost: $$50") == "Cost: $$50"


# --- html_to_unicode -------------------------------------------------------

HTML_TO_UNICODE_VECTORS = [
    ("abc", "abc"),
    ("åäö", "&aring;&auml;&ouml;"),
    ("í", "i&#x301;"),
    ("Ε", "&Epsilon;"),
    ("ä", "&auml;"),
    ("ä", "&#228;"),
    ("ä", "&#xe4;"),
    ("ñ", "&#241;"),
    ("aaa", "<p>aaa</p>"),
    ("bread & butter", "<b>bread</b> &amp; butter"),
]


@pytest.mark.parametrize("expected,value", HTML_TO_UNICODE_VECTORS)
def test_html_to_unicode_parity(expected: str, value: str) -> None:
    assert html_to_unicode(value) == expected


# --- capitalize ------------------------------------------------------------

CAPITALIZE_VECTORS = [
    ("{}", "{}"),
    ("{upper", "{upper"),
    ("Upper", "upper"),
    ("Upper", "UPPER"),
    ("Upper Each First", "upper each first"),
    ("{U}pp{E}r", "{U}PP{E}R"),
    ("Upper Each {NOT} First", "upper each {NOT} first"),
    ("{N}ot {t}his", "{N}OT {t}his"),
    ("Upper-Each-First", "UPPER-EACH-FIRST"),
    ("{u}pper-Each-{f}irst", "{u}pper-each-{f}irst"),
    ("-Upper", "-upper"),
]


@pytest.mark.parametrize("expected,value", CAPITALIZE_VECTORS)
def test_capitalize_parity(expected: str, value: str) -> None:
    assert capitalize(value) == expected


# --- lower_case ------------------------------------------------------------

LOWER_CASE_VECTORS = [
    ("lower", "lower"),
    ("lower", "LOWER"),
    ("lower {UPPER}", "LOWER {UPPER}"),
    ("lower {U}pper", "LOWER {U}PPER"),
    ("kde {Amarok}", "KDE {Amarok}"),
]


@pytest.mark.parametrize("expected,value", LOWER_CASE_VECTORS)
def test_lower_case_parity(expected: str, value: str) -> None:
    assert lower_case(value) == expected


# --- upper_case ------------------------------------------------------------

UPPER_CASE_VECTORS = [
    ("LOWER", "LOWER"),
    ("UPPER", "upper"),
    ("UPPER {lower}", "upper {lower}"),
    ("UPPER {l}OWER", "upper {l}ower"),
    ("1", "1"),
    ("!", "!"),
    ("KDE {Amarok}", "Kde {Amarok}"),
]


@pytest.mark.parametrize("expected,value", UPPER_CASE_VECTORS)
def test_upper_case_parity(expected: str, value: str) -> None:
    assert upper_case(value) == expected


# --- sentence_case ---------------------------------------------------------

SENTENCE_CASE_VECTORS = [
    ("Upper first", "upper First"),
    ("Upper first", "uPPER FIRST"),
    ("Upper {NOT} first", "upper {NOT} FIRST"),
    ("Upper {N}ot first", "upper {N}OT FIRST"),
    (
        "Whose music? A sociology of musical language",
        "Whose music? a sociology of musical language",
    ),
    ("Bibliographic software. A comparison.", "bibliographic software. a comparison."),
    (
        "England’s monitor; The history of the separation",
        "England’s Monitor; the History of the Separation",
    ),
    (
        "Dr. schultz: a dentist turned bounty hunter.",
        "Dr. schultz: a dentist turned bounty hunter.",
    ),
    ("Wetting-and-drying", "wetting-and-drying"),
    ("Example case. {EXCLUDED SENTENCE.}", "Example case. {EXCLUDED SENTENCE.}"),
    ("I have {Aa} dream", "i have {Aa} DREAM"),
]


@pytest.mark.parametrize("expected,value", SENTENCE_CASE_VECTORS)
def test_sentence_case_parity(expected: str, value: str) -> None:
    assert sentence_case(value) == expected


# --- title_case ------------------------------------------------------------

TITLE_CASE_VECTORS = [
    ("Upper Each First", "upper each first"),
    ("An Upper Each of the and First And", "an upper each of the and first AND"),
    ("An Upper Each of: The and First And", "an upper each of: the and first and"),
    (
        "An Upper First with and without {CURLY} {brackets}",
        "AN UPPER FIRST WITH AND WITHOUT {CURLY} {brackets}",
    ),
    ("{b}rackets {b}rac{K}ets Brack{E}ts", "{b}RaCKeTS {b}RaC{K}eTS bRaCK{E}ts"),
    ("Bibliographic Software. A Comparison.", "bibliographic software. a comparison."),
    (
        "--Wetting-and-Drying M-U~L゠T︱I⁓P︲L--~~︲E Dash⸻-Like Characters",
        "--wetting-and-drying M-u~l゠t︱i⁓p︲l--~~︲e dASH⸻-likE charACTErs",
    ),
    ("{BPMN} Conformance in Open Source Engines", "{BPMN} conformance In open source Engines"),
]


@pytest.mark.parametrize("expected,value", TITLE_CASE_VECTORS)
def test_title_case_parity(expected: str, value: str) -> None:
    assert title_case(value) == expected


# --- ordinals_to_superscript -----------------------------------------------

ORDINAL_VECTORS = [
    (r"1\textsuperscript{st}", "1st"),
    (r"1\textsuperscript{ST}", "1ST"),
    (r"1\textsuperscript{sT}", "1sT"),
    (
        "replace on 1\\textsuperscript{st} line\nand on 2\\textsuperscript{nd} line.",
        "replace on 1st line\nand on 2nd line.",
    ),
    (
        r"1\textsuperscript{st} 2\textsuperscript{nd} 3\textsuperscript{rd} 4\textsuperscript{th}",
        "1st 2nd 3rd 4th",
    ),
    (
        r"1\textsuperscript{st} 1stword words1st inside1stwords",
        "1st 1stword words1st inside1stwords",
    ),
]


@pytest.mark.parametrize("expected,value", ORDINAL_VECTORS)
def test_ordinals_to_superscript_parity(expected: str, value: str) -> None:
    assert ordinals_to_superscript(value) == expected


# --- units_to_latex --------------------------------------------------------
#
# These vectors cover JabRef v5.15's unit spacing and non-breaking hyphen form.

UNITS_TO_LATEX_VECTORS = [
    (r"1~{A}", "1 A"),
    (r"1\mbox{-}{mA}", "1-mA"),
    (r"1~{Hz}", "1 Hz"),
]


@pytest.mark.parametrize("expected,value", UNITS_TO_LATEX_VECTORS)
def test_units_to_latex_parity(expected: str, value: str) -> None:
    formatter = FIELD_FORMATTERS["units_to_latex"]
    assert formatter(value) == expected


def test_formatters_registry_supports_lookup_extension_and_discovery() -> None:
    from pynakes.formatters._registry import FormattersRegistry

    registry = FormattersRegistry({"identity": lambda value: value})
    assert registry.get("identity") is not None
    assert registry.get("missing") is None
    assert "identity" in registry
    registry.register("upper", str.upper)
    assert registry.get("upper")("abc") == "ABC"  # type: ignore[misc]
    assert registry.names() == ["identity", "upper"]

    defaults = FormattersRegistry()
    assert "units_to_latex" in defaults


# --- normalize_names -------------------------------------------------------
#
# The names below cover JabRef's initials, affixes, brace protection, and
# legacy comma-separated-list cases.

NAME_VECTORS_OK = [
    ("{Society of Automotive Engineers}", "{Society of Automotive Engineers}"),
    ("Hans von Zimmer", "von Zimmer, Hans"),
    ("Staci Bilbo; Morten Alver", "Bilbo, Staci and Alver, Morten"),
    ("Staci Bilbo; Morten Alver; Test Name", "Bilbo, Staci and Alver, Morten and Name, Test"),
]

NAME_VECTORS = [
    ("Staci D Bilbo", "Bilbo, Staci D."),
    ("Smith SH", "Smith, S. H."),
    ("S Smith", "Smith, S."),
    ("SH Smith", "Smith, S. H."),
    ("Surname, jr, First, Surname2, First2", "Surname, jr, First and Surname2, First2"),
    # comma-separated multi-author lists (pynakes splits only on ';'/'and')
    (
        "Hans von Zimmer, Michael van Oberbergern, Kevin zu Berger",
        "von Zimmer, Hans and van Oberbergern, Michael and zu Berger, Kevin",
    ),
]


@pytest.mark.parametrize("value,expected", NAME_VECTORS_OK)
def test_normalize_names_parity_supported(value: str, expected: str) -> None:
    assert normalize_name_list(value) == expected


@pytest.mark.parametrize("value,expected", NAME_VECTORS)
def test_normalize_names_parity_extended(value: str, expected: str) -> None:
    assert normalize_name_list(value) == expected


# --- integration: saveActions drive the field formatters -------------------


def test_normalize_applies_saveactions_field_formatters() -> None:
    text = (
        "@comment{jabref-meta: saveActions:enabled;\n"
        "date[normalize_date]\nmonth[normalize_month]\npages[normalize_page_numbers]\n"
        "note[latex_cleanup]\nabstract[latex_to_unicode]\nkeywords[unicode_to_latex]\n"
        "title[html_to_latex]\ncomment[html_to_unicode]\n;}\n\n"
        "@article{A,\n"
        "  title = {T},\n"
        "  date = {8.1.2015},\n"
        "  month = {December},\n"
        "  pages = {1 - 2},\n"
        "  note = {{VLSI} {DSP}},\n"
        "  abstract = {$\\sigma$},\n"
        "  keywords = {Mönch},\n"
        "  title = {<b>html</b> &amp; &#x2014;},\n"
        "  comment = {<b>näive</b> &amp; &#241;}\n"
        "}\n"
    )
    lib = parse_bib(text)
    report = normalize_library(lib)

    entry = lib.entries["A"]
    assert entry.fields["date"] == "2015-01-08"
    assert entry.fields["month"] == "#dec#"
    assert entry.fields["pages"] == "1--2"
    assert entry.fields["note"] == "{VLSI DSP}"
    assert entry.fields["abstract"] == "σ"
    assert entry.fields["keywords"] == r"M{\"{o}}nch"
    assert entry.fields["title"] == "html & ---"
    assert entry.fields["comment"] == "näive & ñ"
    assert report.save_action_fields == 8


def test_normalize_skips_formatters_without_saveactions() -> None:
    # No saveActions → date/month are left untouched (no pynakes-meta or flag
    # drives them). ``pages`` is the exception: it has a built-in default step,
    # since ``--`` is the format's own convention rather than a preference.
    text = "@article{A,\n  title = {T},\n  date = {8.1.2015},\n  month = {December}\n}\n"
    lib = parse_bib(text)
    normalize_library(lib)
    assert lib.entries["A"].fields["date"] == "8.1.2015"
    assert lib.entries["A"].fields["month"] == "December"


def test_normalize_pages_defers_to_saveactions_when_configured() -> None:
    # The built-in pages step and the saveAction apply the identical formatter,
    # so a file configuring its own must not be counted (or done) twice.
    text = (
        "@comment{jabref-meta: saveActions:enabled;\npages[normalize_page_numbers]\n;}\n\n"
        "@article{A,\n  title = {T},\n  pages = {1 - 2}\n}\n"
    )
    lib = parse_bib(text)
    report = normalize_library(lib)
    assert lib.entries["A"].fields["pages"] == "1--2"
    assert report.save_action_fields == 1
    assert report.pages == 0


# ---------------------------------------------------------------------------
# Extra formatters (JabRef v5.15 completeness)
# ---------------------------------------------------------------------------

CLEAR_VECTORS = [
    ("any value", ""),
    ("", ""),
    ("{braced}", ""),
]


@pytest.mark.parametrize("input_val,expected", CLEAR_VECTORS)
def test_clear(input_val: str, expected: str) -> None:
    from pynakes.formatters import clear

    assert clear(input_val) == expected


ESCAPE_UNDERSCORES_VECTORS = [
    ("hello_world", r"hello\_world"),
    ("a_b_c", r"a\_b\_c"),
    ("a", "a"),
]


@pytest.mark.parametrize("input_val,expected", ESCAPE_UNDERSCORES_VECTORS)
def test_escape_underscores(input_val: str, expected: str) -> None:
    from pynakes.formatters import escape_underscores

    assert escape_underscores(input_val) == expected


ESCAPE_AMPERSANDS_VECTORS = [
    ("A & B", r"A \& B"),
    (r"already escaped \&", r"already escaped \&"),
    ("no ampersands", "no ampersands"),
]


@pytest.mark.parametrize("input_val,expected", ESCAPE_AMPERSANDS_VECTORS)
def test_escape_ampersands(input_val: str, expected: str) -> None:
    from pynakes.formatters import escape_ampersands

    assert escape_ampersands(input_val) == expected


CLEANUP_URL_VECTORS = [
    ("  https://example.com/path  ", "https://example.com/path"),
    ("<https://example.com/path>", "https://example.com/path"),
    ("{https://example.com/path}", "https://example.com/path"),
    ("https://example.com/path.", "https://example.com/path"),
    ("HTTPS://EXAMPLE.COM/path", "https://EXAMPLE.COM/path"),
    ("not a url.", "not a url."),
    ("{not a url.}", "{not a url.}"),
]


@pytest.mark.parametrize("input_val,expected", CLEANUP_URL_VECTORS)
def test_cleanup_url(input_val: str, expected: str) -> None:
    from pynakes.formatters import cleanup_url

    assert cleanup_url(input_val) == expected


REMOVE_BRACES_VECTORS = [
    ("{hello}", "hello"),
    ("{{nested}}", "{nested}"),
    ("no braces", "no braces"),
    ("{unbalanced", "{unbalanced"),
]


@pytest.mark.parametrize("input_val,expected", REMOVE_BRACES_VECTORS)
def test_remove_braces(input_val: str, expected: str) -> None:
    from pynakes.formatters import remove_braces

    assert remove_braces(input_val) == expected


UNPROTECT_TERMS_VECTORS = [
    ("{protected} word", "protected word"),
    ("word {protected}", "word protected"),
    ("{a} and {b}", "a and b"),
    ("no braces", "no braces"),
]


@pytest.mark.parametrize("input_val,expected", UNPROTECT_TERMS_VECTORS)
def test_unprotect_terms(input_val: str, expected: str) -> None:
    from pynakes.formatters import unprotect_terms

    assert unprotect_terms(input_val) == expected


MINIFY_NAME_LIST_VECTORS = [
    ("Smith  and  Jones", "Smith and Jones"),
    ("and Smith", "Smith"),
    ("Smith and ", "Smith"),
    ("Smith and Jones and Lee", "Smith and Jones and Lee"),
    ("Smith and and and Jones", "Smith and Jones"),
    ("{Barnes and Noble} and Smith", "{Barnes and Noble} and Smith"),
]


@pytest.mark.parametrize("input_val,expected", MINIFY_NAME_LIST_VECTORS)
def test_minify_name_list(input_val: str, expected: str) -> None:
    from pynakes.formatters import minify_name_list

    assert minify_name_list(input_val) == expected


def test_new_formatters_registered() -> None:
    """All new formatters are registered in FIELD_FORMATTERS."""
    expected = [
        "cleanup_url",
        "clear",
        "clean_up_doi",
        "escape_ampersands",
        "escape_underscores",
        "minify_name_list",
        "remove_braces",
        "unprotect_terms",
    ]
    for name in expected:
        assert name in FIELD_FORMATTERS, f"{name!r} not in FIELD_FORMATTERS"
