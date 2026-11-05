"""CLI introspection for machine-readable capability and command references."""

# Stable type vocabulary for command-schema introspection. The on-disk click
# type names are mapped to this small, version-independent set so the pinned
# `capabilities` schema does not change shape when Typer/click internals do.
_TYPE_VOCABULARY = {
    "text": "string",
    "str": "string",
    "boolean": "boolean",
    "integer": "integer",
    # An option with min/max bounds: ``integer range`` up to click 8.1,
    # ``int range`` after it.
    "integer range": "integer",
    # Click's current names.
    "int": "integer",
    "int range": "integer",
    "float": "number",
    "float range": "number",
    "path": "path",
    "filename": "path",
    "file": "path",
    "choice": "choice",
}


def _stable_type(param) -> str:
    """Map a click parameter's type to the stable vocabulary, marking lists."""
    if getattr(param, "is_flag", False):
        return "boolean"
    raw = (getattr(param.type, "name", "") or "").lower()
    base = _TYPE_VOCABULARY.get(raw, "string")
    is_list = bool(getattr(param, "multiple", False)) or getattr(param, "nargs", 1) == -1
    return f"list[{base}]" if is_list else base


def _plain_help(text: str) -> str:
    """Strip Rich console-markup escapes from help text.

    Help strings escape ``[`` so Typer's Rich renderer prints literal brackets
    (``in \\[a, b]``). The capability description is data, not a rendered
    console line, so it reports the text as a reader would type it.
    """
    return text.replace("\\[", "[").replace("``", "`")


def _param_schema(param) -> dict:
    """Describe one click argument or option as a JSON-friendly dict."""
    entry: dict[str, object] = {
        "name": param.name,
        "type": _stable_type(param),
        "required": bool(param.required),
    }
    help_text = _plain_help((getattr(param, "help", "") or "").strip())
    if help_text:
        entry["help"] = help_text
    if getattr(param.type, "name", "") == "choice":
        entry["choices"] = list(param.type.choices)
    if param.param_type_name == "argument":
        entry["arg"] = True
        if getattr(param, "nargs", 1) == -1:
            entry["variadic"] = True
    else:
        # Every spelling, including the negative half of a flag pair
        # (``--no-blank-lines``) and short forms (``-f``).
        entry["flags"] = [*param.opts, *getattr(param, "secondary_opts", [])]
        default = param.default
        if isinstance(default, (str, int, float, bool)) or default is None:
            entry["default"] = default
    return entry


def _command_schema(command) -> dict:
    """Describe one click command: its help, arguments, and options."""
    help_text = _plain_help((command.help or command.short_help or "").strip()).splitlines()
    arguments = [_param_schema(p) for p in command.params if p.param_type_name == "argument"]
    options = [_param_schema(p) for p in command.params if p.param_type_name == "option"]
    return {
        "help": help_text[0] if help_text else "",
        "stability": "stable",
        "arguments": arguments,
        "options": options,
    }


def _walk_commands(group, prefix: str, out: dict) -> None:
    # A subcommand group exposes a ``commands`` mapping; a leaf command does not.
    # (Checked structurally rather than by isinstance, since Typer vendors its
    # own click fork whose Group is not the public ``click.Group``.)
    for name, command in sorted(group.commands.items()):
        if getattr(command, "hidden", False):
            # A deprecated form still runs, but is described under
            # ``deprecations`` rather than as part of the surface.
            continue
        full = f"{prefix}{name}"
        if hasattr(command, "commands"):
            _walk_commands(command, f"{full} ", out)
        else:
            out[full] = _command_schema(command)


def command_schemas() -> dict:
    """Introspect the live CLI into a per-command schema map.

    Derived from the actual Typer/click application, so it can never drift from
    the real command surface. Each entry (keyed by full command path, e.g.
    ``"groups assign"``) lists the command's help, positional ``arguments``,
    and ``options`` with stable type names, flags, defaults, and choices.
    """
    import typer.main

    # Imported first: pynakes.cli wires the shared --file option into
    # typer.main.get_command, which must be looked up after that patch.
    from pynakes.cli import app

    schemas: dict = {}
    _walk_commands(typer.main.get_command(app), "", schemas)
    return schemas
