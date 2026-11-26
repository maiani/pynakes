"""Reviewable native PDF acquisition with durable per-source accounting."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import copy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from pynakes.editing import rename_entry_key
from pynakes.engine import Bibliography
from pynakes.engine._adoption import adoption_policy, check_source_owners
from pynakes.filestore._adoption import adoption_outputs
from pynakes.filestore._transaction import Output, commit, contained, digest, json_bytes
from pynakes.io import encode_text
from pynakes.keys import generate_key, unique_key
from pynakes.library._ingest_review import DECISION_KEYS, select_entry
from pynakes.pdf_import import _stage, inspect_pdf

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pynakes.library import Library


def state_path(library: Library) -> Path:
    if library.manifest is None:
        raise ValueError("Managed ingestion requires a Library manifest")
    return library.manifest.parent / ".pynakes-ingest" / library.manifest.stem


def read_ledger(library: Library) -> dict:
    """Read persistent source occurrences and decisions; no directory creation."""
    path = state_path(library) / "ledger.json"
    if not path.exists():
        return {"version": 1, "sources": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("sources"), dict):
        raise ValueError("Unsupported ingestion ledger")
    return data


def inputs(paths: Sequence[str | Path]) -> list[Path]:
    """Account for every immediate input, including unsupported files."""
    result = []
    for raw in paths:
        path = Path(raw).expanduser().absolute()
        if path.is_dir():
            result.extend(sorted(path.iterdir()) or [path])
        else:
            result.append(path)
    if not result:
        raise ValueError("Provide at least one source file or directory")
    return list(dict.fromkeys(result))


def _without_plan_hash(value):
    """Exclude only the self-referential fingerprint when hashing receipts."""
    if isinstance(value, dict):
        return {k: _without_plan_hash(v) for k, v in value.items() if k != "plan_sha256"}
    if isinstance(value, list):
        return [_without_plan_hash(v) for v in value]
    return value


@dataclass
class IngestionPlan:
    """Staged acquisition; creating or inspecting this object writes nothing.

    ``commit`` checks the full Library snapshot and every selected source, then
    publishes a durable roll-forward journal. Source removal is last. Reopen
    the Library before planning the next batch. Pending records are persisted
    even when no reference can be accepted.
    """

    library: Library
    report: dict
    outputs: list[Output]
    guards: dict[Path, str | None]
    removals: list[dict]

    @property
    def sha256(self) -> str:
        value = {
            "report": _without_plan_hash(self.report),
            "guards": {str(p): h for p, h in self.guards.items()},
            "outputs": [
                (
                    str(o.path),
                    o.before,
                    self.guards[o.data]
                    if isinstance(o.data, Path)
                    else hashlib.sha256(
                        json_bytes(_without_plan_hash(json.loads(o.data)))
                        if o.path == state_path(self.library) / "ledger.json"
                        else o.data
                    ).hexdigest(),
                )
                for o in self.outputs
            ],
            "removals": self.removals,
        }
        return hashlib.sha256(json_bytes(value)).hexdigest()

    @property
    def modifies(self) -> bool:
        """Whether applying the plan changes any file: an output's bytes or a source.

        The ledger is always an output, so its presence alone says nothing; a
        repeated plan that would rewrite identical bytes modifies nothing.
        """
        for output in self.outputs:
            after = (
                self.guards[output.data]
                if isinstance(output.data, Path)
                else hashlib.sha256(output.data).hexdigest()
            )
            if after != output.before:
                return True
        return bool(self.removals)

    def to_dict(self) -> dict:
        return {
            **self.report,
            "results": [
                {**r, "status": "planned" if r["status"] == "committed" else r["status"]}
                for r in self.report["results"]
            ],
            "plan_sha256": self.sha256,
        }

    def commit(self, *, expect_sha256: str | None = None) -> dict:
        """Apply the reviewed plan, refusing changed inputs or destinations."""
        if expect_sha256 is not None and expect_sha256 != self.sha256:
            raise ValueError("Ingestion plan differs from the reviewed preview")
        self.library._assert_current()
        state = state_path(self.library)
        assert self.library.manifest is not None
        return commit(
            self.library.manifest.parent,
            state,
            self.outputs,
            self.guards,
            {**self.report, "plan_sha256": self.sha256},
            remove_sources=self.removals,
        )


def prepare_ingestion(
    library: Library,
    paths: Sequence[str | Path],
    *,
    online: bool = False,
    decisions: dict[str, dict] | None = None,
    destination: str | Path | None = None,
    mode: str | None = None,
    role: str | None = None,
    cache_file: str | Path | None = None,
) -> IngestionPlan:
    """Plan PDF recovery, placement and adoption; unresolved files stay pending.

    Decisions are keyed by absolute source path and require ``sha256``. They
    may supply an identifier, reviewed record, exclusion reason, destination,
    role, mode or an explicitly requested lookup query. Network is opt-in.
    All members and stores must be distinct and within the manifest directory
    so a restored Library is portable. Source files may be anywhere.
    """
    library._assert_current()
    state = state_path(library)
    assert library.manifest is not None
    root = library.manifest.parent
    if library.issues:
        raise ValueError("Incomplete Library: resolve member diagnostics before ingestion")
    if (state / "journal.json").exists():
        raise ValueError("Interrupted ingestion: run library recover first")
    ledger = read_ledger(library)
    guards: dict[Path, str | None] = {member.path: member.sha256 for member in library._loaded}
    guards[library.manifest] = digest(library.manifest)
    ledger_path = state / "ledger.json"
    guards[ledger_path] = digest(ledger_path)
    collections = {p: Bibliography.open(p) for p in library.members}
    roots: set[Path] = set()
    for coll in collections.values():
        assert coll.path is not None
        contained(root, coll.path)
        # Provision metadata only in memory; empty previews create no directories.
        coll.ensure_files_dir()
        store = coll.files
        assert store is not None
        contained(root, store.root)
        if store.root in roots:
            raise ValueError("Managed ingestion requires distinct member-owned Pinax stores")
        roots.add(store.root)
    staged_library = copy(library)
    staged_library._loaded = tuple(replace(m, bib=collections[m.path].lib) for m in library._loaded)
    removals: list[dict] = []
    results = []
    pinned: dict[str, str] = {}
    row_occurrence: dict[int, str] = {}
    touched: set[Path] = set()
    decisions = decisions or {}
    if not isinstance(decisions, dict) or any(
        not isinstance(k, str) or not isinstance(v, dict) for k, v in decisions.items()
    ):
        raise ValueError("Decisions must map absolute source paths to objects")
    for path in inputs(paths):
        row: dict = {"path": str(path), "status": "pending"}
        try:
            if path.is_symlink():
                raise ValueError("Select a regular source file, not a symbolic link")
            source_hash = digest(path)
            row["sha256"] = source_hash
            guards[path] = source_hash
            decision = decisions.get(str(path), {})
            if decision and (not source_hash or decision.get("sha256") != source_hash):
                raise ValueError("Reviewed decision has a stale source hash")
            if decision.keys() - DECISION_KEYS:
                raise ValueError("Unknown ingestion decision fields")
            row["decision"] = decision
            prior = [
                r
                for r in ledger["sources"].values()
                if r["path"] == str(path)
                and r["status"] in {"committed", "already_present"}
                and (source_hash is None or r.get("sha256") == source_hash)
            ]
            receipt = prior[-1] if prior else None
            if receipt:
                contained(root, root / receipt["material"])
                contained(root, root / receipt["bibliography"])
            if not decision and receipt and digest(root / receipt["material"]) == receipt["sha256"]:
                owner = collections.get(root / receipt["bibliography"])
                from pynakes.files import parse_file_field

                material = (root / receipt["material"]).resolve()
                owners = (
                    [
                        e
                        for e in owner.lib.entries.values()
                        if any(
                            (owner.path.parent / link.path).resolve() == material
                            for link in parse_file_field(e)
                        )
                    ]
                    if owner and owner.path
                    else []
                )
                store = owner.files if owner else None
                attributable = bool(
                    store
                    and len(owners) == 1
                    and any(
                        v["intact"]
                        and Path(v["absolute_path"]) == material
                        and v["sha256"] == receipt["sha256"]
                        for v in store.material_variants(owners[0].key)
                    )
                )
                if attributable:
                    assert store is not None
                    guards[store.manifest_path] = digest(store.manifest_path)
                    guards[material] = receipt["sha256"]
                    row.update(receipt, status="already_present", key=owners[0].key)
                else:
                    row["reason"] = "receipt_owner_link_or_manifest_missing"
            elif decision.get("exclude"):
                row.update(status="excluded", reason=str(decision["exclude"]))
            elif not path.exists():
                row["reason"] = "missing_source_or_material"
            elif path.suffix.lower() != ".pdf":
                row["reason"] = "unsupported_format"
            else:
                inspection = inspect_pdf(path)
                row.update(inspection.to_dict())
                entry = select_entry(
                    next(iter(collections.values())), inspection, online, decision, cache_file, row
                )
                if entry is not None:
                    all_keys = {k for c in collections.values() for k in c.lib.entries.keys()}
                    rename_entry_key(entry, unique_key("PendingIngestion", all_keys))
                    routing = staged_library.route(
                        entry, destination=decision.get("destination", destination)
                    )
                    row["routing"] = routing.to_dict()
                    if routing.status not in {"routed", "existing"}:
                        row["reason"] = routing.reason
                    else:
                        assert routing.destination is not None
                        coll = collections[routing.destination]
                        assert coll.path is not None
                        selected_mode, selected_role = adoption_policy(
                            coll, decision.get("mode", mode), decision.get("role", role)
                        )
                        key = (
                            routing.candidates[0]["key"]
                            if routing.status == "existing"
                            else unique_key(generate_key(entry, coll.lib), all_keys)
                        )
                        if selected_mode == "move":
                            for other in collections.values():
                                if other is not coll:
                                    check_source_owners(other, path, None)
                        _stage(
                            coll,
                            inspection,
                            entry,
                            key,
                            "generated",
                            row,
                            mode=selected_mode,
                            role=selected_role,
                        )
                        if row.get("status") not in {"imported", "linked"}:
                            row["status"] = "pending"
                        else:
                            adoption = coll._material_adoptions[-1][0]
                            target_path = adoption.target
                            target = coll.lib.entries[key]
                            touched.add(routing.destination)
                            row.update(
                                status="committed",
                                key=key,
                                bibliography=contained(root, routing.destination),
                                material=contained(root, target_path),
                                mode=selected_mode,
                                role=selected_role,
                                title=target.fields.get("title"),
                            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            row.update(status="pending", reason=str(exc))
        row.setdefault(
            "next_action",
            "Review evidence and supply a hash-bound decision"
            if row["status"] == "pending"
            else "none",
        )
        results.append(row)
        occurrence = hashlib.sha256(
            (str(path) + "\0" + str(row.get("sha256"))).encode()
        ).hexdigest()
        previous = ledger["sources"].get(occurrence)
        if previous and {
            k: v for k, v in previous.items() if k not in {"history", "plan_sha256"}
        } != {k: v for k, v in row.items() if k not in {"history", "plan_sha256"}}:
            row["history"] = [
                *previous.get("history", []),
                {k: v for k, v in previous.items() if k not in {"history", "plan_sha256"}},
            ]
        elif previous:
            # Unchanged: the receipt keeps naming the plan that produced it, so
            # a repeated run leaves the ledger byte-identical.
            if previous.get("history"):
                row["history"] = previous["history"]
            if isinstance(previous.get("plan_sha256"), str):
                pinned[occurrence] = previous["plan_sha256"]
        ledger["sources"][occurrence] = row
        row_occurrence[id(row)] = occurrence
    outputs: list[Output] = []
    for path in sorted(touched):
        coll = collections[path]
        assert coll.files is not None
        material_outputs, material_guards, source_removals = adoption_outputs(
            coll.files, coll._material_adoptions, root
        )
        outputs.extend(material_outputs)
        guards.update(material_guards)
        removals.extend(source_removals)
    diffs = {}
    for path in sorted(touched):
        coll = collections[path]
        diffs[contained(root, path)] = coll.diff()
        outputs.append(Output(path, guards[path], encode_text(coll.preview(), coll.lib.encoding)))
    for row in results:
        if row["status"] in {"committed", "already_present"}:
            bib_path = root / row["bibliography"]
            data = next((o.data for o in outputs if o.path == bib_path), None)
            row["bibliography_sha256"] = (
                hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else digest(bib_path)
            )
            row["material_sha256"] = row["sha256"]
    outputs.append(Output(ledger_path, guards[ledger_path], json_bytes(ledger)))
    report = {
        "results": results,
        "diffs": diffs,
        "source_occurrences": len(results),
        "distinct_source_bytes": len({r.get("sha256") for r in results if r.get("sha256")}),
        "accepted_records": len(
            {
                (r.get("bibliography"), r.get("key"))
                for r in results
                if r["status"] in {"committed", "already_present"}
            }
        ),
        "modified_entries": sum(collections[p].changed_entries_count() for p in touched),
        "pending": sum(r["status"] == "pending" for r in results),
        "complete": all(r["status"] != "pending" for r in results),
    }
    plan = IngestionPlan(library, report, outputs, guards, removals)
    fingerprint = plan.sha256
    for row in results:
        row["plan_sha256"] = pinned.get(row_occurrence.get(id(row), ""), fingerprint)
    outputs[-1] = Output(ledger_path, guards[ledger_path], json_bytes(ledger))
    return plan
