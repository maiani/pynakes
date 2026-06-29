"""Command dispatch support for discovering a lone local BibTeX library."""

from __future__ import annotations

from pathlib import Path

import click
import typer._click.exceptions as _typer_exc
from typer.core import TyperGroup

_BIB_ARGUMENT_NAMES = {"file", "bib_file", "files"}

# Commands whose leading ``.bib`` argument names a file to *create*, not an
# existing library to discover. Auto-detecting and substituting a local ``.bib``
# would be actively wrong for these, so they are excluded from auto-insertion.
_NO_AUTODETECT_COMMANDS = {"init"}

# Context-meta key recording whether the caller asked for JSON output, so the
# group can honor the JSON contract when reframing a usage error.
_JSON_META_KEY = "pynakes_json_output"


def _bib_candidates(directory: Path) -> list[Path]:
    """Return the regular ``.bib`` files in *directory*, name-sorted."""
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == ".bib"),
        key=lambda path: path.name.casefold(),
    )


def _single_bib_file(directory: Path) -> Path | None:
    """Return the only regular ``.bib`` file in *directory*, if there is one."""
    candidates = _bib_candidates(directory)
    return candidates[0] if len(candidates) == 1 else None


def _emit_cli_error(json_output: bool, error: str, message: str) -> None:
    """Emit a structured (or plain) error and exit 1, via the shared helper.

    Imported lazily to avoid a circular import with :mod:`pynakes.cli_common`.
    """
    from pynakes.cli_common import _emit_error

    _emit_error(json_output, error, message)


def _report_missing_bib(json_output: bool, candidates: list[Path]) -> None:
    """Report the real cause when a leading ``.bib`` was omitted and undetectable.

    Mirrors :func:`pynakes.cli_common._resolve_input_bib` so a command that
    omits its library argument fails the same way whether the failure surfaces
    here (a multi-positional command whose parsing would otherwise report a
    misleading "Missing argument") or in the handler. Never returns.
    """
    if not candidates:
        _emit_cli_error(
            json_output,
            "InvalidInput",
            "No *.bib file found in current directory; specify one as an argument",
        )
    names = "  ".join(path.name for path in candidates)
    _emit_cli_error(
        json_output,
        "InvalidInput",
        f"Multiple *.bib files found; specify one as an argument:\n{names}",
    )


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

    When the library argument is omitted but cannot be auto-detected (no local
    ``.bib``, or more than one), it reports the real cause instead of Click's
    misleading downstream "Missing argument". And so the JSON contract is never
    broken by a parse failure, any usage error is reframed as a structured
    ``{"status":"error",...}`` envelope (exit 1) when ``--json`` was requested.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # ``ctx.meta`` is shared across the context tree, so recording the JSON
        # request once makes it visible to ``invoke`` at every nesting level.
        if "--json" in args:
            ctx.meta[_JSON_META_KEY] = True
        json_output = ctx.meta.get(_JSON_META_KEY, False)
        if len(args) >= 2 and "--help" not in args and "-h" not in args:
            command = self.get_command(ctx, args[0])
            if (
                command is not None
                and not hasattr(command, "commands")
                and command.name not in _NO_AUTODETECT_COMMANDS
            ):
                if _should_insert_bib(command, args[1:]):
                    candidates = _bib_candidates(Path.cwd())
                    if len(candidates) == 1:
                        args.insert(1, candidates[0].name)
                    else:
                        _report_missing_bib(json_output, candidates)
        return super().parse_args(ctx, args)

    def main(
        self, args: list[str] | None = None, prog_name: str | None = None, **extra: object
    ) -> object:
        """Override :meth:`click.BaseCommand.main` to catch ``UsageError`` before
        Click formats it when ``--json`` was requested.

        Click's ``main()`` wraps ``invoke()`` in a try/except that converts
        ``UsageError`` to ``SystemExit(2)`` in standalone mode.  That conversion
        bypasses the ``invoke`` override, so we intercept at the ``main`` level.
        """
        json_output = "--json" in (args or [])
        try:
            return super().main(args=args, prog_name=prog_name, **extra)
        except (click.UsageError, _typer_exc.UsageError) as exc:
            if json_output:
                _emit_cli_error(True, "UsageError", exc.format_message())
            raise

    def invoke(self, ctx: click.Context):
        """Override :meth:`click.Group.invoke` to catch ``UsageError`` raised during
        subcommand argument parsing (visible in ``standalone_mode=False`` paths such
        as the test runner)."""
        try:
            return super().invoke(ctx)
        except (click.UsageError, _typer_exc.UsageError) as exc:
            if not ctx.meta.get(_JSON_META_KEY, False):
                raise  # Humans keep Click's usage text and exit code 2.
            _emit_cli_error(True, "UsageError", exc.format_message())
