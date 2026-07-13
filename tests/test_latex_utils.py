"""Shared LaTeX text-conversion helpers."""

import pytest

from pynakes.formatters import latex_to_plain_text


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (r"$\phi$-junction", " Phi -junction"),
        (r"$\varphi$-junction", " Phi -junction"),
        (r"$\Phi$-junction", " Phi -junction"),
        (r"{\ensuremath{\phi}}-junction", " Phi -junction"),
        (r"$\mathbf{\Delta}$ phase", " Delta  phase"),
    ),
)
def test_latex_to_plain_text_converts_math_commands(value: str, expected: str) -> None:
    assert latex_to_plain_text(value) == expected


def test_latex_to_plain_text_preserves_unknown_command_name() -> None:
    assert latex_to_plain_text(r"The \LaTeX companion") == "The  LaTeX  companion"
