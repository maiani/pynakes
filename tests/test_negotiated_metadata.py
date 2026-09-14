"""Tests for repairs to registrar-rendered BibTeX from DOI content negotiation.

The inputs below are shaped exactly like the responses ``https://doi.org`` hands
back for the relevant DOI prefixes: DataCite's arXiv rendering, and Crossref's
for books and chapters.
"""

from pynakes.providers.metadata.doi import parse_bibtex

# DataCite renders some arXiv deposits @article and others @misc, upper-cases
# the DOI, and repeats a keyword verbatim.
ARXIV_AS_ARTICLE = """@article{https://doi.org/10.48550/arxiv.quant-ph/9807006,
  doi = {10.48550/ARXIV.QUANT-PH/9807006},
  url = {https://arxiv.org/abs/quant-ph/9807006},
  author = {Lovelace, Ada},
  keywords = {Quantum Physics (quant-ph), FOS: Physical sciences, FOS: Physical sciences},
  title = {On a Representation of Analytical Engines},
  publisher = {arXiv},
  year = {1843}
}
"""

ARXIV_AS_MISC = """@misc{https://doi.org/10.48550/arxiv.1906.05836,
  doi = {10.48550/ARXIV.1906.05836},
  url = {https://arxiv.org/abs/1906.05836},
  author = {Babbage, Charles},
  keywords = {Quantum Physics (quant-ph), FOS: Physical sciences},
  title = {A Difference Engine},
  publisher = {arXiv},
  year = {1822}
}
"""

# Crossref renders a reference-book as @misc: no container, but an ISBN and a
# publisher.
REFERENCE_BOOK = (
    "@misc{Euclid_300, title={Elements}, ISBN={9781439865057}, "
    "DOI={10.5555/elements}, publisher={Alexandria Press}, "
    "author={Euclid}, year={300} }"
)

# A book chapter, also @misc, carrying its *book* title in `journal` and an
# en-dash page range.
BOOK_CHAPTER = (
    "@misc{Gauss_1801, title={On Congruences}, ISBN={9780521678544}, "
    "DOI={10.5555/chapter}, journal={Disquisitiones Arithmeticae}, "
    "publisher={Göttingen Press}, author={Gauss, Carl Friedrich}, "
    "year={1801}, pages={3–56} }"
)


def test_arxiv_deposits_normalize_to_one_entry_type() -> None:
    # The whole point: the same source and DOI shape must not yield two types,
    # one of which fails pynakes' own lint for want of a journal.
    as_article = parse_bibtex(ARXIV_AS_ARTICLE, "10.48550/arXiv.quant-ph/9807006")
    as_misc = parse_bibtex(ARXIV_AS_MISC, "10.48550/arXiv.1906.05836")

    assert as_article.entry_type == "misc"
    assert as_misc.entry_type == "misc"


def test_arxiv_import_records_eprint_provenance() -> None:
    metadata = parse_bibtex(ARXIV_AS_ARTICLE, "10.48550/arXiv.quant-ph/9807006")

    assert metadata.fields["eprint"] == "quant-ph/9807006"
    assert metadata.fields["archivePrefix"] == "arXiv"
    assert metadata.fields["primaryClass"] == "quant-ph"


def test_arxiv_eprint_uses_the_correctly_cased_legacy_identifier() -> None:
    # The DOI arrives upper-cased; a legacy arXiv id's archive name is
    # case-sensitive, so the id is recovered from `url` in preference.
    metadata = parse_bibtex(ARXIV_AS_ARTICLE, "10.48550/arXiv.quant-ph/9807006")

    assert metadata.fields["eprint"] == "quant-ph/9807006"
    assert metadata.fields["doi"] == "10.48550/arXiv.quant-ph/9807006"


def test_arxiv_import_uses_biblatex_field_names_for_a_biblatex_library() -> None:
    metadata = parse_bibtex(ARXIV_AS_MISC, "10.48550/arXiv.1906.05836", dialect="biblatex")

    assert metadata.entry_type == "online"
    assert metadata.fields["eprinttype"] == "arxiv"
    assert metadata.fields["eprintclass"] == "quant-ph"
    assert "archivePrefix" not in metadata.fields


def test_repeated_keywords_are_dropped_once() -> None:
    metadata = parse_bibtex(ARXIV_AS_ARTICLE, "10.48550/arXiv.quant-ph/9807006")

    assert metadata.fields["keywords"] == "Quantum Physics (quant-ph), FOS: Physical sciences"


def test_keyword_order_is_preserved_when_deduplicating() -> None:
    text = "@misc{k, keywords = {Zeta, Alpha, Zeta, Beta}, DOI={10.5555/k}}"

    metadata = parse_bibtex(text, "10.5555/k")

    assert metadata.fields["keywords"] == "Zeta, Alpha, Beta"


def test_reference_book_becomes_a_book() -> None:
    metadata = parse_bibtex(REFERENCE_BOOK, "10.5555/elements")

    assert metadata.entry_type == "book"


def test_book_chapter_becomes_an_incollection_with_a_booktitle() -> None:
    metadata = parse_bibtex(BOOK_CHAPTER, "10.5555/chapter")

    assert metadata.entry_type == "incollection"
    assert metadata.fields["booktitle"] == "Disquisitiones Arithmeticae"
    # The container must not also remain in `journal`, which is where the
    # registrar put it and where book styles never look.
    assert "journal" not in metadata.fields


def test_en_dash_page_ranges_are_rewritten_on_import() -> None:
    metadata = parse_bibtex(BOOK_CHAPTER, "10.5555/chapter")

    assert metadata.fields["pages"] == "3--56"


def test_a_plain_journal_article_is_left_alone() -> None:
    text = (
        "@article{Bernoulli_1738, title={Hydrodynamica}, journal={Acta Eruditorum}, "
        "DOI={10.5555/hydro}, author={Bernoulli, Daniel}, year={1738}, pages={12--34} }"
    )

    metadata = parse_bibtex(text, "10.5555/hydro")

    assert metadata.entry_type == "article"
    assert metadata.fields["journal"] == "Acta Eruditorum"
    assert metadata.fields["pages"] == "12--34"


def test_an_untyped_record_with_no_evidence_stays_misc() -> None:
    text = "@misc{Anon, title={A Note}, DOI={10.5555/note}, author={Anon}, year={1900} }"

    metadata = parse_bibtex(text, "10.5555/note")

    assert metadata.entry_type == "misc"


def test_a_biblatex_library_imports_an_arxiv_doi_in_biblatex_shape(tmp_path) -> None:
    # The DOI import path is the one route that never consulted the library's
    # own dialect; it did not matter until imports began emitting eprint fields.
    from pynakes.bibtex_parser import parse_bib
    from pynakes.importer import prepare_imported_entry

    lib = parse_bib("@comment{pynakes-meta: dialect:biblatex;}\n")

    entry = prepare_imported_entry(
        lib, "10.48550/arXiv.1906.05836", fetcher=lambda doi: ARXIV_AS_MISC
    )

    assert entry.type == "online"
    assert entry.fields["eprinttype"] == "arxiv"
    assert "archivePrefix" not in entry.fields


def test_a_chapter_without_an_editor_is_inbook_in_biblatex() -> None:
    # BibLaTeX requires `editor` on @incollection and Crossref rarely supplies
    # one, so claiming @incollection there would just trade one lint error for
    # another. @inbook asserts less and is satisfied by what the record has.
    metadata = parse_bibtex(BOOK_CHAPTER, "10.5555/chapter", dialect="biblatex")

    assert metadata.entry_type == "inbook"
    assert metadata.fields["booktitle"] == "Disquisitiones Arithmeticae"


def test_a_chapter_with_an_editor_stays_incollection_in_biblatex() -> None:
    text = BOOK_CHAPTER.replace("year={1801}", "editor={Nowakowski, Richard}, year={1801}")

    metadata = parse_bibtex(text, "10.5555/chapter", dialect="biblatex")

    assert metadata.entry_type == "incollection"


def test_every_refined_import_passes_lint() -> None:
    # The rule this module exists to uphold: never emit an entry that fails
    # pynakes' own validator on import.
    from pynakes.bibtex_parser import parse_bib
    from pynakes.importer import entry_from_metadata
    from pynakes.lint import lint

    records = {
        "10.48550/arXiv.quant-ph/9807006": ARXIV_AS_ARTICLE,
        "10.48550/arXiv.1906.05836": ARXIV_AS_MISC,
        "10.5555/elements": REFERENCE_BOOK,
        "10.5555/chapter": BOOK_CHAPTER,
    }
    dialects = (("bibtex", ""), ("biblatex", "@comment{pynakes-meta: dialect:biblatex;}\n"))
    for dialect, meta in dialects:
        for doi_value, text in records.items():
            entry = entry_from_metadata(parse_bibtex(text, doi_value, dialect=dialect))
            entry.key = "Imported"
            lib = parse_bib(meta)
            lib.entries["Imported"] = entry
            bad = [i for i in lint(lib) if i.severity in ("error", "warning")]
            assert bad == [], f"{dialect} {doi_value}: {[i.message for i in bad]}"
