"""Machine-readable description of what pynakes can do.

Kept in sync with the actually-implemented CLI commands so agents can introspect
the tool rather than guessing. Update this when commands are added or removed.
"""

from pynakes import __version__ as VERSION

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
# enumerated so agents can branch on them deterministically. Grouped by the exit
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
            "NoSources": "used: no sources given and no 'tex-sources' metadata to use.",
            "InvalidNamespace": "metadata set: namespace was not 'jabref' or 'pynakes'.",
            "InvalidNormalizeOption": "normalize: an option value was not allowed.",
            "KeyNotFound": "A referenced citation key is not in the library (remove, keys rename, etc.).",
            "InvalidIdentifier": "add: an identifier value was malformed.",
            "UnsupportedIdentifier": "add: the identifier was not a DOI, arXiv id/URL, or supported journal URL.",
            "ReferenceImportError": "add: a DOI/arXiv reference could not be resolved or imported.",
        },
    },
    "conflict": {
        "exit_code": 2,
        "codes": {
            "ExternalModification": "The file changed on disk since it was read.",
            "DuplicateMetadata": "metadata set: multiple blocks match the key (ambiguous).",
            "DuplicateMergeKey": "combine/split --dedupe: a shared key has differing content.",
            "DedupeConflict": "dedupe merge: a cluster has irreconcilable field values.",
            "DuplicateReference": "add: the DOI/arXiv reference is already present.",
            "CitationKeyConflict": "add: the chosen citation key already exists.",
        },
    },
}

# The predicate grammar shared by `fields --where`, `search --where`, and
# `split --to` rules.
_PREDICATE_GRAMMAR = {
    "used_by": ["fields (--where)", "search (--where)", "split (--to)"],
    "field_operators": ["contains", "=", "==", "exists"],
    "special_fields": {"type": "the entry type", "key": "the citation key"},
    "split_predicates": {
        "*": "matches every entry (catch-all / rest bucket)",
        "used": "citation key appears in the --tex/--aux sources",
        "unused": "citation key does not appear in the sources",
        'group "Name"': "entry belongs to the named group",
    },
    "examples": [
        'title contains "digital currency"',
        "type = article",
        "doi exists",
        'group "Machine Learning"',
        "used",
        "*",
    ],
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
}


def _stable_type(param) -> str:
    """Map a click parameter's type to the stable vocabulary, marking lists."""
    if getattr(param, "is_flag", False):
        return "boolean"
    raw = (getattr(param.type, "name", "") or "").lower()
    base = _TYPE_VOCABULARY.get(raw, "string")
    is_list = bool(getattr(param, "multiple", False)) or getattr(param, "nargs", 1) == -1
    return f"list[{base}]" if is_list else base


def _param_schema(param) -> dict:
    """Describe one click argument or option as a JSON-friendly dict."""
    entry: dict[str, object] = {
        "name": param.name,
        "type": _stable_type(param),
        "required": bool(param.required),
    }
    help_text = (getattr(param, "help", "") or "").strip()
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
    help_text = (command.help or command.short_help or "").strip().splitlines()
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
            "Small, reviewable, deterministic edits to BibTeX/BibLaTeX .bib files — "
            "minimal diffs, dry-run previews, atomic writes, and structured JSON — safe "
            "for scripts, CI, and LLM agents. Losslessly interoperable with JabRef and "
            "the BibTeX/BibLaTeX toolchain."
        ),
        "safe_by_default": True,
        "supports_dry_run": True,
        "supports_json_output": True,
        "supports_backup": True,
        "supports_atomic_write": True,
        "supports_multiple_files": True,
        # Two structurally identical metadata comment namespaces are read and
        # merged (pynakes-meta overrides jabref-meta). `metadata set` routes a
        # key to jabref-meta when JabRef understands it, else pynakes-meta.
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
            "files check",
            "dedupe check",
        ],
        "capabilities": [
            "parse_bibtex",
            "create_library",
            "inspect_library",
            "lint",
            "manage_groups",
            "manage_fields",
            "protect_title_capitalization",
            "generate_keys",
            "rename_citation_keys",
            "detect_duplicate_keys",
            "repair_duplicate_keys",
            "detect_duplicate_works",
            "merge_duplicate_works",
            "verify_references",
            "check_published_preprints",
            "enrich_metadata",
            "normalize_library",
            "convert_to_biblatex",
            "convert_to_bibtex",
            "export_csl_json",
            "export_ris",
            "export_mods",
            "export_endnote",
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
            "inspect_jabref_metadata",
            "update_jabref_metadata",
            "validate_linked_files",
            "pinax_filestore",
            "pinax_arxiv_download_core",
            "pinax_fetch",
            "pinax_agent_surface",
            "pinax_manifest",
            "pinax_setops",
            "pinax_key_edits",
        ],
        "commands": {
            "init": "Create a new .bib library, optionally seeded with a metadata profile (--pinax for pinax mode)",
            "inspect": "Inspect a .bib file structure",
            "lint": "Validate entries and report issues",
            "groups": "Manage entry groups (list, add-entry, remove-entry)",
            "keys": "Generate, check, rename, and repair citation keys",
            "fields": "Edit fields (rename, move, append, clear, protect-title)",
            "files": "Validate linked-file references and Pinax material presence/drift",
            "dedupe": "Detect and conservatively merge duplicate works",
            "verify": "Verify entries against authoritative metadata "
            "(--published also reports preprints with a published version)",
            "enrich": "Conservatively fill missing metadata "
            "(--published also promotes preprints to their published version)",
            "metadata": "Inspect and update top-level library metadata",
            "normalize": "Run the standard normalization routine",
            "convert": "Convert between BibTeX/BibLaTeX dialects and interchange "
            "formats (export/import CSL-JSON, RIS, MODS, and EndNote)",
            "add": "Add a reference by DOI, arXiv identifier, or journal article URL; optionally fetch configured Pinax arXiv materials",
            "fetch": "Download arXiv materials (PDF and source) into the Pinax files-dir",
            "search": "Search entries by free text, phrases, or field-scoped terms",
            "used": "Report/tag/export entries cited in LaTeX sources",
            "combine": "Union several .bib files into one (optionally deduping by key), copying Pinax materials when present",
            "split": "Combine inputs and route entries into several outputs by predicate, copying Pinax materials when present",
            "remove": "Remove one or more entries by citation key (removes Pinax materials by default)",
            "batch": "Apply a sequence of operations atomically (one preview, one commit)",
            "capabilities": "Show this capability description",
        },
        # Self-description for agents: the full per-command schema (args/options/
        # types) derived from the live CLI, the enumerated error/conflict codes,
        # and the predicate grammar shared by `fields --where` and `split --to`.
        "command_schemas": command_schemas(),
        "error_codes": _ERROR_CODES,
        "predicate_grammar": _PREDICATE_GRAMMAR,
        "search_query_grammar": _SEARCH_QUERY_GRAMMAR,
        # The operations accepted by `batch` (op name → required/optional params).
        "batch_operations": _batch_operations(),
    }


def _batch_operations() -> dict:
    from pynakes.batch import operation_catalog

    return operation_catalog()
