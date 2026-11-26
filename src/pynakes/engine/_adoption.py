"""Stage Pinax adoption and commit it with bibliography bytes and durable recovery."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes.bibtex_parser import ParseError, parse_bib
from pynakes.editing import set_entry_field
from pynakes.fields import check_field_value
from pynakes.filestore._adoption import ROLES, adoption_outputs, plan_adoption
from pynakes.filestore._transaction import Output, commit, contained, retained_warnings
from pynakes.io import _decode_bytes, encode_text
from pynakes.metadata import metadata_value

if TYPE_CHECKING:
    from pynakes.engine import Bibliography


def adoption_policy(coll: Bibliography, mode: str | None, role: str | None) -> tuple[str, str]:
    """Resolve attachment policy once for bibliography and Library acquisition."""
    mode = mode or metadata_value(coll.lib, "pinax-adopt-mode") or "move"
    role = role or metadata_value(coll.lib, "pinax-adopt-role") or "unclassified"
    if mode not in {"move", "copy"} or role not in ROLES:
        raise ValueError("Invalid Pinax adoption mode or role")
    return mode, role


def stage_adoption(
    coll: Bibliography,
    key: str,
    source: str | Path,
    *,
    mode: str | None = None,
    role: str | None = None,
) -> dict:
    """Stage an attachment using member settings; never touch source bytes yet."""
    if coll.path is None or coll.files is None:
        raise ValueError("File adoption requires configured Pinax storage")
    entries = coll.lib.entries.get_all(key)
    if len(entries) != 1:
        raise ValueError("File adoption requires one unambiguous citation key")
    mode, role = adoption_policy(coll, mode, role)
    source = Path(source).expanduser().absolute()
    if source.is_symlink():
        raise ValueError("Select a regular source file, not a symbolic link")
    store = coll.files
    contained(coll.path.parent.resolve(), store.root)
    if source.resolve() == coll.path.resolve():
        raise ValueError("Cannot adopt the owning bibliography as a material")
    if mode == "move":
        check_source_owners(coll, source, key)
    previous = coll._material_adoptions[-1][0].manifest if coll._material_adoptions else None
    plan = plan_adoption(store, key, source, role=role, manifest=previous)
    if mode == "move" and plan.source != plan.target and plan.source.is_relative_to(store.root):
        raise ValueError("Existing Pinax materials must be copied, not moved")
    relative = Path(os.path.relpath(plan.target, coll.path.parent)).as_posix()
    descriptor = (
        ":"
        + relative.replace(":", r"\:").replace(";", r"\;")
        + ":"
        + (plan.target.suffix.lstrip(".").upper() or "FILE")
    )
    entry = entries[0]
    # Structured splitting is needed because escaped semicolons may occur in paths.
    from pynakes.files import parse_file_field, resolve_linked_file

    retained = []
    linked = False
    for link in parse_file_field(entry):
        resolve_linked_file(link, coll.path.resolve(), [], coll.lib)
        if (
            link.resolved_path
            and link.resolved_path.resolve() == plan.source
            and plan.source != plan.target
        ):
            continue
        retained.append(link.raw)
        linked = linked or link.path == relative
    if not linked:
        retained.append(descriptor)
    value = ";".join(retained)
    check_field_value("file", value)
    set_entry_field(entry, "file", value)
    coll._material_adoptions.append((plan, mode))
    return {**plan.to_dict(), "mode": mode, "key": key}


def commit_adoptions(coll: Bibliography, new_text: str) -> list[str]:
    """Commit material bytes before links; journal survives any interrupted write.

    Returns warnings for moved originals that had to be kept.
    """
    assert coll.path is not None and coll.files is not None
    store = coll.files
    root = coll.path.parent.resolve()
    if coll._pinax_renames or coll._pinax_material_merges or coll._tex_rewrites:
        raise ValueError("Commit adoption separately from key renames, merges or TeX rewrites")
    bib = coll.path.resolve()
    # The checks save_text makes, before any material moves.
    if bib.exists() and not os.access(bib, os.W_OK):
        raise OSError(f"{coll.path} is read-only; nothing was written")
    data = encode_text(new_text, coll.lib.encoding)
    try:
        parse_bib(_decode_bytes(data)[0])
    except ParseError as exc:
        raise OSError(f"Validation failed: {exc}") from exc
    outputs, guards, removals = adoption_outputs(store, coll._material_adoptions, root)
    guards[bib] = coll.source_fingerprint.sha256 if coll.source_fingerprint else None
    outputs.append(Output(bib, guards[bib], data))
    report = commit(
        root,
        root / ".pynakes-ingest" / coll.path.name,
        outputs,
        guards,
        {"file": str(coll.path), "materials": len(coll._material_adoptions)},
        remove_sources=removals,
        recover_command="asset recover",
    )
    return retained_warnings(report)


def check_source_owners(coll: Bibliography, source: Path, key: str | None) -> None:
    """Refuse a move that would break another entry's existing attachment."""
    from pynakes.files import parse_file_field, resolve_linked_file

    assert coll.path is not None
    for entry in coll.lib.entries.values():
        if entry.key == key:
            continue
        for link in parse_file_field(entry):
            resolve_linked_file(link, coll.path.resolve(), [], coll.lib)
            if link.resolved_path and link.resolved_path.resolve() == source.resolve():
                raise ValueError("Source is linked by another entry; use copy mode")
