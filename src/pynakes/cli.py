"""Command-line application assembly for pynakes.

The public app object remains available from this module. Command callbacks live
in pynakes.cli_commands, grouped by command family.
"""

import typer

from pynakes.cli_commands import (
    capabilities,
    convert,
    dedupe,
    doi,
    fields,
    files,
    groups,
    inspect,
    integrity,
    journals,
    keys,
    lint,
    metadata,
    normalize,
    used,
)

app = typer.Typer(help="Agent-friendly BibTeX library management tool")
groups_app = typer.Typer(help="Manage entry groups")
keys_app = typer.Typer(help="Generate and check citation keys")
fields_app = typer.Typer(help="Edit fields (rename, move, append, clear, protect titles)")
files_app = typer.Typer(help="Validate JabRef linked files")
doi_app = typer.Typer(help="Import references by DOI")
dedupe_app = typer.Typer(help="Detect and merge duplicate works")
journals_app = typer.Typer(help="Abbreviate, expand, and check journal titles")
metadata_app = typer.Typer(help="Inspect and update JabRef library metadata")

inspect.register(app)
metadata.register(metadata_app)
lint.register(app)
files.register(files_app)
doi.register(doi_app)
dedupe.register(dedupe_app)
integrity.register(app)
groups.register(groups_app)
keys.register(keys_app)
fields.register(fields_app)
normalize.register(app)
convert.register(app)
journals.register(journals_app)
capabilities.register(app)
used.register(app)

app.add_typer(groups_app, name="groups")
app.add_typer(keys_app, name="keys")
app.add_typer(fields_app, name="fields")
app.add_typer(files_app, name="files")
app.add_typer(doi_app, name="doi")
app.add_typer(dedupe_app, name="dedupe")
app.add_typer(journals_app, name="journals")
app.add_typer(metadata_app, name="metadata")


if __name__ == "__main__":
    app()
