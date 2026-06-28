"""Command-line application assembly for pynakes.

The public app object remains available from this module. Command callbacks live
in pynakes.cli_commands, grouped by command family.
"""

import typer
import typer.main

from pynakes import __version__
from pynakes.capabilities import COMMAND_GROUPS
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
from pynakes.cli_common import _bibfile_completer
from pynakes.cli_common import _citekey_completer as _complete_fn
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

# --- Group top-level --help by nature ---------------------------------------
# The taxonomy lives once in capabilities.COMMAND_GROUPS (shared with the
# machine-readable description). Apply it as Typer rich-help panels, and order
# both the commands and the panels to follow that taxonomy.
_PANEL_BY_COMMAND = {name: panel for panel, names in COMMAND_GROUPS.items() for name in names}
_PANEL_ORDER = {panel: index for index, panel in enumerate(COMMAND_GROUPS)}
_COMMAND_ORDER = {
    name: index
    for index, name in enumerate(name for names in COMMAND_GROUPS.values() for name in names)
}


def _command_name(info) -> str:
    """Resolve a registered command's CLI name (Typer leaves ``name`` None often)."""
    return info.name or info.callback.__name__


def _panel_sort_key(name: str) -> tuple[int, int]:
    panel = _PANEL_BY_COMMAND.get(name)
    return (
        _PANEL_ORDER.get(panel, len(_PANEL_ORDER)),
        _COMMAND_ORDER.get(name, len(_COMMAND_ORDER)),
    )


for _info in app.registered_commands:
    _info.rich_help_panel = _PANEL_BY_COMMAND.get(_command_name(_info))
for _info in app.registered_groups:
    _info.rich_help_panel = _PANEL_BY_COMMAND.get(_info.name)

# Order so panels (and commands within them) render in taxonomy order. Leaf
# commands sort before sub-groups within a shared panel, which reads naturally.
app.registered_commands.sort(key=lambda info: _panel_sort_key(_command_name(info)))
app.registered_groups.sort(key=lambda info: _panel_sort_key(info.name))

# --- Shell completion wiring ------------------------------------------------
# Typer does not forward ``shell_complete`` from arguments. Since
# ``typer.main.get_command()`` builds a fresh Click tree on every call, we
# monkey-patch it so our completion wiring is always applied.

# Maps (command_path, parameter_name) → shell_complete callback.
_CITEKEY_ARGS: dict[tuple[str, ...], str] = {
    ("remove",): "citekeys",
    ("fetch",): "target",
    ("keys", "rename"): "old",
    ("groups", "add-entry"): "key",
    ("groups", "remove-entry"): "key",
}


def _wire_completion(command, path=()) -> None:
    for name, sub in command.commands.items():
        full = (*path, name)
        if not hasattr(sub, "commands"):
            target = _CITEKEY_ARGS.get(full)
            for param in sub.params:
                if param.name == target:
                    param.shell_complete = _complete_fn
                if param.name in ("file", "bib_file"):
                    param.shell_complete = _bibfile_completer
        else:
            _wire_completion(sub, full)


_get_command_orig = typer.main.get_command


def _get_command_patched(typer_instance):
    cmd = _get_command_orig(typer_instance)
    _wire_completion(cmd)
    return cmd


typer.main.get_command = _get_command_patched


if __name__ == "__main__":
    app()
