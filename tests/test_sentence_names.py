"""Opt-in title name protection and matching lint policy."""

import json

import pytest
from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.fields import protect_title_capitalization, title_capitalization_is_protected
from pynakes.lint import lint
from pynakes.normalize import NormalizeOptions, normalize_library


@pytest.mark.parametrize(
    "title,expected",
    [
        ("On the theory of Brownian motion", "On the theory of {Brownian} motion"),
        (
            "A study of Hamilton and the motion of particles",
            "A study of {Hamilton} and the motion of particles",
        ),
        ("On the Theory of Brownian Motion", "On the Theory of Brownian Motion"),
        ("Self-Consistent Theory of Motion", "Self-Consistent Theory of Motion"),
        ("Brownian motion in a liquid", "Brownian motion in a liquid"),
        ("Motion in a liquid: Brownian theory", "Motion in a liquid: Brownian theory"),
        ("Motion in a liquid. Brownian theory", "Motion in a liquid. Brownian theory"),
        ("Motion in a liquid? Brownian theory", "Motion in a liquid? Brownian theory"),
        ("Motion in a liquid! Brownian theory", "Motion in a liquid! Brownian theory"),
        ("On the theory of {Brownian} motion", "On the theory of {Brownian} motion"),
        ("ON THE THEORY OF BROWNIAN MOTION", "ON THE THEORY OF BROWNIAN MOTION"),
        (
            "On the theory of Ångström and the motion of particles",
            "On the theory of {Ångström} and the motion of particles",
        ),
        (
            "On the theory of Brownian-motion particles",
            "On the theory of {Brownian}-motion particles",
        ),
        (
            r"On the theory of $H$ and the motion of particles",
            r"On the theory of {$H$} and the motion of particles",
        ),
    ],
)
def test_sentence_names(title, expected):
    lib = parse_bib("@book{A, title={" + title + "}}")
    protect_title_capitalization(lib, proper_nouns=True)
    assert lib.entries["A"].fields["title"] == expected
    assert title_capitalization_is_protected(expected, proper_nouns=True)
    assert protect_title_capitalization(lib, proper_nouns=True) == 0


def test_api_and_lint_use_the_same_opt_in():
    source = "@book{A, title={On the theory of Brownian motion}}"
    plain = parse_bib(source)
    normalize_library(plain, NormalizeOptions(only=["titles"]))
    assert "Brownian" in plain.entries["A"].fields["title"]
    assert "{Brownian}" not in plain.entries["A"].fields["title"]
    lib = parse_bib("@comment{pynakes-meta: normalize-proper-nouns:true;}\n" + source)
    assert any(issue.type == "title_capitalization_unprotected" for issue in lint(lib))
    normalize_library(lib, NormalizeOptions(only=["titles"]))
    assert "{Brownian}" in lib.entries["A"].fields["title"]
    assert not any(issue.type == "title_capitalization_unprotected" for issue in lint(lib))
    lib = parse_bib("@comment{pynakes-meta: normalize-proper-nouns:true;}\n" + source)
    normalize_library(lib, NormalizeOptions(only=["titles"], proper_nouns=False))
    assert "{Brownian}" not in lib.entries["A"].fields["title"]


@pytest.mark.parametrize(
    "stored,flag,protected",
    [("true", "--no-proper-nouns", False), ("false", "--proper-nouns", True)],
)
def test_cli_override_and_metadata_validation(tmp_path, stored, flag, protected):
    path = tmp_path / "refs.bib"
    path.write_text("@book{A, title={On the theory of Brownian motion}}\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app, ["metadata", "set", str(path), "normalize-proper-nouns", stored, "--json"]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["normalize", str(path), "--only", "titles", flag, "--json"])
    assert result.exit_code == 0, result.output
    assert ("{Brownian}" in path.read_text(encoding="utf-8")) is protected
    result = runner.invoke(
        app, ["metadata", "set", str(path), "normalize-proper-nouns", "maybe", "--json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "error"
