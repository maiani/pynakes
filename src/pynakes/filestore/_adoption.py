"""Content-addressed local material adoption, independent of acquisition providers.

Version-1 manifests retain their fixed-role records. An optional ``variants``
array adds immutable objects; citation-key renames move the containing row, not
objects or relative attachment links. No migration rewrites existing files.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes.filestore._manifest import _manifest_row, _sha256_path, _validate_key

if TYPE_CHECKING:
    from pynakes.filestore import FileStore
    from pynakes.filestore._transaction import Output

ROLES = frozenset({"unclassified", "published", "preprint", "supplement", "erratum"})


def variant_path(root: Path, record: dict) -> Path:
    """Validate a variant's contained, content-addressed path."""
    digest = record.get("sha256", "")
    name = record.get("path", "")
    if (
        not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or not isinstance(name, str)
        or not re.fullmatch(rf"\.pinax/objects/{digest}\.[a-z0-9]{{1,12}}", name)
        or record.get("role") not in ROLES
    ):
        raise ValueError("Invalid Pinax variant record")
    path = root / name
    for part in (root, root / ".pinax", path.parent, path):
        if part.is_symlink():
            raise ValueError(f"Symlink in Pinax object path: {part}")
    return path


@dataclass(frozen=True)
class MaterialAdoption:
    """A read-only adoption plan with original and destination fingerprints."""

    source: Path
    target: Path
    sha256: str
    manifest: dict
    manifest_before: str | None
    record: dict
    target_before: str | None

    def to_dict(self) -> dict:
        return {"source": str(self.source), "target": str(self.target), **self.record}


def plan_adoption(
    store: FileStore,
    key: str,
    source: str | Path,
    *,
    role: str = "unclassified",
    manifest: dict | None = None,
) -> MaterialAdoption:
    """Plan an unchanged local-file copy; never create directories or records.

    ``manifest`` permits composing several plans over one staged manifest. The
    external source name is provenance, never a paper title or role heuristic.
    """
    _validate_key(key)
    if role not in ROLES:
        raise ValueError(f"Unknown material role: {role}")
    source = Path(source).expanduser().absolute()
    if source.is_symlink():
        raise ValueError("Select a regular source file, not a symbolic link")
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError("Material source must be a regular file")
    digest = _sha256_path(source)
    suffix = source.suffix.lower().lstrip(".")
    if not re.fullmatch(r"[a-z0-9]{1,12}", suffix):
        suffix = "bin"
    record = {
        "sha256": digest,
        "role": role,
        "path": f".pinax/objects/{digest}.{suffix}",
        "sources": [{"path": str(source), "filename": source.name}],
        "refetchable": False,
    }
    target = variant_path(store.root, record)
    if target.exists() and (not target.is_file() or _sha256_path(target) != digest):
        raise ValueError(f"Pinax object collision: {target}")
    updated = deepcopy(manifest if manifest is not None else store.read_manifest())
    row = _manifest_row(updated, key, create=True)
    variants = row.setdefault("variants", [])
    if not isinstance(variants, list):
        raise ValueError("Invalid Pinax variants")
    for existing in variants:
        variant_path(store.root, existing)
        if existing["sha256"] == digest and existing["role"] == role:
            for occurrence in record["sources"]:
                if occurrence not in existing["sources"]:
                    existing["sources"].append(occurrence)
            record = existing
            target = variant_path(store.root, record)
            break
    else:
        variants.append(record)
    before = _sha256_path(store.manifest_path) if store.manifest_path.exists() else None
    return MaterialAdoption(
        source,
        target,
        digest,
        updated,
        before,
        record,
        _sha256_path(target) if target.exists() else None,
    )


def adoption_outputs(
    store: FileStore, plans: list[tuple[MaterialAdoption, str]], root: Path
) -> tuple[list[Output], dict[Path, str | None], list[dict]]:
    """Compose the shared object/manifest writes and last-step source removals."""
    from pynakes.filestore._transaction import Output, contained, json_bytes

    objects: dict[Path, Output] = {}
    guards: dict[Path, str | None] = {}
    removals = []
    for plan, mode in plans:
        guards[plan.source] = plan.sha256
        guards[store.manifest_path] = plan.manifest_before
        objects[plan.target] = Output(plan.target, plan.target_before, plan.source)
        if mode == "move" and plan.source != plan.target:
            if plan.source.is_relative_to(store.root) or plan.source == store.bib_path:
                raise ValueError("Existing Pinax materials or bibliography must not be moved")
            removals.append(
                {
                    "path": str(plan.source),
                    "sha256": plan.sha256,
                    "target": contained(root, plan.target),
                }
            )
    outputs = list(objects.values())
    if plans:
        outputs.append(
            Output(
                store.manifest_path, guards[store.manifest_path], json_bytes(plans[-1][0].manifest)
            )
        )
    return outputs, guards, removals


def adopt_file(
    store: FileStore,
    key: str,
    source: str | Path,
    *,
    role: str = "unclassified",
    mode: str = "move",
) -> MaterialAdoption:
    """Adopt bytes and provenance with recovery; remove the source last in move mode.

    This low-level operation does not edit a bibliography. Applications adding
    an attachment should use ``Bibliography.adopt_file`` and commit instead.
    """
    from pynakes.filestore._transaction import commit

    if mode not in {"move", "copy"}:
        raise ValueError("Material mode must be move or copy")
    plan = plan_adoption(store, key, source, role=role)
    outputs, guards, removals = adoption_outputs(store, [(plan, mode)], store.root)
    commit(
        store.root,
        store.root / ".pinax" / "adoption",
        outputs,
        guards,
        plan.to_dict(),
        remove_sources=removals,
    )
    return plan


def material_variants(
    store: FileStore, key: str, *, verify: bool = True, manifest: dict | None = None
) -> list[dict]:
    """Return variants with explicit presence and checksum diagnostics.

    ``verify=False`` skips hashing and reports ``intact`` as None, for reads that
    need only presence. A record this version cannot use (an unknown role, say,
    from a newer version) is reported with ``invalid`` instead of raising, and
    its path is never touched. ``manifest`` reuses an already-read manifest.
    """
    data = manifest if manifest is not None else store.read_manifest()
    row = _manifest_row(data, key, create=False) or {}
    variants = row.get("variants", [])
    if not isinstance(variants, list):
        raise ValueError("Invalid Pinax variants")
    result = []
    for record in variants:
        try:
            path = variant_path(store.root, record)
        except ValueError as exc:
            base = record if isinstance(record, dict) else {}
            result.append(
                {
                    **base,
                    "absolute_path": None,
                    "present": False,
                    "intact": False,
                    "invalid": str(exc),
                }
            )
            continue
        present = path.is_file()
        intact = (present and _sha256_path(path) == record["sha256"]) if verify else None
        result.append({**record, "absolute_path": str(path), "present": present, "intact": intact})
    return result


def variant_copy_plan(source: FileStore, target: FileStore, key: str) -> list[dict[str, str]]:
    """Plan verified immutable-object copies for existing material operations."""
    planned = []
    for record in material_variants(source, key):
        if not record["intact"]:
            raise ValueError(f"Missing or changed source variant for {key}")
        src, dst = variant_path(source.root, record), variant_path(target.root, record)
        if dst.exists() and _sha256_path(dst) != record["sha256"]:
            raise ValueError(f"Pinax object collision: {dst}")
        if src != dst:
            planned.append(
                {"key": key, "kind": "variant", "source_path": str(src), "path": str(dst)}
            )
    return planned


def removable_variants(store: FileStore, key: str) -> list[Path]:
    """Only retire objects not addressed by another citation key."""
    manifest = store.read_manifest()
    files = manifest["files"]
    assert isinstance(files, dict)
    shared = {r["path"] for k, row in files.items() if k != key for r in row.get("variants", [])}
    return [
        variant_path(store.root, r)
        for r in material_variants(store, key)
        if r["path"] not in shared
    ]
