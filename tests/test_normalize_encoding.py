"""normalize's encoding step, and the fields commands it replaces."""

import json
from pathlib import Path

from typer.testing import CliRunner

from pynakes.bibtex_parser import parse_bib
from pynakes.cli import app
from pynakes.lint import lint

runner = CliRunner()

LIBRARY = (
    "@book{Poincare1890,\n"
    "  author = {Henri Poincaré},\n"
    "  title = {Sur le problème des trois corps},\n"
    "  url = {https://example.org/poincaré},\n"
    "}\n"
)


def _library(tmp_path: Path, prefix: str = "") -> str:
    path = tmp_path / "refs.bib"
    path.write_text(prefix + LIBRARY, encoding="utf-8")
    return str(path)


def _normalize(*args: str) -> dict:
    result = runner.invoke(app, ["normalize", *args, "--only", "encoding", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_encoding_is_off_unless_asked(tmp_path: Path) -> None:
    library = _library(tmp_path)
    data = _normalize(library)
    assert "--encoding" in data["operations"]["skipped"]["encoding"]
    assert Path(library).read_text(encoding="utf-8").endswith(LIBRARY)


def test_encoding_converts_prose_fields_but_never_links(tmp_path: Path) -> None:
    library = _library(tmp_path)
    data = _normalize(library, "--encoding", "latex")
    assert data["operations"]["encoded_fields"] == {"author": 1, "title": 1}
    text = Path(library).read_text(encoding="utf-8")
    assert "Henri Poincar{\\'{e}}" in text
    assert "probl{\\`{e}}me" in text
    assert "https://example.org/poincaré" in text


def test_encoding_fields_and_setting_are_honoured(tmp_path: Path) -> None:
    library = _library(tmp_path, "@comment{pynakes-meta:\nnormalize-encoding: latex\n}\n\n")
    data = _normalize(library, "--encoding-field", "title")
    assert data["operations"]["encoded_fields"] == {"title": 1}


def test_the_deprecated_fields_encoding_setting_is_not_read_and_lint_says_so(
    tmp_path: Path,
) -> None:
    prefix = "@comment{pynakes-meta:\nfields-encoding: latex\n}\n\n"
    library = _library(tmp_path, prefix)
    assert "encoding" in _normalize(library)["operations"]["skipped"]
    findings = lint(parse_bib(prefix + LIBRARY))
    assert [issue.key for issue in findings if issue.type == "deprecated_metadata_key"] == [
        "fields-encoding"
    ]


def test_fields_encode_and_protect_title_run_hidden_and_point_to_normalize(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path)
    for args, action in (
        (["encode", library, "title", "--to", "latex"], "fields_encode"),
        (["protect-title", library], "fields_protect_title"),
    ):
        result = runner.invoke(app, ["fields", *args, "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["action"] == action
        assert data["warnings"][-1]["new"].startswith("normalize")


def test_batch_normalize_takes_a_selection_and_steps(tmp_path: Path) -> None:
    library = _library(tmp_path)
    ops = json.dumps(
        [{"op": "normalize", "only": ["encoding"], "encoding": "latex", "where": "year missing"}]
    )
    result = runner.invoke(app, ["batch", library, "--ops", ops, "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["operations"][0]["result"]["operations"]["encoded_fields"] == {
        "author": 1,
        "title": 1,
    }
