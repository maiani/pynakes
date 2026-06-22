"""Machine-readable description of what pynakes can do.

Kept in sync with the actually-implemented CLI commands so agents can introspect
the tool rather than guessing. Update this when commands are added or removed.
"""

VERSION = "0.1"


def get_capabilities() -> dict:
    """Return a structured description of supported operations and commands."""
    return {
        "tool": "pynakes",
        "version": VERSION,
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
            "abbreviate_journals",
            "normalize_authors",
            "normalize_dois",
            "import_doi",
            "detect_used_citations",
            "inspect_jabref_metadata",
            "update_jabref_metadata",
            "validate_linked_files",
        ],
        "commands": {
            "inspect": "Inspect a .bib file structure",
            "lint": "Validate entries and report issues",
            "groups": "Manage entry groups (list, add-entry, remove-entry)",
            "keys": "Generate, check, rename, and repair citation keys",
            "fields": "Edit fields (rename, move, append, clear, protect-title)",
            "files": "Validate JabRef linked files",
            "dedupe": "Detect and conservatively merge duplicate works",
            "verify": "Verify DOI-backed entries against provider metadata",
            "published": "Report and optionally apply published-version metadata for preprints",
            "enrich": "Conservatively fill missing metadata",
            "metadata": "Inspect and update top-level JabRef metadata",
            "normalize": "Run the standard normalization routine",
            "convert": "Convert a library between BibTeX and BibLaTeX conventions",
            "journals": "Abbreviate, expand, and check journal titles",
            "doi": "Import references by DOI",
            "used": "Report/tag/export entries cited in LaTeX sources",
            "capabilities": "Show this capability description",
        },
    }
