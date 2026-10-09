"""The command line's positional convention: the library comes first.

Every command that reads one library takes it **first**: as the leading
positional argument, or as ``--file``/``-f`` anywhere on the line, or not at all
when the working directory holds exactly one ``.bib`` file. Which positional
token is the library is decided by syntax alone, never by asking the
filesystem: the first positional is the library when it ends in ``.bib``, or
when the positionals fill every argument the command has. Otherwise the
library was omitted and the lone local ``.bib`` is used.
"""

from __future__ import annotations

from pathlib import Path, PurePath

import click
import typer

from pynakes.cli_common import _emit_error, bib_candidates, missing_bib_message

#: The name of the library argument on every single-library command.
LIBRARY_ARGUMENT = "file"

#: The name of the libraries argument on the multi-file checks (``lint``, ``verify``, ...).
FILES_ARGUMENT = "files"

#: The option that names the library wherever the positional slot is inconvenient.
FILE_OPTION = ("--file", "-f")

FILE_OPTION_HELP = (
    "The library to read, as an alternative to the leading FILE argument "
    "(default: the single .bib in the working directory)"
)

#: Commands whose library may be ``-``, standard input.
STDIN_LIBRARY_COMMANDS = {("format",), ("normalize",), ("scrub",)}

#: Arguments holding free text, which may legitimately end in ``.bib``.
FREE_TEXT_ARGUMENTS = {"query", "value"}

#: Commands that create the library they name, so it is never auto-detected.
NO_AUTODETECT_COMMANDS = {("init",)}


#: Typer 0.26+ vendors its own click, and only its exceptions reach the
#: standalone handler, so a usage error raised here must be typer's class.
_UsageError: type[click.UsageError] = next(
    cls for cls in typer.BadParameter.__mro__ if cls.__name__ == "UsageError"
)


def _usage_error(message: str) -> click.UsageError:
    return _UsageError(message)


def command_line(path: tuple[str, ...]) -> str:
    """Return the command path as typed: ``ref show``."""
    return " ".join(path)


# --- token scanning ---------------------------------------------------------


def _option_table(command: click.Command) -> dict[str, click.Parameter]:
    return {
        name: param
        for param in command.params
        if param.param_type_name == "option"
        for name in (*param.opts, *param.secondary_opts)
    }


def _takes_value(param: click.Parameter) -> bool:
    return not (getattr(param, "is_flag", False) or getattr(param, "count", False))


def _positional_indices(command: click.Command, tokens: list[str]) -> list[int]:
    """Return the indices of the positional tokens, skipping options and their values."""
    options = _option_table(command)
    indices: list[int] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            indices.extend(range(index + 1, len(tokens)))
            break
        name, has_value, _ = token.partition("=")
        option = options.get(name)
        if option is not None:
            index += 1
            if not has_value and _takes_value(option):
                index += option.nargs
            continue
        if token.startswith("-") and token != "-":
            # An unknown option is Click's to report; it is not a positional.
            index += 1
            continue
        indices.append(index)
        index += 1
    return indices


# --- the library slot -------------------------------------------------------


def looks_like_library(token: str, path: tuple[str, ...]) -> bool:
    """Whether a positional token names a library, judged by its spelling alone."""
    if token == "-":
        return path in STDIN_LIBRARY_COMMANDS
    if "://" in token:
        return False
    return PurePath(token).suffix.lower() == ".bib"


def _argument_at(operands: list[click.Parameter], position: int) -> click.Parameter | None:
    """Return the argument that binds the operand token at *position*."""
    for index, param in enumerate(operands):
        if param.nargs == -1:
            return param
        if index == position:
            return param
    return None


def _misplaced(
    path: tuple[str, ...], operands: list[click.Parameter], tokens: list[str]
) -> int | None:
    """Return the position of an operand token that looks like a library, if any."""
    for position, token in enumerate(tokens):
        param = _argument_at(operands, position)
        if param is not None and param.name in FREE_TEXT_ARGUMENTS:
            continue
        if looks_like_library(token, path):
            return position
    return None


def _synopsis(path: tuple[str, ...], operands: list[click.Parameter]) -> str:
    names = [
        f"{(param.name or '').upper()}{'...' if param.nargs == -1 else ''}" for param in operands
    ]
    return " ".join(["pynakes", command_line(path), "FILE", *names])


def _misplaced_error(
    path: tuple[str, ...], operands: list[click.Parameter], token: str
) -> click.UsageError:
    return _usage_error(
        f"{token} looks like a library, but `{command_line(path)}` takes the library "
        f"first: {_synopsis(path, operands)} (or name it with --file)"
    )


def _extract_file_option(tokens: list[str], command: click.Command) -> tuple[list[str], list[str]]:
    """Remove every ``--file``/``-f`` occurrence, returning the rest and the values."""
    options = _option_table(command)
    rest: list[str] = []
    values: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            rest.extend(tokens[index:])
            break
        name, has_value, inline = token.partition("=")
        if name in FILE_OPTION:
            if has_value:
                values.append(inline)
            elif index + 1 < len(tokens):
                index += 1
                values.append(tokens[index])
            else:
                raise _usage_error(f"Option '{name}' requires an argument.")
            index += 1
            continue
        option = options.get(name)
        rest.append(token)
        if option is not None and not has_value and _takes_value(option):
            # Copy an option's value through untouched, even one spelled ``-f``.
            for _ in range(option.nargs):
                if index + 1 < len(tokens):
                    index += 1
                    rest.append(tokens[index])
        index += 1
    return rest, values


def _autodetected(json_output: bool) -> str:
    """Return the lone ``.bib`` in the working directory, or report why there is none."""
    candidates = bib_candidates(Path.cwd())
    if len(candidates) != 1:
        _emit_error(json_output, "InvalidInput", missing_bib_message(candidates))
    return candidates[0].name


def place_library(
    path: tuple[str, ...], command: click.Command, tokens: list[str], json_output: bool
) -> list[str]:
    """Return *tokens* with the library as the leading positional argument.

    Handles ``--file`` and the lone-local-library default. A token that looks
    like a library anywhere but the library slot is refused.
    """
    arguments = [param for param in command.params if param.param_type_name == "argument"]
    if arguments and arguments[0].name == FILES_ARGUMENT:
        # The checks take several libraries; with none named they check the lone local one.
        if _positional_indices(command, tokens) or "--recursive" in tokens:
            return tokens
        return [_autodetected(json_output), *tokens]
    if not arguments or arguments[0].name != LIBRARY_ARGUMENT:
        return tokens
    operands = arguments[1:]
    tokens, file_values = _extract_file_option(tokens, command)
    indices = _positional_indices(command, tokens)
    positional = [tokens[index] for index in indices]

    if file_values:
        if len(file_values) > 1:
            raise _usage_error("The library is named more than once with --file")
        misplaced = _misplaced(path, operands, positional)
        if misplaced is not None:
            raise _misplaced_error(path, operands, positional[misplaced])
        return [file_values[0], *tokens]

    if "--recursive" in tokens:
        # ``format --recursive`` takes a directory, or nothing for the cwd.
        return tokens
    if positional and looks_like_library(positional[0], path):
        misplaced = _misplaced(path, operands, positional[1:])
        if misplaced is not None:
            raise _misplaced_error(path, operands, positional[1 + misplaced])
        return tokens

    misplaced = _misplaced(path, operands, positional)
    if misplaced is not None:
        raise _misplaced_error(path, operands, positional[misplaced])

    variadic = any(param.nargs == -1 for param in operands)
    if positional and not variadic and len(positional) == len(operands) + 1:
        # Every slot is filled, so the first token is the library whatever its name.
        return tokens
    if path in NO_AUTODETECT_COMMANDS:
        return tokens
    return [_autodetected(json_output), *tokens]
