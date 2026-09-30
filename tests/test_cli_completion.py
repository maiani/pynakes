"""Shell completion resolves the argument actually being typed.

Typer 0.26+ vendors its own click, so the parameter sources its parser records
are not the public ``click.ParameterSource`` members. Completion must still tell
an argument already given on the command line from one still open.
"""

from typer.main import get_command

from pynakes.cli import app
from pynakes.cli_discovery import AutoBibGroup


def _rename_context(args: list[str]):
    root = get_command(app)
    ctx = root.make_context("pynakes", ["keys", "rename", *args], resilient_parsing=True)
    keys = root.get_command(ctx, "keys")
    keys_ctx = keys.make_context("keys", ["rename", *args], parent=ctx, resilient_parsing=True)
    rename = keys.get_command(keys_ctx, "rename")
    return rename, rename.make_context("rename", args, parent=keys_ctx, resilient_parsing=True)


def test_arguments_given_on_the_command_line_are_not_completed_again() -> None:
    command, ctx = _rename_context(["lib.bib", "Euler1748"])

    still_open = {
        param.name: AutoBibGroup._incomplete_typer_argument(ctx, param)
        for param in command.params
        if AutoBibGroup._is_typer_argument(param)
    }

    assert still_open == {"file": False, "old": False, "new": True, "sources": True}
