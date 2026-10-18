"""``coauthors``: the co-authorship network, its ego view, variants, and documents."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pynakes._analysis_people import entry_people
from pynakes._coauthor_variants import classify, name_parts, plain_letters
from pynakes.analysis import analyze
from pynakes.cli import app
from pynakes.coauthors import (
    DEFAULT_MAX_AUTHORS,
    SCHEMA,
    UnknownAuthorError,
    coauthor_network,
    library_max_authors,
)
from pynakes.engine import Bibliography
from pynakes.model import BibEntry

runner = CliRunner()

LIBRARY = r"""@article{BornJordan1925,
  author = {Born, M. and Jordan, P.},
  title = {Zur Quantenmechanik},
  year = {1925}
}

@article{BornHeisenbergJordan1926,
  author = {Max Born and Werner Heisenberg and Pascual Jordan},
  title = {Zur Quantenmechanik II},
  year = {1926}
}

@article{BornWiener1926,
  author = {Born, Max and Wiener, Norbert},
  title = {Eine neue Formulierung der Quantengesetze},
  year = {1926}
}

@article{Heisenberg1927,
  author = {Heisenberg, Werner and others},
  title = {Ueber den anschaulichen Inhalt},
  date = {1927-03}
}

@article{EPR1935,
  author = {Einstein, A. and Podolsky, B. and Rosen, N.},
  title = {Can Quantum-Mechanical Description of Physical Reality Be Considered Complete?},
  year = {1935}
}

@article{Einstein1905,
  author = {Albert Einstein},
  title = {Zur Elektrodynamik bewegter Koerper},
  year = {1905}
}

@article{Schrodinger1926,
  author = {Schr{\"o}dinger, Erwin},
  title = {Quantisierung als Eigenwertproblem},
  year = {1926}
}

@article{SchrodingerBorn,
  author = {Schrödinger, Erwin and Born, Max},
  title = {An undated note}
}

@article{Curie1898,
  author = {Curie, Pierre and Curie, Marie and B{\'e}mont, G.},
  author+an:orcid = {1="0000-0002-1825-0097"; 4="not an orcid"},
  title = {Sur une nouvelle substance fortement radio-active},
  year = {1898}
}

@misc{Anonymous1900,
  title = {A record without authors},
  year = {1900}
}
"""


def _bib(tmp_path: Path, text: str = LIBRARY) -> Path:
    path = tmp_path / "lib.bib"
    path.write_text(text, encoding="utf-8")
    return path


def _network(text: str = LIBRARY, **kwargs):
    return coauthor_network(Bibliography.from_text(text).lib.entries.values(), **kwargs)


def _json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    assert "Traceback" not in result.output
    return result.exit_code, json.loads(result.output)


def _author(network, name: str) -> dict:
    return next(item for item in network.authors if item["name"] == name)


def _pair(network, a: str, b: str) -> dict:
    return next(item for item in network.pairs if item["authors"] == sorted([a, b]))


# --- the network -----------------------------------------------------------------


def test_people_reconcile_with_the_authors_section() -> None:
    coll = Bibliography.from_text(LIBRARY)
    sections = analyze(coll, sections=["authors", "coauthors"], top=100).sections
    network = coauthor_network(coll.lib.entries.values())

    assert network.summary["authors"] == sections["authors"]["distinct"] == 15
    assert network.entries["with_authors"] == sections["authors"]["entries_with_authors"] == 9
    assert network.entries["with_others"] == sections["authors"]["entries_with_others"] == 1
    counted = {item["name"]: item["entries"] for item in sections["authors"]["top"]}
    assert {item["name"]: item["entries"] for item in network.authors} == counted


def test_entry_counts_reconcile() -> None:
    entries = _network().entries

    assert entries == {
        "total": 10,
        "with_authors": 9,
        "without_authors": 1,
        "single_author": 3,
        "coauthored": 6,
        "with_others": 1,
        "over_max_authors": 0,
    }


def test_pairs_carry_counts_years_and_keys() -> None:
    network = _network()

    # "Max Born" and "Born, Max" are one person, as in the authors section.
    born = _author(network, "Born, Max")
    assert born["entries"] == 3 and born["collaborators"] == 4
    assert born["spellings"] == ["Born, Max", "Max Born"]
    assert (born["first_year"], born["last_year"], born["undated"]) == ("1926", "1926", 1)
    assert _pair(network, "Born, Max", "Heisenberg, Werner") == {
        "authors": ["Born, Max", "Heisenberg, Werner"],
        "entries": 1,
        "first_year": "1926",
        "last_year": "1926",
        "undated": 0,
        "keys": ["BornHeisenbergJordan1926"],
    }
    assert _pair(network, "Born, Max", "Schrödinger, Erwin")["undated"] == 1
    assert network.summary["pairs"] == len(network.pairs) == 12
    # Most shared entries first, then alphabetical.
    assert [pair["entries"] for pair in network.pairs] == sorted(
        (pair["entries"] for pair in network.pairs), reverse=True
    )


def test_others_links_only_the_listed_authors() -> None:
    network = _network()
    heisenberg = _author(network, "Heisenberg, Werner")

    assert heisenberg["entries"] == 2 and heisenberg["entries_with_others"] == 1
    assert heisenberg["collaborators"] == 2
    assert not any("others" in pair["authors"] for pair in network.pairs)


def test_components_partition_the_entries_with_authors() -> None:
    network = _network()
    components = network.components

    assert sum(item["entries"] for item in components) == network.entries["with_authors"]
    assert sum(item["size"] for item in components) == network.summary["authors"]
    assert components[0] == {
        "id": 0,
        "size": 5,
        "entries": 4,
        "authors": [
            "Born, Max",
            "Heisenberg, Werner",
            "Jordan, Pascual",
            "Schrödinger, Erwin",
            "Wiener, Norbert",
        ],
    }
    assert [item["size"] for item in components] == [5, 3, 3, 2, 1, 1]
    assert network.summary["isolated_authors"] == 2
    assert _author(network, "Einstein, Albert")["component"] == 4


def test_duplicate_keys_are_counted_as_separate_entries() -> None:
    text = (
        "@article{Same, author = {Born, Max and Wiener, Norbert}, year = {1926}}\n"
        "@article{Same, author = {Born, Max and Wiener, Norbert}, year = {1927}}\n"
    )
    pair = _network(text).pairs[0]

    assert pair["entries"] == 2 and pair["keys"] == ["Same", "Same"]
    assert (pair["first_year"], pair["last_year"]) == ("1926", "1927")


def test_an_empty_selection() -> None:
    network = _network("")

    assert network.summary == {
        "authors": 0,
        "pairs": 0,
        "components": 0,
        "largest_component": 0,
        "isolated_authors": 0,
        "variant_candidates": 0,
    }
    assert network.to_dict()["schema"] == SCHEMA


def test_output_is_deterministic() -> None:
    assert _network().to_dict() == _network().to_dict()
    assert _network().to_graphml() == _network().to_graphml()


# --- large author lists ---------------------------------------------------------

BIG = (
    "@article{Big, author = {%s}, year = {2012}}\n"
    % " and ".join(f"Member, A{n:03d}" for n in range(5))
    + "@article{Small, author = {Member, A000 and Born, Max}, year = {2013}}\n"
)


def test_large_author_lists_count_authors_but_are_not_linked() -> None:
    network = _network(BIG, max_authors=4)

    assert network.summary["authors"] == 6
    assert network.entries["over_max_authors"] == 1
    assert network.unlinked_keys == ["Big"]
    assert [pair["authors"] for pair in network.pairs] == [["Born, Max", "Member, A000"]]
    member = _author(network, "Member, A000")
    assert member["entries"] == 2 and member["unlinked_entries"] == 1
    assert member["collaborators"] == 1
    # Components count only linked entries, so they still partition them.
    assert sum(item["entries"] for item in network.components) == 1
    (warning,) = network.warnings
    assert warning["type"] == "large_author_lists" and warning["keys"] == ["Big"]


def test_zero_links_every_entry() -> None:
    network = _network(BIG, max_authors=0)

    assert network.unlinked_keys == [] and network.summary["pairs"] == 11
    with pytest.raises(ValueError):
        _network(BIG, max_authors=-1)


def test_the_limit_is_a_library_setting_the_flag_overrides(tmp_path: Path) -> None:
    text = "@comment{pynakes-meta:\ncoauthors-max-authors: 4\n}\n\n" + BIG
    bib = _bib(tmp_path, text)

    assert library_max_authors(Bibliography.open(bib).lib) == 4
    assert library_max_authors(Bibliography.from_text(BIG).lib) == DEFAULT_MAX_AUTHORS
    _code, stored = _json("coauthors", str(bib))
    _code, flag = _json("coauthors", str(bib), "--max-authors", "0")
    _code, analyzed = _json("analyze", str(bib), "--section", "coauthors")
    _code, overridden = _json("analyze", str(bib), "--section", "coauthors", "--max-authors", "10")
    negative = _json("coauthors", str(bib), "--max-authors", "-1")

    assert stored["network"]["max_authors"] == 4 and stored["network"]["unlinked_keys"] == ["Big"]
    assert flag["network"]["max_authors"] == 0 and flag["network"]["unlinked_keys"] == []
    assert analyzed["sections"]["coauthors"]["entries_over_max_authors"] == 1
    assert overridden["sections"]["coauthors"]["entries_over_max_authors"] == 0
    assert negative[0] == 1 and negative[1]["error"] == "InvalidInput"


def test_the_setting_is_validated(tmp_path: Path) -> None:
    bib = _bib(tmp_path, BIG)

    code, payload = _json("metadata", "set", str(bib), "coauthors-max-authors", "25")
    refused = _json("metadata", "set", str(bib), "coauthors-max-authors", "many")

    assert code == 0, payload
    assert "coauthors-max-authors: 25" in bib.read_text(encoding="utf-8")
    assert refused[0] == 1
    bib.write_text("@comment{pynakes-meta:\ncoauthors-max-authors: -3\n}\n\n" + BIG)
    _code, linted = _json("lint", str(bib))
    assert any("coauthors-max-authors" in issue["message"] for issue in linted["issues"])
    assert _json("coauthors", str(bib))[1]["error"] == "InvalidInput"


# --- ego view --------------------------------------------------------------------


def test_focus_keeps_the_collaborators_and_the_pairs_among_them() -> None:
    network = _network(focus=["Max Born"])

    assert network.focus == [{"requested": "Max Born", "name": "Born, Max"}]
    names = {item["name"] for item in network.authors}
    assert names == {
        "Born, Max",
        "Heisenberg, Werner",
        "Jordan, Pascual",
        "Wiener, Norbert",
        "Schrödinger, Erwin",
    }
    # Heisenberg and Jordan worked together; that link is part of the view.
    assert _pair(network, "Heisenberg, Werner", "Jordan, Pascual")["entries"] == 1
    assert all(set(pair["authors"]) <= names for pair in network.pairs)
    heisenberg = _author(network, "Heisenberg, Werner")
    assert heisenberg["with_focus"] == 1
    assert heisenberg["with_focus_keys"] == ["BornHeisenbergJordan1926"]
    assert heisenberg["entries"] == 2  # counts stay those of the whole selection
    assert _author(network, "Born, Max")["focus"] is True


def test_focus_components_leave_the_focus_out() -> None:
    network = _network(focus=["Born, Max"])

    assert _author(network, "Born, Max")["component"] is None
    assert [item["authors"] for item in network.components] == [
        ["Heisenberg, Werner", "Jordan, Pascual"],
        ["Schrödinger, Erwin"],
        ["Wiener, Norbert"],
    ]
    assert network.summary["isolated_authors"] == 2


def test_focus_warns_about_other_spellings_of_the_focus() -> None:
    network = _network(focus=["Born, Max"])

    warning = next(item for item in network.warnings if item["type"] == "focus_variants")
    assert warning["name"] == "Born, Max" and warning["variants"] == ["Born, M."]


def test_several_focus_names_form_one_view() -> None:
    network = _network(focus=["Born, Max", "Born, M."])

    names = {item["name"] for item in network.authors}
    assert {"Jordan, P.", "Jordan, Pascual", "Wiener, Norbert"} <= names
    assert _author(network, "Born, M.")["focus"] is True
    # Each spelling is a focus name, so neither is reported as a missing variant.
    assert not [item for item in network.warnings if item["type"] == "focus_variants"]


def test_an_unlisted_focus_name_is_refused_with_candidates() -> None:
    with pytest.raises(UnknownAuthorError) as raised:
        _network(focus=["Heisenberg, W."])

    assert raised.value.candidates == ["Heisenberg, Werner"]
    with pytest.raises(UnknownAuthorError) as raised:
        _network(focus=["Nobody, Ann"])
    assert raised.value.candidates == []


# --- name variants ---------------------------------------------------------------


def _reasons(left: str, right: str) -> list[str]:
    a, b = name_parts(left), name_parts(right)
    assert a is not None and b is not None
    return classify(a, b)


@pytest.mark.parametrize(
    ("left", "right", "reasons"),
    [
        ('Schr{\\"o}dinger, Erwin', "Schrödinger, Erwin", ["spelling"]),
        ("Born, M.", "Born, Max", ["initials"]),
        ("Born, Max", "Born, Max E.", ["extra_given_names"]),
        ("Born, M.", "Born, Max E.", ["initials", "extra_given_names"]),
        ("Born", "Born, Max", ["given_missing"]),
        ("Cajal, Santiago Ramón", "Ramón Cajal, Santiago", ["family_split"]),
        ("Cajal, S. Ramón", "Ramón Cajal, Santiago", ["family_split", "initials"]),
        ("Curie, Pierre", "Curie, Marie", []),
        ("Born, Max", "Wiener, Max", []),
        ("Cajal, Santiago Ramón", "Ramón, S.", []),
    ],
)
def test_variant_reasons(left: str, right: str, reasons: list[str]) -> None:
    assert _reasons(left, right) == reasons


def test_tex_accents_and_diacritics_compare_as_letters() -> None:
    assert plain_letters("{\\.{Z}}ywiec") == plain_letters("Żywiec") == "zywiec"
    assert plain_letters("{\\O}rsted") == "orsted"
    assert plain_letters("Gau{\\ss}") == "gauss"
    assert name_parts("{World Bank}") is None


def test_variants_are_listed_never_merged() -> None:
    network = _network()
    found = {tuple(item["names"]): item for item in network.variants}

    assert set(found) == {
        ("Born, M.", "Born, Max"),
        ("Einstein, A.", "Einstein, Albert"),
        ("Jordan, P.", "Jordan, Pascual"),
        ('Schr{\\"o}dinger, Erwin', "Schrödinger, Erwin"),
    }
    born = found[("Born, M.", "Born, Max")]
    assert born["reasons"] == ["initials"] and born["evidence_against"] == []
    assert born["entries"][0] == {"name": "Born, M.", "entries": 1, "keys": ["BornJordan1925"]}
    # Both stay separate authors.
    assert _author(network, "Born, M.")["entries"] == 1


def test_co_listed_names_carry_evidence_against() -> None:
    text = "@article{A, author = {Born, Max and Born, M. E.}, year = {1950}}\n"
    (variant,) = _network(text).variants

    assert variant["reasons"] == ["initials", "extra_given_names"]
    assert variant["evidence_against"] == ["co_listed"]


def test_orcid_annotations_are_identity_evidence() -> None:
    text = (
        "@article{A, author = {Wiener, Norbert}, year = {1920},\n"
        '  author+an:orcid = {1="0000-0002-1825-0097"}}\n'
        "@article{B, author = {Wiener, N. and Born, Max}, year = {1926},\n"
        '  author+an:orcid = {1="https://orcid.org/0000-0001-5109-3700"}}\n'
        "@article{C, author = {Norbert Wiener-Smith}, year = {1930},\n"
        '  author+an:orcid = {1="0000-0002-1825-0097"}}\n'
    )
    network = _network(text)
    found = {tuple(item["names"]): item for item in network.variants}

    assert found[("Wiener, N.", "Wiener, Norbert")]["evidence_against"] == ["different_orcid"]
    assert found[("Wiener, Norbert", "Wiener-Smith, Norbert")]["reasons"] == ["same_orcid"]
    assert _author(network, "Wiener, N.")["orcids"] == ["0000-0001-5109-3700"]


def test_unreadable_orcid_items_are_warnings() -> None:
    network = _network()

    (warning,) = [item for item in network.warnings if item["type"] == "invalid_orcid_annotation"]
    assert warning["key"] == "Curie1898" and warning["items"] == ['4="not an orcid"']
    assert _author(network, "Curie, Pierre")["orcids"] == ["0000-0002-1825-0097"]


def test_entry_people_lists_each_person_once() -> None:
    entry = BibEntry(
        type="article", key="A", fields={"author": "Born, Max and Max Born and et al."}
    )
    people = entry_people(entry)

    assert people.keys == ["born, max"] and people.others


# --- documents -------------------------------------------------------------------


def test_graphml_is_a_weighted_undirected_graph() -> None:
    network = _network(focus=["Born, Max"])
    root = ET.fromstring(network.to_graphml())
    ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
    graph = root.find("g:graph", ns)
    assert graph is not None and graph.get("edgedefault") == "undirected"

    labels = {
        node.get("id"): node.find("g:data[@key='label']", ns).text  # type: ignore[union-attr]
        for node in graph.findall("g:node", ns)
    }
    assert len(labels) == network.summary["authors"]
    edges = graph.findall("g:edge", ns)
    assert len(edges) == network.summary["pairs"]
    first = edges[0]
    weight = first.find("g:data[@key='weight']", ns)
    assert weight is not None and int(weight.text or 0) == network.pairs[0]["entries"]
    assert sorted([labels[first.get("source")], labels[first.get("target")]]) == sorted(
        network.pairs[0]["authors"]
    )
    assert root.find("g:key[@id='focus']", ns) is not None


def test_markdown_has_one_table_per_list() -> None:
    text = _network(focus=["Born, Max"]).to_markdown("Born's co-authors")

    assert text.startswith("# Born's co-authors\n")
    for heading in ("## Focus", "## Authors", "## Pairs", "## Components"):
        assert heading in text
    assert "| Heisenberg, Werner | 1 | 0 | BornHeisenbergJordan1926 |" in text
    assert "| Born, M. / Born, Max | initials |  | 1 / 3 |" in text


# --- CLI ---------------------------------------------------------------------------


def test_cli_envelope_carries_the_network(tmp_path: Path) -> None:
    bib = _bib(tmp_path)
    code, payload = _json("coauthors", str(bib))

    assert code == 0 and payload["action"] == "coauthors"
    assert payload["selection"] == {"where": None, "keys": None, "entries": 10}
    assert payload["network"]["schema"] == SCHEMA
    assert payload["network"]["summary"]["authors"] == 15
    assert {item["type"] for item in payload["warnings"]} == {"invalid_orcid_annotation"}


def test_cli_where_slices_by_year(tmp_path: Path) -> None:
    bib = _bib(tmp_path)
    code, payload = _json("coauthors", str(bib), "--where", "year >= 1926 and year < 1930")

    assert code == 0 and payload["selection"]["entries"] == 4
    network = payload["network"]
    assert network["entries"]["with_others"] == 1
    assert "Born, M." not in {item["name"] for item in network["authors"]}


def test_cli_key_selection_and_unknown_keys(tmp_path: Path) -> None:
    bib = _bib(tmp_path)
    code, payload = _json("coauthors", str(bib), "--key", "EPR1935")
    missing = _json("coauthors", str(bib), "--key", "Nobody2000")

    assert code == 0 and payload["network"]["summary"]["pairs"] == 3
    assert missing[0] == 1 and missing[1]["error"] == "KeyNotFound"


def test_cli_unknown_focus_lists_candidates(tmp_path: Path) -> None:
    code, payload = _json("coauthors", str(_bib(tmp_path)), "--focus", "Jordan, Paul")

    assert code == 1 and payload["error"] == "InvalidInput"
    assert payload["candidates"] == ["Jordan, P.", "Jordan, Pascual"]


def test_cli_human_summary(tmp_path: Path) -> None:
    result = runner.invoke(app, ["coauthors", str(_bib(tmp_path)), "--focus", "Max Born"])

    assert result.exit_code == 0
    assert "15 authors" not in result.output  # the ego view is smaller
    assert "focus: Born, Max" in result.output
    assert "  Heisenberg, Werner: 1 shared" in result.output
    assert "warning: Focus 'Born, Max' has possible name variants (Born, M.)" in result.output


@pytest.mark.parametrize("fmt", ["json", "graphml", "markdown"])
def test_cli_writes_documents(tmp_path: Path, fmt: str) -> None:
    bib = _bib(tmp_path)
    out = tmp_path / f"net.{fmt}"

    code, payload = _json("coauthors", str(bib), "--to", fmt, "--out", str(out))
    again = _json("coauthors", str(bib), "--to", fmt, "--out", str(out))
    forced = _json("coauthors", str(bib), "--to", fmt, "--out", str(out), "--force")

    assert code == 0 and payload["written"] is True and payload["content"] is None
    assert again[0] == 1 and again[1]["error"] == "FileExists"
    assert forced[0] == 0
    text = out.read_text(encoding="utf-8")
    if fmt == "json":
        document = json.loads(text)
        assert document["schema"] == SCHEMA
        assert document["source"]["file"] == str(bib)
        assert document["source"]["sha256"] == payload["source_sha256"]
    elif fmt == "graphml":
        ET.fromstring(text)
    else:
        assert text.startswith("# Co-author network of lib.bib")


def test_cli_streams_a_document_and_previews_writes(tmp_path: Path) -> None:
    bib = _bib(tmp_path)
    out = tmp_path / "net.graphml"

    streamed = runner.invoke(app, ["coauthors", str(bib), "--to", "graphml"])
    code, preview = _json(
        "coauthors", str(bib), "--to", "graphml", "--out", str(out), "--dry-run", "--diff"
    )
    without_format = _json("coauthors", str(bib), "--out", str(out))
    over_input = _json("coauthors", str(bib), "--to", "json", "--out", str(bib), "--force")

    assert streamed.exit_code == 0 and streamed.output.startswith("<?xml")
    assert code == 0 and preview["written"] is False and not out.exists()
    assert preview["diff"].startswith("---")
    assert without_format[0] == 1 and without_format[1]["error"] == "InvalidInput"
    assert over_input[1]["error"] == "OutputIsInput"


def test_analyze_reports_the_coauthor_summary(tmp_path: Path) -> None:
    bib = _bib(tmp_path)
    code, payload = _json("analyze", str(bib), "--section", "coauthors", "--top", "2")
    human = runner.invoke(app, ["analyze", str(bib), "--section", "coauthors"]).output

    section = payload["sections"]["coauthors"]
    assert code == 0
    assert section["authors"] == 15 and section["pairs"] == 12
    assert section["single_author_entries"] + section["coauthored_entries"] == 9
    assert len(section["top_pairs"]) == len(section["top_collaborators"]) == 2
    assert section["top_collaborators"][0] == {"name": "Born, Max", "collaborators": 4}
    assert "coauthors: 15 authors, 12 pairs, 6 components (largest 5)" in human
    assert "4 name-variant candidates" in human
