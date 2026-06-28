"""Command dispatch support for discovering a lone local BibTeX library."""

from __future__ import annotations

from pathlib import Path

import click
from typer.core import TyperGroup

_BIB_ARGUMENT_NAMES = {"file", "bib_file", "files"}


def _single_bib_file(directory: Path) -> Path | None:
    """Return the only regular ``.bib`` file in *directory*, if there is one."""
    candidates = sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".bib"),
        key=lambda path: path.name.casefold(),
    )
    return candidates[0] if len(candidates) == 1 else None


def _positional_tokens(command: click.Command, tokens: list[str]) -> list[str]:
    """Extract positional tokens while accounting for the command's options."""
    options = {
        option_name: param
        for param in command.params
        if param.param_type_name == "option"
        for option_name in (*param.opts, *param.secondary_opts)
    }
    positional: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            positional.extend(tokens[index + 1 :])
            break
        option_name, has_value, _value = token.partition("=")
        option = options.get(option_name)
        if option is not None:
            index += 1
            if not has_value and not option.is_flag:
                index += option.nargs
            continue
        if token.startswith("-"):
            # Leave unknown options for Click to report, but do not mistake
            # them for a library argument while deciding whether to insert one.
            index += 1
            continue
        positional.append(token)
        index += 1
    return positional


def _should_insert_bib(command: click.Command, tokens: list[str]) -> bool:
    """Whether *tokens* appear to omit this command's leading BibTeX argument."""
    arguments = [param for param in command.params if param.param_type_name == "argument"]
    if not arguments or arguments[0].name not in _BIB_ARGUMENT_NAMES:
        return False

    positional = _positional_tokens(command, tokens)
    if not positional:
        return True

    first = Path(positional[0])
    if first.suffix.lower() == ".bib" or first.is_file():
        return False

    required = sum(param.required for param in arguments)
    if len(positional) < required:
        return True

    # ``used`` and ``keys rename`` accept optional source paths after the
    # library. If their leading token is not an explicit file, it belongs to
    # that optional source list rather than the omitted library argument.
    if any(param.nargs == -1 for param in arguments[1:]):
        return True

    # When the leading bib argument is optional and the first token does not
    # look like a bib file, auto-insert the discovered library so that commands
    # like ``fields append keywords ml`` work without an explicit file.
    if not arguments[0].required:
        return True

    return False


class AutoBibGroup(TyperGroup):
    """Insert the lone local ``.bib`` file for commands that omit it.

    This operates before Click binds positional arguments, allowing commands
    such as ``fields append keywords ml`` to retain their existing positional
    syntax while using the discovered library as the leading argument.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if len(args) >= 2 and "--help" not in args and "-h" not in args:
            command = self.get_command(ctx, args[0])
            if command is not None and not hasattr(command, "commands"):
                candidate = _single_bib_file(Path.cwd())
                if candidate is not None and _should_insert_bib(command, args[1:]):
                    args.insert(1, candidate.name)
        return super().parse_args(ctx, args)
