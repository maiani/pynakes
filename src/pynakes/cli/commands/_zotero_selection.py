"""One guarded project plan for explicit Zotero items, a collection or all bindings."""

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pynakes.cli._common import (
    RunParams,
    _check_expected_sha256,
    _emit_conflict,
    _finish_mod,
    _source_sha256,
)
from pynakes.engine import Bibliography
from pynakes.library.backends.base import ItemRef, Revision, SourceChanged
from pynakes.library.backends.zotero import ZoteroLibraryBackend
from pynakes.project_selection import (
    SelectionBatchConflict,
    prepare_selections,
    project_bindings,
)


def _collection_refs(
    backend: ZoteroLibraryBackend, collection: str, revision: Revision, max_items: int
) -> tuple[list[ItemRef], list[str]]:
    refs = []
    cursor = None
    scanned = 0
    while True:
        page = backend.scan(collection=collection, limit=min(100, max_items), cursor=cursor)
        if page.revision != revision:
            raise SourceChanged("Zotero changed while reading the collection")
        scanned += page.scanned
        if page.source_total > max_items or scanned > max_items:
            raise ValueError("Collection exceeds --max-items; increase the explicit scan budget")
        if not page.complete:
            raise ValueError("Collection read is incomplete; refusing a partial selection")
        refs.extend(r.ref for r in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    # Selecting direct members must make omitted child collections visible.
    cursor = None
    children = []
    for _ in range(100):
        page = backend.collections(limit=100, cursor=cursor)
        if page.revision != revision:
            raise SourceChanged("Zotero changed while reading collection hierarchy")
        children.extend(c.name for c in page.items if c.parent == collection)
        cursor = page.next_cursor
        if cursor is None:
            break
    else:
        raise ValueError("Collection hierarchy exceeds the 10000-collection read budget")
    warnings = (
        ["Direct members only; omitted subcollections: " + ", ".join(children)] if children else []
    )
    return refs, warnings


def _decisions(
    values: list[str], refs: list[ItemRef], *, scoped: bool
) -> dict[ItemRef, dict[str, Literal["source", "project"]]]:
    selected = {r.key: r for r in refs}
    result: dict[ItemRef, dict[str, Literal["source", "project"]]] = {}
    for value in values:
        label, sep, choice = value.partition("=")
        if not sep or choice not in ("source", "project"):
            raise ValueError("Use --resolve ITEM:FIELD=source|project (FIELD for one item)")
        if ":" in label:
            item, field = label.split(":", 1)
        elif not scoped and len(refs) == 1:
            item, field = refs[0].key, label
        else:
            raise ValueError("Batch decisions require --resolve ITEM:FIELD=source|project")
        if item not in selected or not field:
            raise ValueError("Conflict decision must name a selected item and field")
        decisions = result.setdefault(selected[item], {})
        if field in decisions:
            raise ValueError("Repeated conflict decision for " + label)
        decisions[field] = "source" if choice == "source" else "project"
    return result


def run_selection(
    file: str,
    *,
    backend_factory: Callable[..., ZoteroLibraryBackend],
    items: list[str],
    collection: str | None,
    refresh: bool,
    key: str | None,
    port: int,
    expect_revision: str | None,
    resolve: list[str],
    max_items: int,
    params: RunParams,
) -> None:
    if resolve and (expect_revision is None or params.expect_sha256 is None):
        raise ValueError("--resolve requires --expect-revision and --expect-sha256 from review")
    if key is not None and (refresh or collection is not None or len(items) != 1):
        raise ValueError("--key requires exactly one --item and no collection")
    if not refresh and not items and collection is None:
        raise ValueError("Select at least one --item or a --collection")
    if not Path(file).exists():
        raise FileNotFoundError(
            f"Project bibliography does not exist: {file}. Create it with pynakes init first"
        )
    coll = Bibliography.open(file)
    _check_expected_sha256(file, coll, params)
    with backend_factory(port=port) as backend:
        description = backend.describe()
        revision = Revision(**description["revision"])
        if expect_revision is not None and expect_revision != revision.digest:
            raise SourceChanged("Zotero differs from the reviewed source revision")
        refs = [backend.item_ref(item) for item in items]
        warnings = []
        foreign = []
        if refresh:
            for ref in project_bindings(coll):
                if ref.source == description["source"]:
                    refs.append(ref)
                else:
                    foreign.append(ref.to_dict())
            if foreign:
                warnings.append(f"Skipped {len(foreign)} bindings belonging to other sources")
        if collection is not None:
            members, warnings = _collection_refs(backend, collection, revision, max_items)
            refs.extend(members)
        refs = list(dict.fromkeys(refs))
        if len(refs) > max_items:
            raise ValueError("Selection exceeds --max-items")
        decisions = _decisions(
            resolve, refs, scoped=refresh or collection is not None or len(refs) != 1
        )
        try:
            plan = prepare_selections(
                backend,
                refs,
                coll,
                keys={refs[0]: key} if key is not None else None,
                resolutions=decisions,
                expected_revision=revision,
            )
        except SelectionBatchConflict as exc:
            extra = {}
            if len(refs) == 1:
                extra = {
                    "source_ref": refs[0].to_dict(),
                    "conflicts": [asdict(c) for f in exc.findings for c in f.conflicts],
                }
            _emit_conflict(
                params.json_output,
                "SourceChanged",
                str(exc),
                file=file,
                key=key,
                source_sha256=_source_sha256(coll),
                source_revision=asdict(revision),
                source_revision_digest=revision.digest,
                findings=[asdict(f) for f in exc.findings],
                options=[
                    {
                        "id": choice,
                        "description": f"Review fields; --resolve ITEM:FIELD={choice} with both preconditions",
                    }
                    for choice in ("source", "project")
                ],
                **extra,
            )
        payload: dict = {
            "source_revision": asdict(revision),
            "source_revision_digest": revision.digest,
            "selections": [
                {
                    "source_ref": p.reference.ref.to_dict(),
                    "key": p.key,
                    "changes": list(p.changes),
                    "issues": list(p.issues),
                }
                for p in plan.selections
            ],
            "foreign_bindings": foreign,
            "resolutions": {ref.key: values for ref, values in decisions.items()},
        }
        if len(plan.selections) == 1 and not refresh and collection is None:
            selected = plan.selections[0]
            payload.update(
                source_ref=selected.reference.ref.to_dict(),
                key=selected.key,
                changes=list(selected.changes),
                resolutions=decisions.get(selected.reference.ref, {}),
            )
        _finish_mod(
            file,
            "zotero_refresh" if refresh else "zotero_select",
            coll,
            params,
            [f"Project references: {len(plan.selections)}"],
            warnings=warnings + [issue for p in plan.selections for issue in p.issues],
            **payload,
        )
