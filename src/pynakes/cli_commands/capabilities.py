"""CLI command registration for pynakes.

This module keeps command callbacks separate from application assembly while
retaining the stable CLI contract.
"""

import json as _json

import typer

from pynakes.capabilities import get_capabilities

# --- capabilities ------------------------------------------------


def capabilities(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show tool capabilities."""
    caps = get_capabilities()
    if json_output:
        typer.echo(_json.dumps(caps, indent=2))
        return
    typer.echo(f"{caps['tool']} v{caps['version']}")
    typer.echo("Commands:")
    for name, desc in caps["commands"].items():
        typer.echo(f"  {name:14} {desc}")


def register(app: typer.Typer) -> None:
    """Register this command family on its Typer application."""
    app.command()(capabilities)
