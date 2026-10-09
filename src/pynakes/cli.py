"""Command-line application assembly for pynakes.

The public app object remains available from this module. Command callbacks live
in pynakes.cli_commands, grouped by command family.
"""

import typer
import typer.main
from typer.core import TyperOption

from pynakes import __version__
from pynakes.capabilities import COMMAND_GROUPS
from pynakes.cli_commands import (
    add,
    asset_check,
    batch,
    capabilities,
    compare,
    convert,
    dedupe,
    directive,
    edit,
    fetch,
    fields,
    find,
    format,
    groups,
    import_ref,
    init,
    inspect,
    integrity,
    keys,
    lint,
    metadata,
    normalize,
    remove,
    scrub,
    search,
    setops,
    show,
    tex,
    tex_scan,
)
from pynakes.cli_completion import _bibfile_completer, _metadata_key_completer
from pynakes.cli_completion import _citekey_completer as _complete_fn
from pynakes.cli_discovery import AutoBibGroup
from pynakes.cli_surface import FILE_OPTION, FILE_OPTION_HELP, LIBRARY_ARGUMENT

app = typer.Typer(
    help="Agent-friendly BibTeX library management tool",
    cls=AutoBibGroup,
    rich_markup_mode="rich",
)
ref_app = typer.Typer(help="Manage individual reference entries", cls=AutoBibGroup)
groups_app = typer.Typer(help="Manage entry groups", cls=AutoBibGroup)
keys_app = typer.Typer(help="Work with citation keys", cls=AutoBibGroup)
fields_app = typer.Typer(help="Bulk-edit fields across matching references", cls=AutoBibGroup)
dedupe_app = typer.Typer(help="Detect and merge duplicate works", cls=AutoBibGroup)
metadata_app = typer.Typer(help="Inspect and update library metadata", cls=AutoBibGroup)
tex_app = typer.Typer(
    help="Manage linked TeX sources and scan them for citations", cls=AutoBibGroup
)
asset_app = typer.Typer(help="Fetch and validate Pinax materials", cls=AutoBibGroup)
corpus_app = typer.Typer(help="Operate across multiple .bib files", cls=AutoBibGroup)


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
metadata.register(metadata_app)
lint.register(app)
dedupe.register(dedupe_app)
integrity.register(app)
groups.register(groups_app)
keys.register(keys_app)
fields.register(fields_app)
normalize.register(app)
format.register(app)
convert.register(app)
capabilities.register(app)
search.register(app)
scrub.register(app)

# ref: per-entry lifecycle
add.register(ref_app)
import_ref.register(ref_app)
show.register(ref_app)
edit.register(ref_app)
directive.register(ref_app)
compare.register(ref_app)
find.register(ref_app)
remove.register(ref_app)

# tex: linked TeX sources (add/list/remove/clear) + scan (formerly `used`)
tex.register(tex_app)
tex_scan.register(tex_app)

# asset: Pinax materials (fetch download + linked-file check)
fetch.register(asset_app)
asset_check.register(asset_app)

# corpus: operations across multiple .bib files
setops.register(corpus_app)
batch.register(corpus_app)

app.add_typer(ref_app, name="ref")
app.add_typer(groups_app, name="groups")
app.add_typer(keys_app, name="keys")
app.add_typer(fields_app, name="fields")
app.add_typer(dedupe_app, name="dedupe")
app.add_typer(metadata_app, name="metadata")
app.add_typer(tex_app, name="tex")
app.add_typer(asset_app, name="asset")
app.add_typer(corpus_app, name="corpus")

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

# --- Command wiring ---------------------------------------------------------
# Typer does not forward ``shell_complete`` from arguments, and the shared
# ``--file`` option is added here rather than to every callback. Since
# ``typer.main.get_command()`` builds a fresh Click tree on every call, we
# monkey-patch it so this wiring is always applied.

# Maps (command_path, parameter_name) → shell_complete callback.
_CITEKEY_ARGS: dict[tuple[str, ...], str] = {
    ("ref", "show"): "key",
    ("ref", "edit"): "key",
    ("ref", "compare"): "key",
    ("ref", "remove"): "citekeys",
    ("keys", "generate"): "key",
    ("asset", "fetch"): "target",
    ("keys", "rename"): "old",
    ("keys", "usage"): "key",
    ("groups", "add-entry"): "key",
    ("groups", "remove-entry"): "key",
}

_METADATA_KEY_ARGS: dict[tuple[str, ...], str] = {
    ("metadata", "set"): "key",
}


def _file_option() -> TyperOption:
    """Return the ``--file``/``-f`` option every single-library command carries.

    Its value never reaches the callback: :mod:`pynakes.cli_surface` moves it
    into the leading FILE argument before Click parses the line. It exists as a
    real option so help, completion, and ``capabilities`` all show it.
    """
    option = TyperOption(
        param_decls=["file_option", *FILE_OPTION],
        default=None,
        metavar="FILE",
        expose_value=False,
        help=FILE_OPTION_HELP,
    )
    option.shell_complete = _bibfile_completer  # type: ignore[method-assign]
    return option


def _wire_command(command, path=()) -> None:
    for name, sub in command.commands.items():
        full = (*path, name)
        if hasattr(sub, "commands"):
            _wire_command(sub, full)
            continue
        target = _CITEKEY_ARGS.get(full)
        meta_target = _METADATA_KEY_ARGS.get(full)
        arguments = [param for param in sub.params if param.param_type_name == "argument"]
        if arguments and arguments[0].name == LIBRARY_ARGUMENT:
            sub.params.append(_file_option())
        for param in sub.params:
            if param.name == target:
                param.shell_complete = _complete_fn
            if param.name == meta_target:
                param.shell_complete = _metadata_key_completer
            if param.name == LIBRARY_ARGUMENT:
                # The leading slot holds the library, or the first operand when
                # the library is auto-detected: this offers both.
                param.shell_complete = _bibfile_completer


_get_command_orig = typer.main.get_command


def _get_command_patched(typer_instance):
    cmd = _get_command_orig(typer_instance)
    _wire_command(cmd)
    return cmd


typer.main.get_command = _get_command_patched


if __name__ == "__main__":
    app()
