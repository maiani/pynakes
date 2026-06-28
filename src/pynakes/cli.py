"""Command-line application assembly for pynakes.

The public app object remains available from this module. Command callbacks live
in pynakes.cli_commands, grouped by command family.
"""

import typer

from pynakes import __version__
from pynakes.cli_commands import (
    add,
    batch,
    capabilities,
    convert,
    dedupe,
    fetch,
    fields,
    files,
    groups,
    init,
    inspect,
    integrity,
    keys,
    lint,
    metadata,
    normalize,
    remove,
    search,
    setops,
    used,
)
from pynakes.cli_discovery import AutoBibGroup

app = typer.Typer(help="Agent-friendly BibTeX library management tool", cls=AutoBibGroup)
groups_app = typer.Typer(help="Manage entry groups", cls=AutoBibGroup)
keys_app = typer.Typer(help="Generate and check citation keys", cls=AutoBibGroup)
fields_app = typer.Typer(
    help="Edit fields (rename, move, append, clear, protect titles)", cls=AutoBibGroup
)
files_app = typer.Typer(help="Validate linked-file references", cls=AutoBibGroup)
dedupe_app = typer.Typer(help="Detect and merge duplicate works", cls=AutoBibGroup)
metadata_app = typer.Typer(help="Inspect and update library metadata", cls=AutoBibGroup)


def _version_callback(value: bool) -> None:
    """Print the installed package version and exit before command parsing."""
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the pynakes version and exit.",
    ),
) -> None:
    """Agent-friendly BibTeX library management tool."""


init.register(app)
inspect.register(app)
fetch.register(app)
metadata.register(metadata_app)
lint.register(app)
files.register(files_app)
add.register(app)
dedupe.register(dedupe_app)
integrity.register(app)
groups.register(groups_app)
keys.register(keys_app)
fields.register(fields_app)
normalize.register(app)
convert.register(app)
capabilities.register(app)
search.register(app)
used.register(app)
setops.register(app)
remove.register(app)
batch.register(app)

app.add_typer(groups_app, name="groups")
app.add_typer(keys_app, name="keys")
app.add_typer(fields_app, name="fields")
app.add_typer(files_app, name="files")
app.add_typer(dedupe_app, name="dedupe")
app.add_typer(metadata_app, name="metadata")


if __name__ == "__main__":
    app()
