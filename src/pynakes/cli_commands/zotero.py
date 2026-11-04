"""Explicit local Zotero reads and guarded selection into project files."""

from dataclasses import asdict

import typer

from pynakes.cli_common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _check_expected_sha256,
    _emit,
    _finish_mod,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.engine import Bibliography
from pynakes.library_backend import SourceChanged, search_page
from pynakes.project_selection import prepare_selection
from pynakes.zotero import ZoteroLibraryBackend


def status(
    port: int = typer.Option(23119, help="Local Zotero port"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Describe the explicitly selected local Zotero source (no authorization)."""
    with ZoteroLibraryBackend(port=port) as backend:
        result = backend.describe()
        _emit(
            json_output,
            {"status": "success", "warnings": [], "action": "zotero_status", **result},
            [f"Zotero {result['application_version']}: {result['source']}"],
        )


def scan(
    port: int = typer.Option(23119),
    limit: int = typer.Option(50, min=1, max=100),
    cursor: str | None = typer.Option(None),
    where: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read one bounded source page; optional --where filters its citation projection.

    This is not global ranking. Empty filtered pages can have a next cursor.
    Notes, annotations and standalone PDFs are counted as skipped, not papers.
    """
    with ZoteroLibraryBackend(port=port) as backend:
        page = (
            search_page(backend, where, limit=limit, cursor=cursor)
            if where
            else backend.scan(limit=limit, cursor=cursor)
        )
        _emit(
            json_output,
            {"status": "success", "warnings": [], "action": "zotero_scan", **page.to_dict()},
            [f"{r.ref.key}: {dict(r.fields).get('title', '')}" for r in page.items]
            + ([f"Next cursor: {page.next_cursor}"] if page.next_cursor else []),
        )


def show(
    item: str = typer.Argument(..., help="Zotero item key"),
    port: int = typer.Option(23119),
    native: bool = typer.Option(
        False, "--native", help="Include native metadata, including private fields"
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read a reference; private native fields are an explicit expansion."""
    with ZoteroLibraryBackend(port=port) as backend:
        record = backend.get(backend.item_ref(item), native=native)
        _emit(
            json_output,
            {
                "status": "success",
                "warnings": [],
                "action": "zotero_show",
                "reference": record.to_dict(),
            },
            [f"{name}: {value}" for name, value in record.fields] + list(record.issues),
        )


def collections(
    port: int = typer.Option(23119),
    limit: int = typer.Option(50, min=1, max=100),
    cursor: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read a bounded page of collection names and parent relationships."""
    with ZoteroLibraryBackend(port=port) as backend:
        page = backend.collections(limit=limit, cursor=cursor)
        _emit(
            json_output,
            {"status": "success", "warnings": [], "action": "zotero_collections", **page.to_dict()},
            [f"{r.ref.key}: {r.name}" for r in page.items],
        )


def materials(
    item: str = typer.Argument(...),
    port: int = typer.Option(23119),
    limit: int = typer.Option(50, min=1, max=100),
    cursor: str | None = typer.Option(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List attachment metadata without resolving paths or fetching bytes."""
    with ZoteroLibraryBackend(port=port) as backend:
        page = backend.materials(backend.item_ref(item), limit=limit, cursor=cursor)
        _emit(
            json_output,
            {"status": "success", "warnings": [], "action": "zotero_materials", **page.to_dict()},
            [f"{r.ref.key}: {r.title} ({r.media_type})" for r in page.items],
        )


def select(
    file: str | None = bib_file_argument(help="Existing project bibliography"),
    item: str = typer.Option(..., help="Source Zotero item key"),
    key: str | None = typer.Option(None, help="Independent project citation key"),
    port: int = typer.Option(23119),
    expect_revision: str | None = typer.Option(
        None, help="Source revision digest from a reviewed preview"
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Stage or refresh one reference in a project; never write to Zotero.

    Persists source and target baselines in an attached comment. Same-field
    conflicts require review. Does not copy PDFs, private notes or annotations.
    """
    file = _resolve_input_bib(file, json_output)
    coll = Bibliography.open(file)
    params = RunParams(
        dry_run=dry_run,
        diff=diff,
        backup=backup,
        expect_sha256=expect_sha256,
        json_output=json_output,
    )
    _check_expected_sha256(file, coll, params)
    with ZoteroLibraryBackend(port=port) as backend:
        plan = prepare_selection(backend, backend.item_ref(item), coll, key=key)
        revision = plan.reference.revision
        if expect_revision is not None and expect_revision != revision.digest:
            raise SourceChanged("Zotero differs from the reviewed source revision")
        _finish_mod(
            file,
            "zotero_select",
            coll,
            params,
            [f"Project reference: {plan.key}"],
            warnings=list(plan.issues),
            source_ref=plan.reference.ref.to_dict(),
            source_revision=asdict(revision),
            source_revision_digest=revision.digest,
            key=plan.key,
        )


def register(app: typer.Typer) -> None:
    app.command("status")(_safe(status))
    app.command("scan")(_safe(scan))
    app.command("show")(_safe(show))
    app.command("collections")(_safe(collections))
    app.command("materials")(_safe(materials))
    app.command("select")(_safe(select))
