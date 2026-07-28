"""Machine-readable description of what pynakes can do.

Kept in sync with the actually-implemented CLI commands so agents can introspect
the tool rather than guessing. Update this when commands are added or removed.
"""

from pynakes import __all__ as PUBLIC_API_EXPORTS
from pynakes import __version__ as VERSION
from pynakes.query import FUZZY_THRESHOLD, WHERE_GRAMMAR

# Stable type vocabulary for command-schema introspection. The on-disk click
# type names are mapped to this small, version-independent set so the pinned
# `capabilities` schema does not change shape when Typer/click internals do.
_TYPE_VOCABULARY = {
    "text": "string",
    "boolean": "boolean",
    "integer": "integer",
    "path": "path",
    "filename": "path",
    "file": "path",
    "choice": "choice",
}

# Error/conflict codes a caller may see in the JSON envelope's ``error`` field,
# enumerated so callers can route on them explicitly. Grouped by the exit
# code / status they accompany. Kept in sync with the codes the CLI emits.
_ERROR_CODES = {
    "error": {
        "exit_code": 1,
        "codes": {
            "FileNotFound": "A given file does not exist.",
            "FileExists": "init: the target .bib already exists (pass --force to overwrite).",
            "ParseError": "A .bib or source file could not be parsed (includes 'line').",
            "InvalidInput": "An argument, option, or predicate was invalid.",
            "IOError": "A read or write failed.",
            "NoSources": "tex scan: no sources given and no 'tex-sources' metadata to use.",
            "InvalidNamespace": "metadata set: namespace was not 'jabref' or 'pynakes'.",
            "InvalidNormalizeOption": "normalize: an option value was not allowed.",
            "RecursiveFormatError": "format --recursive: one or more files failed.",
            "FormatLintError": "format: lint errors make a lossless rewrite unsafe.",
            "KeyNotFound": "A referenced citation key is not in the library (remove, keys rename, etc.).",
            "InvalidIdentifier": "import: an identifier value was malformed.",
            "UnsupportedIdentifier": "import: no provider recognized the identifier or URL.",
            "ReferenceImportError": "import: provider metadata could not be resolved or imported.",
        },
    },
    "conflict": {
        "exit_code": 2,
        "codes": {
            "ExternalModification": "The file changed on disk since it was read.",
            "DuplicateMetadata": "metadata set: multiple blocks match the key (ambiguous).",
            "DuplicateMergeKey": "combine/split --dedupe: a shared key has differing content.",
            "DedupeConflict": "dedupe merge: a cluster has irreconcilable field values.",
            "DuplicateReference": "import: the provider identity is already present.",
            "CitationKeyConflict": "import: the chosen citation key already exists.",
            "DuplicateCitationKey": "ref show/edit: the citation key identifies multiple entries.",
        },
    },
}

# One transversal selector surface: the same grammar for every command that
# addresses a set of entries. Described by `pynakes.query`, so the capability
# description cannot drift from the parser.
_PREDICATE_GRAMMAR = {
    "used_by": [
        "fields (--where)",
        "search (--where)",
        "format (--where)",
        "corpus combine (--where)",
        "corpus split (--to)",
        "batch (fields.* where)",
    ],
    "bucket_predicates_used_by": ["corpus split (--to)"],
    **WHERE_GRAMMAR,
}

_SEARCH_QUERY_GRAMMAR = {
    "terms": "Whitespace-separated terms are ANDed.",
    "phrases": "Quoted phrases stay together.",
    "field_prefix": "field:term scopes a term to one field; key: and type: are special fields.",
    "examples": [
        "learning",
        '"natural language"',
        "title:learning type:article",
        'author:"Jane Example"',
    ],
    "matched_fields": (
        "Each result reports the field(s) it matched: key, type, or any stored "
        "field name (title, author, groups, abstract, ...)."
    ),
    "match_explanations": (
        "Each result also reports one entry per hit in `matches`: field, term, "
        "kind (exact|fuzzy), score, and the matching excerpt; `score` on the "
        "result is the weakest term score."
    ),
    "fuzzy": (
        f"--fuzzy also matches near-misses by normalized similarity >= "
        f"{FUZZY_THRESHOLD} (misspellings, inflections). `--where 'title ~ \"…\"'` "
        f"applies the same similarity as a selector."
    ),
    "selection": (
        "--where narrows which entries are searched using the shared predicate "
        "grammar, covering date ranges (year >= 2020) and missing-field "
        "questions (abstract missing) without command-specific flags."
    ),
    "ranking": (
        "Results are ranked by relevance by default: key > title > author > "
        "other fields > groups/abstract, then by match score, ties kept in file "
        "order. --no-rank restores plain file order."
    ),
}


# Single source of truth for how commands are grouped by nature, shared by the
# CLI ``--help`` panels (``cli.py`` reads this for ``rich_help_panel``) and the
# ``command_groups`` field of the capability description. Ordered: panels render
# in this order, and the commands within each panel in this order. Every
# top-level command/group must appear in exactly one panel — guarded by tests.
COMMAND_GROUPS: dict[str, list[str]] = {
    "Inspect & validate": ["inspect", "search", "lint", "verify", "capabilities"],
    "Edit references": [
        "ref",
        "format",
        "normalize",
        "convert",
        "enrich",
        "dedupe",
        "fields",
        "keys",
        "groups",
        "metadata",
        "tex",
    ],
    "Materials (pinax)": ["asset"],
    "Corpus (multiple files)": ["corpus"],
    "Create": ["init"],
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
    return text.replace("\\[", "[")


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
        entry["flags"] = list(param.opts)
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
        "arguments": arguments,
        "options": options,
    }


def _walk_commands(group, prefix: str, out: dict) -> None:
    # A subcommand group exposes a ``commands`` mapping; a leaf command does not.
    # (Checked structurally rather than by isinstance, since Typer vendors its
    # own click fork whose Group is not the public ``click.Group``.)
    for name, command in sorted(group.commands.items()):
        full = f"{prefix}{name}"
        if hasattr(command, "commands"):
            _walk_commands(command, f"{full} ", out)
        else:
            out[full] = _command_schema(command)


def command_schemas() -> dict:
    """Introspect the live CLI into a per-command schema map.

    Derived from the actual Typer/click application, so it can never drift from
    the real command surface. Each entry (keyed by full command path, e.g.
    ``"groups add-entry"``) lists the command's help, positional ``arguments``,
    and ``options`` with stable type names, flags, defaults, and choices.
    """
    from typer.main import get_command

    from pynakes.cli import app

    schemas: dict = {}
    _walk_commands(get_command(app), "", schemas)
    return schemas


def get_capabilities() -> dict:
    """Return a structured description of supported operations and commands."""
    return {
        "tool": "pynakes",
        "version": VERSION,
        "description": (
            "BibTeX/BibLaTeX maintenance with minimal diffs, dry-run previews, "
            "atomic writes, structured JSON, and JabRef interoperability."
        ),
        "network_access_is_explicit": True,
        "supports_dry_run": True,
        "supports_json_output": True,
        "supports_backup": True,
        "supports_atomic_write": True,
        "supports_multiple_files": True,
        "python_api": {
            "facade": "pynakes.Bibliography",
            "public_exports": list(PUBLIC_API_EXPORTS),
            "constructors": [
                "Bibliography.open",
                "Bibliography.from_text",
                "Bibliography.from_bibfile",
            ],
            "review": ["preview", "diff", "change_plan", "lint"],
            "persistence": ["commit", "reset", "reload", "externally_changed"],
            "transport_independent": True,
        },
        # Two structurally identical metadata comment namespaces are read and
        # merged (pynakes-meta overrides jabref-meta). `metadata set` routes a
        # JabRef-native key to jabref-meta only when the file is already
        # JabRef-tracked (carries jabref-meta); otherwise it, like every
        # pynakes-owned key, stays in pynakes-meta. `metadata adopt-jabref`
        # establishes tracking so JabRef-native keys are mirrored from then on.
        "metadata_namespaces": ["jabref-meta", "pynakes-meta"],
        "exit_codes": {
            "0": "success",
            "1": "error (parse, validation, I/O)",
            "2": "conflict (operation blocked; options returned)",
        },
        # Read-only checks that accept one or more .bib files and support
        # --strict (exit 1 on findings) — the primitives for CI / pre-commit
        # gating. A single file keeps the per-file envelope; multiple files
        # emit an aggregate {status, action, strict, files, summary} envelope.
        "gate_commands": [
            "lint",
            "verify",
            "keys check",
            "asset check",
            "dedupe check",
        ],
        "capabilities": [
            "parse_bibtex",
            "create_library",
            "inspect_library",
            "lint",
            "manage_groups",
            "manage_group_tree",
            "manage_fields",
            "protect_title_capitalization",
            "generate_keys",
            "rename_citation_keys",
            "detect_duplicate_keys",
            "repair_duplicate_keys",
            "detect_duplicate_works",
            "compare_work_evidence",
            "merge_duplicate_works",
            "verify_references",
            "check_published_preprints",
            "backfill_arxiv_ids",
            "enrich_metadata",
            "normalize_library",
            "format_bibliography",
            "convert_to_biblatex",
            "convert_to_bibtex",
            "export_csl_json",
            "export_ris",
            "export_mods",
            "export_endnote",
            "export_csv",
            "import_csl_json",
            "import_ris",
            "import_mods",
            "import_endnote",
            "normalize_journals",
            "normalize_authors",
            "normalize_dois",
            "import_reference",
            "search_library",
            "detect_used_citations",
            "remove_entries",
            "combine_libraries",
            "partition_library",
            "inspect_metadata",
            "update_metadata",
            "validate_linked_files",
            "pinax_filestore",
            "pinax_arxiv_download_core",
            "pinax_fetch",
            "pinax_agent_surface",
            "pinax_manifest",
            "pinax_setops",
            "pinax_key_edits",
        ],
        # Commands grouped by nature (single source of truth shared with the CLI
        # ``--help`` panels). Mirrors the flat ``commands`` map below.
        "command_groups": {panel: list(names) for panel, names in COMMAND_GROUPS.items()},
        "commands": {
            "init": "Create a new .bib library, optionally seeded with a metadata profile (--pinax for pinax mode)",
            "inspect": "Inspect a .bib file structure",
            "lint": "Validate entries and report issues",
            "ref": "Create, show, edit, import, and remove individual references "
            "(add, show, edit, import, remove)",
            "groups": "Manage entry groups and group hierarchy "
            "(list, list-entries, add-entry, remove-entry, tree, add-group, "
            "remove-group, rename-group, move-group, update-group)",
            "keys": "Generate, check, rename, and repair citation keys",
            "fields": "Bulk-edit fields across matching references "
            "(set, rename, move, append, clear, protect-title)",
            "dedupe": "Detect and conservatively merge duplicate works",
            "verify": "Verify entries against authoritative metadata "
            "(--published also reports published/preprint identity links)",
            "enrich": "Conservatively fill missing metadata "
            "(--published also promotes preprints and backfills arXiv ids)",
            "tex": "Manage linked TeX sources and scan them for citations "
            "(list, add, remove, clear, scan)",
            "metadata": "Inspect and update top-level library metadata "
            "(list, set, remove, adopt-jabref)",
            "normalize": "Normalize entries (titles, authors, journals, DOIs, "
            "identifier case, ordering) per the library's configured settings",
            "format": "Lint, then rewrite bibliography layout with portable profile settings "
            "and explicit policy overrides",
            "convert": "Convert between BibTeX/BibLaTeX dialects and interchange "
            "formats (export/import CSL-JSON, RIS, MODS, EndNote, and export CSV)",
            "search": "Search entries by free text, phrases, or field-scoped terms",
            "asset": "Fetch and validate Pinax materials — arXiv PDF/source, "
            "open or institutionally entitled published/supplement PDF download, "
            "and linked-file checks (fetch, check)",
            "corpus": "Operate across multiple .bib files (combine, split, batch)",
            "capabilities": "Show this capability description",
        },
        # Self-description for agents: the full per-command schema (args/options/
        # types) derived from the live CLI, the enumerated error/conflict codes,
        # and the one selector grammar shared by every entry-addressable command.
        "command_schemas": command_schemas(),
        "error_codes": _ERROR_CODES,
        "predicate_grammar": _PREDICATE_GRAMMAR,
        "search_query_grammar": _SEARCH_QUERY_GRAMMAR,
        "formatting": {
            "lint_gate": (
                "Formatting runs lint and refuses findings that make a canonical "
                "rewrite lossy (currently repeated fields)."
            ),
            "profile_prefix": "format-",
            "defaults": {
                "indent": 2,
                "alignment": "compact",
                "trailing_comma": True,
                "blank_lines": True,
                "field_order": "preferred",
                "entry_order": "preserve",
                "block_order": "canonical",
                "wrap_values": "off",
                "line_width": 100,
            },
            "choices": {
                "alignment": ["compact", "equals"],
                "field_order": ["preferred", "preserve", "alphabetical"],
                "entry_order": ["preserve", "key", "profile"],
                "block_order": ["preserve", "canonical"],
                "wrap_values": ["off", "stable", "canonical"],
            },
            "wrapping": {
                "never": [
                    "verbatim identifiers and paths",
                    "date fields",
                    "bare macros and numbers",
                    "concatenated expressions",
                ],
                "names": "break only between top-level names",
                "prose": "break only at brace- and math-top-level whitespace",
                "delimiters": "preserved",
            },
            "selection": (
                "--where reformats only the matching entries and leaves every "
                "other byte untouched. A selection owns the layout inside an "
                "entry, so the whole-file options --entry-order, --block-order, "
                "and --blank-lines cannot be combined with it."
            ),
        },
        "work_matching": {
            "module": "pynakes.identity",
            "statuses": ["exact", "probable", "conflict", "unknown"],
            "exact": "At least one normalized identifier matches and none conflict.",
            "probable": "Metadata similarity passes conservative title/year/author rules.",
            "conflict": "The candidates carry incompatible values for one identifier kind.",
            "unknown": "Available evidence does not support a match.",
            "non_work_identity": ["orcid"],
            "relationships_are_separate": True,
            "offline": True,
        },
        # The operations accepted by `batch` (op name → required/optional params).
        "batch_operations": _batch_operations(),
    }


def _batch_operations() -> dict:
    from pynakes.batch import operation_catalog

    return operation_catalog()
