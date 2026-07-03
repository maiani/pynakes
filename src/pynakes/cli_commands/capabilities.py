"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json

import typer

from pynakes.capabilities import get_capabilities

# --- capabilities ------------------------------------------------


def capabilities(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show tool capabilities."""
    caps = get_capabilities()
    if json_output:
        typer.echo(json.dumps(caps, indent=2))
        return
    typer.echo(f"{caps['tool']} v{caps['version']}")
    descriptions = caps["commands"]
    for panel, names in caps["command_groups"].items():
        typer.echo(f"\n{panel}:")
        for name in names:
            typer.echo(f"  {name:14} {descriptions[name]}")


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(capabilities)
