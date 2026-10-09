"""Command dispatch support for discovering a lone local BibTeX library."""

from __future__ import annotations

import os
import sys

import click
import typer
from click.shell_completion import CompletionItem
from typer.core import TyperGroup

from pynakes.cli_common import _emit_error
from pynakes.cli_surface import place_library

# Context-meta key recording whether the caller asked for JSON output, so the
# group can honor the JSON contract when reframing a usage error.
_JSON_META_KEY = "pynakes_json_output"

# Typer 0.26+ vendors its own click, so the usage errors and parameter sources
# its parser produces are not the public ``click`` classes. Take typer's usage
# error from a public typer class rather than importing its private module; on
# older typer, which uses click itself, this is simply ``click.UsageError``.
_TYPER_USAGE_ERROR: type[Exception] = next(
    cls for cls in typer.BadParameter.__mro__ if cls.__name__ == "UsageError"
)
_USAGE_ERRORS = (click.UsageError, _TYPER_USAGE_ERROR)


def _source_name(ctx: click.Context, param: click.Parameter) -> str | None:
    """Return where ``param`` got its value, by name (``"COMMANDLINE"``, ...).

    Compared by name because the enum comes from whichever click the running
    typer uses, which need not be the public ``click`` module.
    """
    source = ctx.get_parameter_source(param.name) if param.name else None
    return getattr(source, "name", None)


def _is_shell_completion() -> bool:
    """Whether Click/Typer is resolving shell completions for this process."""
    return bool(os.environ.get("_PYNAKES_COMPLETE"))


#: Selector options whose absence is worth explaining rather than merely
#: reporting. ``--key`` is the one that bites: it means "the key to assign" on
#: the commands that create an entry, so reaching for it as a selector is a
#: reasonable guess, and Click's bare "No such option" leaves nowhere to go.
_SELECTOR_ALIASES = {"--key", "--keys", "--citekey", "--citation-key", "--entry"}


def _selector_hint(exc: click.UsageError) -> str | None:
    """Return the selector advice for an unknown option, when one applies.

    Click's ``NoSuchOption`` says only that the option does not exist. When the
    option the caller reached for is a citation-key selector, the useful reply
    names what this command does accept — ``--key`` where it is a selector,
    ``--where`` where the command takes only the expression grammar, and the
    positional citation key where it takes neither.
    """
    option = getattr(exc, "option_name", None)
    if option not in _SELECTOR_ALIASES:
        return None
    if getattr(exc, "possibilities", None):
        # Click found a near-miss of its own; two pieces of advice in one
        # message is worse than the better one alone.
        return None
    command = getattr(exc.ctx, "command", None)
    accepted = {
        name
        for param in getattr(command, "params", [])
        if param.param_type_name == "option"
        for name in param.opts
    }
    if "--where" in accepted:
        # ``--key`` is defined alongside every ``--where``, so arriving here
        # means a near-miss spelling of it.
        return "this command selects entries with --key or --where"
    arguments = [
        param.name
        for param in getattr(command, "params", [])
        if param.param_type_name == "argument"
    ]
    if any(name in {"key", "citekey", "citekeys"} for name in arguments):
        return "this command takes the citation key as a positional argument"
    return None


def _annotate_usage_error(exc: click.UsageError) -> None:
    """Append selector advice to a usage error in place, when any applies.

    The message is rewritten on the exception itself so both routes out of this
    group — Click's own usage text for a human, and the JSON envelope — carry
    the same advice without either having to know about the other.
    """
    hint = _selector_hint(exc)
    if hint and hint not in str(exc.message):
        exc.message = f"{exc.message} ({hint})"


def _command_path(ctx: click.Context, name: str) -> tuple[str, ...]:
    """Return the full command path of subcommand *name* below *ctx*: ``("ref", "show")``."""
    names: list[str] = [name]
    current: click.Context | None = ctx
    while current is not None and current.parent is not None:
        names.append(current.info_name or "")
        current = current.parent
    return tuple(reversed(names))


def _exit_one(exc: click.UsageError) -> None:
    """Report a usage error with exit code 1, the code of every other error."""
    exc.exit_code = 1


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
            or _source_name(ctx, param) != "COMMANDLINE"
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
        try:
            if args and "--help" not in args and "-h" not in args and not _is_shell_completion():
                command = self.get_command(ctx, args[0])
                if command is not None and not hasattr(command, "commands"):
                    path = _command_path(ctx, args[0])
                    args[1:] = place_library(path, command, args[1:], json_output)
            return super().parse_args(ctx, args)
        except _USAGE_ERRORS as exc:
            _annotate_usage_error(exc)
            _exit_one(exc)
            if json_output:
                _emit_error(True, "UsageError", exc.format_message())
            raise

    def main(
        self, args: list[str] | None = None, prog_name: str | None = None, **extra: object
    ) -> object:
        """Override :meth:`click.BaseCommand.main` to report usage errors as pynakes does.

        Click's ``main()`` wraps ``invoke()`` in a try/except that converts a
        ``UsageError`` to its own report and exit code 2 in standalone mode,
        bypassing the ``invoke`` override, so it is intercepted here too. A usage
        error exits 1 in both output modes: exit 2 is pynakes's conflict code.
        """
        json_output = "--json" in (args if args is not None else sys.argv[1:])
        try:
            return super().main(args=args, prog_name=prog_name, **extra)
        except _USAGE_ERRORS as exc:
            _annotate_usage_error(exc)
            _exit_one(exc)
            if json_output:
                _emit_error(True, "UsageError", exc.format_message())
            raise

    def invoke(self, ctx: click.Context) -> object:
        """Override :meth:`click.Group.invoke` to catch ``UsageError`` raised during
        subcommand argument parsing (visible in ``standalone_mode=False`` paths such
        as the test runner)."""
        try:
            return super().invoke(ctx)
        except _USAGE_ERRORS as exc:
            _annotate_usage_error(exc)
            _exit_one(exc)
            if not ctx.meta.get(_JSON_META_KEY, False):
                raise  # Humans keep Click's usage text, on stderr.
            _emit_error(True, "UsageError", exc.format_message())
