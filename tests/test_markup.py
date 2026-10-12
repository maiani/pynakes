"""Provider markup (MathML, JATS, HTML) in titles converts to LaTeX."""

import pytest

from pynakes._markup import comparable_title, has_markup, markup_to_latex
from pynakes.bibtex_parser import parse_bib
from pynakes.importer import prepare_imported_entry

# DOI content negotiation pretty-prints MathML on its own lines and turns the
# attribute quotes typographic; the formula below is the shape APS deposits.
MATHML_TITLE = """Spin Splitting in Layered
                    <mml:math xmlns:mml=“http://www.w3.org/1998/Math/MathML” display=“inline”>
                      <mml:mrow>
                        <mml:msub>
                          <mml:mrow>
                            <mml:mi>MnO</mml:mi>
                          </mml:mrow>
                          <mml:mrow>
                            <mml:mn>2</mml:mn>
                          </mml:mrow>
                        </mml:msub>
                      </mml:mrow>
                    </mml:math>
                    -Based Junctions"""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (MATHML_TITLE, "Spin Splitting in Layered MnO$_2$-Based Junctions"),
        ("On a Coherent\n   <i>LC</i>\n   Circuit", r"On a Coherent \textit{LC} Circuit"),
        (
            "A <mml:math><mml:mi>p</mml:mi></mml:math>-wave and "
            "<mml:math><mml:mi>κ</mml:mi></mml:math>-type state",
            r"A $p$-wave and $\kappa$-type state",
        ),
        (
            "Time <mml:math><mml:msub><mml:mi>T</mml:mi><mml:mn>1</mml:mn></mml:msub></mml:math>",
            "Time $T_1$",
        ),
        (
            "<mml:math><mml:msub><mml:mi>Fe</mml:mi><mml:mn>3</mml:mn></mml:msub>"
            "<mml:msub><mml:mi>O</mml:mi><mml:mn>4</mml:mn></mml:msub></mml:math> films",
            "Fe$_3$O$_4$ films",
        ),
        ("H<sub>2</sub>O and x<sup>2</sup>", "H$_2$O and x$^2$"),
        (
            "Gap <inline-formula><tex-math>$\\Delta$</tex-math></inline-formula> in "
            "<italic>situ</italic>",
            r"Gap $\Delta$ in \textit{situ}",
        ),
    ],
)
def test_markup_to_latex(value: str, expected: str) -> None:
    assert markup_to_latex(value) == expected


def test_values_without_markup_are_untouched() -> None:
    for value in ("a < b and c > d", "Plain  title", "{RuO$_2$} films"):
        assert not has_markup(value)
        assert markup_to_latex(value) == value


def test_comparable_title_ignores_markup_conventions() -> None:
    local = "Spin Splitting in Layered {MnO$_{2}$}-Based Junctions"
    assert comparable_title(MATHML_TITLE) == comparable_title(local)


def test_doi_import_converts_mathml_title() -> None:
    bibtex = (
        "@article{Doe_2024, title={" + MATHML_TITLE + "}, author={Doe, Jane},"
        " journal={Journal of Tests}, year={2024}, DOI={10.5555/markup}}"
    )
    entry = prepare_imported_entry(parse_bib(""), "10.5555/markup", fetcher=lambda doi: bibtex)
    assert entry.fields["title"] == "Spin Splitting in Layered MnO$_2$-Based Junctions"


def test_verify_compares_titles_across_provider_markup(monkeypatch) -> None:
    from pynakes.integrity import verify_library
    from pynakes.providers.metadata import doi

    provider = "@article{X, title={" + MATHML_TITLE + "}, author={Doe, Jane}, year={2024}}"
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: provider)
    lib = parse_bib(
        "@article{A,\n  author = {Doe, Jane},\n"
        "  title = {Spin Splitting in Layered {MnO$_2$}-Based Junctions},\n"
        "  year = {2024},\n  doi = {10.5555/markup}\n}\n"
    )
    assert verify_library(lib, online=True).issues == []


def test_verify_title_mismatch_message_shows_both_titles(monkeypatch) -> None:
    from pynakes.integrity import verify_library
    from pynakes.providers.metadata import doi

    provider = "@article{X, title={On <i>Something</i> Else}, author={Doe, Jane}, year={2024}}"
    monkeypatch.setattr(doi, "fetch_bibtex", lambda d: provider)
    lib = parse_bib(
        "@article{A,\n  author = {Doe, Jane},\n  title = {A Wrong Title},\n"
        "  year = {2024},\n  doi = {10.5555/markup}\n}\n"
    )
    (issue,) = verify_library(lib, online=True).issues
    assert issue.type == "title_mismatch"
    assert issue.expected == r"On \textit{Something} Else"
    assert "'A Wrong Title'" in issue.message and r"\\textit{Something}" in issue.message
    assert "ref compare A" in issue.message


MARKUP_LIBRARY = (
    "@article{A,\n  author = {Doe, Jane},\n"
    "  title = {On a Coherent <i>LC</i> Circuit},\n  journal = {Journal of Tests},\n"
    "  year = {2024}\n}\n"
)


def test_lint_reports_title_markup() -> None:
    from pynakes.lint import lint

    issues = [issue for issue in lint(parse_bib(MARKUP_LIBRARY)) if issue.type == "title_markup"]
    assert [(issue.key, issue.field, issue.category) for issue in issues] == [
        ("A", "title", "content")
    ]


def test_normalize_converts_title_markup_before_protection() -> None:
    from pynakes.normalize import NormalizeOptions, normalize_library

    lib = parse_bib(MARKUP_LIBRARY)
    report = normalize_library(lib, NormalizeOptions(protect_titles=True))
    # A brace group is already case-protected; protection adds nothing inside it.
    assert lib.entries["A"].fields["title"] == r"On a Coherent \textit{LC} Circuit"
    assert report.title_markup == 1

    lib = parse_bib(MARKUP_LIBRARY)
    normalize_library(lib, NormalizeOptions(protect_titles=False))
    assert lib.entries["A"].fields["title"] == r"On a Coherent \textit{LC} Circuit"
