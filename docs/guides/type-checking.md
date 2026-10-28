# Type checking

The repository is type-checked with [ty](https://github.com/astral-sh/ty),
which Astral describes as beta. Run it from the repository root:

```sh
ty check
```

The same command runs in pre-commit and gates CI. The `dev` extra in
`pyproject.toml` pins the ty version, so a local run and CI report the same
diagnostics; update the pin deliberately, in its own change.

`[tool.ty]` in `pyproject.toml` configures the run: it checks `src/pynakes`
against Python 3.12, the lowest supported version, on all platforms at once,
so platform-specific names such as `ctypes` attributes are checked without
exemptions.

## The baseline

Each `[[tool.ty.overrides]]` table names one module and the rule families
ignored in it. Every other rule in that module, and every rule in every other
module, is enforced. The overrides record existing annotation debt, not
observed runtime failures, and the list only shrinks:

- Do not add an override, or a rule to an existing one, for new code. Fix the
  annotation instead.
- When a repair clears a module's last diagnostic of a rule family, remove that
  rule from the override, and the table once it is empty.

The remaining overrides cover a few kinds of code:

| Modules | What remains |
| --- | --- |
| `cli.py`, `cli_surface.py`, `cli_discovery.py` | Click subclasses typed against the Click that Typer vendors, and monkey-patched Typer hooks. |
| `cli_commands/` (`dedupe`, `import_ref`, `init`, `integrity`, `keys`, `remove`, `setops`) | `**details` envelopes passed to `_finish_mod`, which ty cannot match to its keyword parameters. |
| `bibtex_writer.py` | The loosely typed source-layout segments the writer reassembles. |
| `providers/_http.py` | The injectable `urlopen`-style opener, used as a context manager. |

`pyproject.toml` is the authoritative list; read it rather than this table when
the two differ.
