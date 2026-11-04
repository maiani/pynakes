"""All-capital personal names are advisory findings, never automatic recasing."""

import pytest

from pynakes.bibtex_parser import parse_bib
from pynakes.lint import lint


@pytest.mark.parametrize("field", ["author", "editor"])
@pytest.mark.parametrize(
    "name,flagged",
    [
        ("NEWTON, ISAAC", True),
        ("EULER, L.", True),
        ("LUDWIG BOLTZMANN", True),
        (r"G{\"O}DEL, KURT", True),
        ("ÅNGSTRÖM, ANDERS", True),
        ("Newton, Isaac", False),
        ("NEWTON, Isaac", False),
        ("{ROYAL SOCIETY OF LONDON}", False),
        ("ABC", False),
        ("A. B.", False),
        ("{Royal Society} and NEWTON, ISAAC", True),
        ("{NEWTON}", True),
        ("", False),
    ],
)
def test_author_all_caps(field, name, flagged):
    source = "@misc{Example, " + field + "={" + name + "}}"
    lib = parse_bib(source)
    issues = [issue for issue in lint(lib) if issue.type == "author_all_caps"]
    assert bool(issues) is flagged
    if flagged:
        issue = issues[0]
        assert issue.field == field
        assert issue.category == "content"
        assert issue.severity == "warning"
        assert issue.fixer is None
        assert "recase by hand" in issue.message
        assert "[auth:capitalize]" in issue.message
    assert lib.entries["Example"].raw_content == source
