"""Command dispatch support for discovering a lone local BibTeX library."""

from __future__ import annotations

import os
from pathlib import Path

import click
from click.shell_completion import CompletionItem
from typer._click.exceptions import UsageError as TyperUsageError
from typer.core import TyperGroup

from pynakes.cli_common import _emit_error, bib_candidates, missing_bib_message

_BIB_ARGUMENT_NAMES = {"file", "bib_file", "files"}

# Commands whose leading ``.bib`` argument names a file to *create*, not an
# existing library to discover. Auto-detecting and substituting a local ``.bib``
# would be actively wrong for these, so they are excluded from auto-insertion.
_NO_AUTODETECT_COMMANDS = {"init"}

# Context-meta key recording whether the caller asked for JSON output, so the
# group can honor the JSON contract when reframing a usage error.
_JSON_META_KEY = "pynakes_json_output"


def _is_shell_completion() -> bool:
    """Whether Click/Typer is resolving shell completions for this process."""
    return bool(os.environ.get("_PYNAKES_COMPLETE"))


def _report_missing_bib(json_output: bool, candidates: list[Path]) -> None:
    """Report the real cause when a leading ``.bib`` was omitted and undetectable.

    Mirrors :func:`pynakes.cli_common._resolve_input_bib` so a command that
    omits its library argument fails the same way whether the failure surfaces
    here (a multi-positional command whose parsing would otherwise report a
    misleading "Missing argument") or in the handler. Never returns.
    """
    _emit_error(json_output, "InvalidInput", missing_bib_message(candidates))


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

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Render help, but enumerate each sub-group's subcommands inline.

        Grouping commands under sub-apps (``ref``, ``tex``, ``asset`` …) hides
        the actual operations behind a noun in the top-level ``--help``. To keep
        that listing useful, temporarily append each sub-group's subcommand names
        to its short help so the second level is visible at a glance. Leaf
        commands and the per-group ``--help`` are untouched.
        """
        rich = getattr(self, "rich_markup_mode", None) == "rich"
        saved: list[tuple[click.Command, str | None]] = []
        for command in self.commands.values():
            subcommands = getattr(command, "commands", None)
            if not subcommands:
                continue
            saved.append((command, command.short_help))
            base = (command.help or command.short_help or "").strip().splitlines()
            head = base[0].rstrip(".") if base else ""
            names = ", ".join(subcommands)
            if rich:
                names = f"[cyan]{names}[/cyan]"
            command.short_help = f"{head} → {names}" if head else names
        try:
            super().format_help(ctx, formatter)
        finally:
            for command, original in saved:
                command.short_help = original

    @staticmethod
    def _is_typer_option(param: click.Parameter) -> bool:
        """Return whether *param* is an option-like parameter (Typer or Click)."""
        return param.param_type_name == "option"

    @staticmethod
    def _is_typer_argument(param: click.Parameter) -> bool:
        """Return whether *param* is an argument-like parameter (Typer or Click)."""
        return param.param_type_name == "argument"

    @staticmethod
    def _incomplete_typer_option(
        ctx: click.Context, args: list[str], param: click.Parameter
    ) -> bool:
        """Whether *param* (an option) is waiting for a value from the incomplete arg."""
        if not AutoBibGroup._is_typer_option(param):
            return False
        if getattr(param, "is_flag", False) or getattr(param, "count", False):
            return False
        depth = getattr(param, "nargs", 1)
        for index, arg in enumerate(reversed(args)):
            if index + 1 > depth:
                break
            if arg and arg[0] in ctx._opt_prefixes:
                return arg in param.opts
        return False

    @staticmethod
    def _incomplete_typer_argument(ctx: click.Context, param: click.Parameter) -> bool:
        """Whether *param* (an argument) can still accept a value."""
        if not AutoBibGroup._is_typer_argument(param):
            return False
        nargs = getattr(param, "nargs", 1)
        value = ctx.params.get(param.name)
        return (
            nargs == -1
            or ctx.get_parameter_source(param.name) is not click.ParameterSource.COMMANDLINE
            or (nargs > 1 and isinstance(value, (tuple, list)) and len(value) < nargs)
        )

    @staticmethod
    def _resolve_incomplete_typer(
        ctx: click.Context, args: list[str], incomplete: str
    ) -> tuple[click.Command | click.Parameter, str]:
        """Resolve the param or command to complete, mirroring Click's ``_resolve_incomplete``."""
        if incomplete == "=":
            incomplete = ""
        elif "=" in incomplete and incomplete[0] in ctx._opt_prefixes:
            name, _, incomplete = incomplete.partition("=")
            args.append(name)

        if "--" not in args and incomplete and incomplete[0] in ctx._opt_prefixes:
            return ctx.command, incomplete

        params = ctx.command.get_params(ctx)

        for param in params:
            if AutoBibGroup._incomplete_typer_option(ctx, args, param):
                return param, incomplete

        for param in params:
            if AutoBibGroup._incomplete_typer_argument(ctx, param):
                return param, incomplete

        return ctx.command, incomplete

    def shell_complete(self, ctx: click.Context, incomplete: str) -> list[CompletionItem]:
        """Override Click's command-name-only completion to handle Typer sub-groups.

        Click's ``_resolve_context`` uses ``isinstance(command, Group)`` to
        descend into sub-groups, and ``_resolve_incomplete`` checks
        ``isinstance(param, Argument/Option)`` to resolve the target param.
        Since Typer subclasses ``click.Command`` and ``click.Parameter``
        (not ``Group``/``Argument``/``Option``), those checks always fail.
        This override walks the Typer command tree directly and provides its
        own parameter-resolution logic that accepts Typer-style params.
        """
        args = [*ctx._protected_args, *ctx.args]

        # Walk the Typer command tree to find the target command.
        current: click.Command = self
        while args:
            name = args[0]
            cmd = current.commands.get(name) if hasattr(current, "commands") else None
            if cmd is None:
                break
            if len(args) > 1 or incomplete not in current.commands:
                args.pop(0)
                current = cmd
                continue
            break

        # Suggest option names when the incomplete value looks like an option.
        if incomplete.startswith("-"):
            results: list[CompletionItem] = []
            for param in current.get_params(ctx):
                if not AutoBibGroup._is_typer_option(param) or getattr(param, "hidden", False):
                    continue
                for opt in [*param.opts, *param.secondary_opts]:
                    if opt.startswith(incomplete):
                        results.append(CompletionItem(opt, help=param.help))
            return results

        # Suggest subcommand names when the current command is a group.
        subcommands = getattr(current, "commands", None)
        if subcommands:
            return [
                CompletionItem(name, help=cmd.get_short_help_str())
                for name, cmd in subcommands.items()
                if not getattr(cmd, "hidden", False) and incomplete.lower() in name.lower()
            ]

        # Leaf command: create a resilient context and resolve the incomplete param.
        try:
            with current.make_context(
                current.name or "", list(args), parent=ctx.parent, resilient_parsing=True
            ) as sub_ctx:
                obj, inc = AutoBibGroup._resolve_incomplete_typer(sub_ctx, list(args), incomplete)
                return obj.shell_complete(sub_ctx, inc)  # type: ignore[no-any-return]
        except Exception:
            return []

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # ``ctx.meta`` is shared across the context tree, so recording the JSON
        # request once makes it visible to ``invoke`` at every nesting level.
        if "--json" in args:
            ctx.meta[_JSON_META_KEY] = True
        json_output = ctx.meta.get(_JSON_META_KEY, False)
        if args and "--help" not in args and "-h" not in args and not _is_shell_completion():
            command = self.get_command(ctx, args[0])
            if (
                command is not None
                and not hasattr(command, "commands")
                and command.name not in _NO_AUTODETECT_COMMANDS
            ):
                if _should_insert_bib(command, args[1:]):
                    candidates = bib_candidates(Path.cwd())
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
        except (click.UsageError, TyperUsageError) as exc:
            if json_output:
                _emit_error(True, "UsageError", exc.format_message())
            raise

    def invoke(self, ctx: click.Context):
        """Override :meth:`click.Group.invoke` to catch ``UsageError`` raised during
        subcommand argument parsing (visible in ``standalone_mode=False`` paths such
        as the test runner)."""
        try:
            return super().invoke(ctx)
        except (click.UsageError, TyperUsageError) as exc:
            if not ctx.meta.get(_JSON_META_KEY, False):
                raise  # Humans keep Click's usage text and exit code 2.
            _emit_error(True, "UsageError", exc.format_message())
