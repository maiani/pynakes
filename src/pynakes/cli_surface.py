"""The command line's positional convention and its deprecated forms.

Every command that reads one library takes it **first**: as the leading
positional argument, or as ``--file``/``-f`` anywhere on the line, or not at all
when the working directory holds exactly one ``.bib`` file. Which positional
token is the library is decided by syntax alone, never by asking the
filesystem: the first positional is the library when it ends in ``.bib``, or
when the positionals fill every argument the command has. Otherwise the
library was omitted and the lone local ``.bib`` is used.

The forms that 0.7 renamed or reordered keep working through 0.7.x, rewritten
here before Click parses the line, and each use is reported as a ``deprecated``
warning naming the replacement. They are removed in 0.8.0. A form whose meaning
changed, rather than its spelling, fails with an error naming the replacement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath

import click
import typer

from pynakes.cli_common import _emit_error, bib_candidates, missing_bib_message, note_deprecation

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

#: Commands that took their operand before the library before 0.7. When a later
#: positional looks like a library and the first does not, the old order is
#: still accepted, with a deprecation warning, through 0.7.x.
LEGACY_OPERAND_FIRST: dict[tuple[str, ...], str] = {
    ("ref", "show"): "KEY",
    ("ref", "edit"): "KEY",
    ("ref", "compare"): "KEY",
    ("ref", "add"): "KEY",
    ("ref", "import"): "IDENTIFIER...",
    ("search",): "QUERY",
    ("asset", "fetch"): "KEY",
    ("keys", "generate"): "KEY",
    ("tex", "add"): "PATH...",
    ("tex", "remove"): "PATH...",
}

#: Commands whose library may be ``-``, standard input.
STDIN_LIBRARY_COMMANDS = {("format",), ("normalize",), ("scrub",)}

#: Arguments holding free text, which may legitimately end in ``.bib``.
FREE_TEXT_ARGUMENTS = {"query", "value"}

#: Commands that create the library they name, so it is never auto-detected.
NO_AUTODETECT_COMMANDS = {("init",)}


@dataclass(frozen=True)
class Renamed:
    """A deprecated option spelling and the tokens that replace it.

    ``replacement`` replaces the old flag token. When ``takes_value`` is set the
    old option took a value, which follows the replacement unchanged; an empty
    replacement turns that value into a positional argument.
    """

    replacement: tuple[str, ...]
    takes_value: bool

    @property
    def spelling(self) -> str:
        """The replacement as a caller would write it."""
        if not self.replacement:
            return "a positional argument"
        return " ".join(self.replacement)


def _valued(*replacement: str) -> Renamed:
    return Renamed(replacement, takes_value=True)


def _flag(*replacement: str) -> Renamed:
    return Renamed(replacement, takes_value=False)


#: Option spellings removed in 0.7 that are rewritten, with a warning, until 0.8.
DEPRECATED_OPTIONS: dict[tuple[str, ...], dict[str, Renamed]] = {
    ("ref", "show"): {"--keys": _valued("--key")},
    ("search",): {"--field": _valued("--in-field"), "--show-abstract": _flag("--abstract")},
    ("scrub",): {"--field": _valued("--drop-field"), "--keep-fields": _flag("--keep-field", "*")},
    ("fields", "protect-title"): {"--field": _valued("--title-field")},
    ("normalize",): {
        "--keys": _valued("--key-generation"),
        "--force": _flag("--ignore-missing-tex"),
    },
    ("init",): {"--type": _valued("--dialect"), "--from": _valued("--profile-from")},
    ("corpus", "split"): {"--to": _valued("--route")},
    ("format",): {"--stdout": _flag("--out", "-")},
    ("keys", "usage"): {"--path": _valued()},
    ("asset", "fetch"): {
        "--preprint": _flag("--material", "preprint"),
        "--published": _flag("--material", "published"),
        "--source": _flag("--material", "source"),
        "--supplement": _flag("--material", "supplement"),
        "--bestpdf": _flag("--material", "best-pdf"),
    },
}

_ON_OFF = {"true": "on", "yes": "on", "1": "on", "false": "off", "no": "off", "0": "off"}
_CONTEXT = {"0": "independent", "1": "refining", "2": "including"}
_NORMALIZE_SWITCHES = (
    "--title-protection",
    "--doi-normalization",
    "--pages",
    "--key-generation",
    "--identifier-case",
    "--metadata-formatting",
)

#: Option values that 0.7 renamed, rewritten with a warning until 0.8.
DEPRECATED_VALUES: dict[tuple[str, ...], dict[str, dict[str, str]]] = {
    ("normalize",): {flag: _ON_OFF for flag in _NORMALIZE_SWITCHES},
    ("groups", "add-group"): {"--context": _CONTEXT},
    ("groups", "update-group"): {"--context": _CONTEXT},
}

#: Short flags whose meaning changed in 0.7: the old use fails, naming the new one.
#: ``-f`` set a field on ``ref add``/``ref edit``; it now names the library
#: everywhere, as it already did on ``ref import`` and ``tex``.
CHANGED_SHORT_FLAGS: dict[tuple[str, ...], dict[str, str]] = {
    ("ref", "add"): {"-f": "--field"},
    ("ref", "edit"): {"-f": "--field"},
}


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


# --- deprecated spellings ---------------------------------------------------


def _rewrite_options(path: tuple[str, ...], tokens: list[str], json_output: bool) -> list[str]:
    """Replace deprecated option spellings and values with their 0.7 forms."""
    renames = DEPRECATED_OPTIONS.get(path, {})
    values = DEPRECATED_VALUES.get(path, {})
    changed = CHANGED_SHORT_FLAGS.get(path, {})
    out: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            out.extend(tokens[index:])
            break
        name, has_value, inline = token.partition("=")
        if name in changed:
            value = inline if has_value else (tokens[index + 1] if index + 1 < len(tokens) else "")
            if "=" in value:
                raise _usage_error(
                    f"{name} now names the library (--file); set a field with "
                    f"{changed[name]} {value}"
                )
        rename = renames.get(name)
        if rename is not None:
            note_deprecation(json_output, name, rename.spelling)
            out.extend(rename.replacement)
            if rename.takes_value:
                if has_value:
                    out.append(inline)
                elif index + 1 < len(tokens):
                    index += 1
                    out.append(tokens[index])
            index += 1
            continue
        aliases = values.get(name)
        if aliases is not None:
            if has_value:
                value, consumed = inline, 0
            elif index + 1 < len(tokens):
                value, consumed = tokens[index + 1], 1
            else:
                out.append(token)
                index += 1
                continue
            new_value = aliases.get(value.lower())
            if new_value is not None:
                note_deprecation(json_output, f"{name} {value}", f"{name} {new_value}")
                value = new_value
            out.extend([name, value])
            index += 1 + consumed
            continue
        out.append(token)
        index += 1
    return out


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

    Handles ``--file``, the old operand-first order of the commands listed in
    :data:`LEGACY_OPERAND_FIRST`, and the lone-local-library default. A token
    that looks like a library anywhere but the library slot is refused.
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
        operand = LEGACY_OPERAND_FIRST.get(path)
        rest = positional[:misplaced] + positional[misplaced + 1 :]
        if operand is None or _misplaced(path, operands, rest) is not None:
            raise _misplaced_error(path, operands, positional[misplaced])
        library_index = indices[misplaced]
        line = command_line(path)
        note_deprecation(json_output, f"{line} {operand} FILE", f"{line} FILE {operand}")
        return [tokens[library_index], *tokens[:library_index], *tokens[library_index + 1 :]]

    variadic = any(param.nargs == -1 for param in operands)
    if positional and not variadic and len(positional) == len(operands) + 1:
        # Every slot is filled, so the first token is the library whatever its name.
        return tokens
    if path in NO_AUTODETECT_COMMANDS:
        return tokens
    return [_autodetected(json_output), *tokens]


def prepare_arguments(
    path: tuple[str, ...], command: click.Command, tokens: list[str], json_output: bool
) -> list[str]:
    """Rewrite a leaf command's tokens into the form its Click parameters expect."""
    tokens = _rewrite_options(path, tokens, json_output)
    return place_library(path, command, tokens, json_output)


def deprecations() -> list[dict]:
    """Describe every deprecated form, for ``capabilities``."""
    described: list[dict] = []
    for path, renames in DEPRECATED_OPTIONS.items():
        for old, rename in renames.items():
            described.append({"command": command_line(path), "old": old, "new": rename.spelling})
    for path, options in DEPRECATED_VALUES.items():
        for option, aliases in options.items():
            for old, new in aliases.items():
                described.append(
                    {
                        "command": command_line(path),
                        "old": f"{option} {old}",
                        "new": f"{option} {new}",
                    }
                )
    for path, operand in LEGACY_OPERAND_FIRST.items():
        line = command_line(path)
        described.append(
            {"command": line, "old": f"{line} {operand} FILE", "new": f"{line} FILE {operand}"}
        )
    return described
