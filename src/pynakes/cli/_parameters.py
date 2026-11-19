"""Build shared options through Typer's annotated command API."""

from copy import deepcopy
from functools import cache

import typer
from typer.core import TyperOption
from typer.main import get_command

from pynakes.cli._surface import FILE_OPTION, FILE_OPTION_HELP


@cache
def _templates() -> dict[str, TyperOption]:
    app = typer.Typer(add_completion=False)

    @app.command()
    def shared(
        file_option: str | None = typer.Option(
            None, *FILE_OPTION, metavar="FILE", expose_value=False, help=FILE_OPTION_HELP
        ),
        pretty_json: bool = typer.Option(
            False,
            "--pretty",
            expose_value=False,
            help="Indent --json output for reading (default: compact, one line)",
        ),
    ) -> None:
        """Declare options whose values are consumed before callback dispatch."""

    # Capture the original builder at import time, before _app installs its
    # command-tree wiring. This declaration-only command must not be wired.
    return {p.name: p for p in get_command(app).params if isinstance(p, TyperOption) and p.name}


def shared_option(name: str) -> TyperOption:
    """Return an independent option, including Typer's validation descriptor."""
    return deepcopy(_templates()[name])
