"""CLI entry point; command infrastructure loads independently of the app.

The console script remains ``pynakes.cli:app``. Importing shared error codes,
choices or file-discovery helpers does not assemble the Typer command tree.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typer import Typer

    from pynakes.cli._app import app as app

__all__ = ["app"]


def __getattr__(name: str) -> "Typer":
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from pynakes.cli._app import app

    globals()[name] = app
    return app


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
