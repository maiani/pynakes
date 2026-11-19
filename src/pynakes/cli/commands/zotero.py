"""Explicit local Zotero reads and guarded selection into project files."""

import typer

from pynakes.cli._common import (
    _BACKUP_OPTION,
    _EXPECT_SHA256_OPTION,
    RunParams,
    _emit,
    _resolve_input_bib,
    _safe,
    bib_file_argument,
)
from pynakes.cli.commands._zotero_selection import run_selection
from pynakes.library.backends.zotero import ZoteroLibraryBackend


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
    collection: str | None = typer.Option(
        None, help="Direct members of this Zotero collection key"
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Read one bounded source page; optional --where filters its citation projection.

    This is not global ranking. Empty filtered pages can have a next cursor.
    Notes, annotations and standalone PDFs are counted as skipped, not papers.
    """
    with ZoteroLibraryBackend(port=port) as backend:
        page = backend.scan(limit=limit, cursor=cursor, where=where, collection=collection)
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


def search(
    text: str | None = typer.Argument(None, help="Native Zotero title/creator/year search"),
    where: str | None = typer.Option(None, help="Local predicate over citation projections"),
    collection: str | None = typer.Option(None, help="Restrict to direct collection members"),
    max_items: int = typer.Option(1000, min=1, help="Maximum candidate items to scan this call"),
    cursor: str | None = typer.Option(None),
    port: int = typer.Option(23119),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Search across pages within a budget; report exhaustion and a continuation cursor.

    Supply TEXT, --where, or both. TEXT uses Zotero quick search; --where always
    uses the pynakes query grammar. A budget-limited empty result is incomplete.
    """
    with ZoteroLibraryBackend(port=port) as backend:
        result = backend.search(
            text, where=where, collection=collection, max_items=max_items, cursor=cursor
        )
        _emit(
            json_output,
            {"status": "success", "action": "zotero_search", "warnings": [], **result.to_dict()},
            [f"{r.ref.key}: {dict(r.fields).get('title', '')}" for r in result.items]
            + [f"Scanned {result.scanned}; complete: {result.complete}"]
            + ([f"Next cursor: {result.next_cursor}"] if result.next_cursor else []),
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
            [f"{r.ref.key}: {r.name}" for r in page.items]
            + ([f"Next cursor: {page.next_cursor}"] if page.next_cursor else []),
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
            [f"{r.ref.key}: {r.title} ({r.media_type})" for r in page.items]
            + ([f"Next cursor: {page.next_cursor}"] if page.next_cursor else []),
        )


def select(
    file: str | None = bib_file_argument(help="Existing project bibliography"),
    item: list[str] | None = typer.Option(None, help="Source Zotero item key; repeatable"),
    collection: str | None = typer.Option(None, help="Select direct members of a collection"),
    max_items: int = typer.Option(1000, min=1, help="Maximum source items to scan/select"),
    key: str | None = typer.Option(None, help="Independent project citation key"),
    port: int = typer.Option(23119),
    expect_revision: str | None = typer.Option(
        None, help="Source revision digest from a reviewed preview"
    ),
    resolve: list[str] | None = typer.Option(
        None,
        "--resolve",
        help="Reviewed ITEM:FIELD=source|project (FIELD for one item); repeatable; @type selects entry type. Requires both preconditions",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Select or refresh items in one guarded plan and one project write.

    Collection selection includes direct members and reports omitted children.
    Batch decisions use --resolve ITEM:FIELD=source|project with both preconditions.
    """
    file = _resolve_input_bib(file, json_output)
    run_selection(
        file,
        backend_factory=ZoteroLibraryBackend,
        items=item or [],
        collection=collection,
        refresh=False,
        key=key,
        port=port,
        expect_revision=expect_revision,
        resolve=resolve or [],
        max_items=max_items,
        params=RunParams(
            dry_run=dry_run,
            diff=diff,
            backup=backup,
            expect_sha256=expect_sha256,
            json_output=json_output,
        ),
    )


def refresh(
    file: str | None = bib_file_argument(help="Existing project bibliography"),
    port: int = typer.Option(23119),
    expect_revision: str | None = typer.Option(None),
    resolve: list[str] | None = typer.Option(
        None, help="ITEM:FIELD=source|project; requires both preconditions"
    ),
    max_items: int = typer.Option(1000, min=1, help="Maximum bindings to refresh"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    diff: bool = typer.Option(False, "--diff"),
    backup: bool = _BACKUP_OPTION,
    expect_sha256: str | None = _EXPECT_SHA256_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Refresh all bindings to this Zotero instance in one guarded project write.

    Other-source bindings are reported and retained. Unresolved findings refuse
    the entire batch. Reviewed decisions use --resolve ITEM:FIELD=source|project.
    """
    file = _resolve_input_bib(file, json_output)
    run_selection(
        file,
        backend_factory=ZoteroLibraryBackend,
        items=[],
        collection=None,
        refresh=True,
        key=None,
        port=port,
        expect_revision=expect_revision,
        resolve=resolve or [],
        max_items=max_items,
        params=RunParams(
            dry_run=dry_run,
            diff=diff,
            backup=backup,
            expect_sha256=expect_sha256,
            json_output=json_output,
        ),
    )


def register(app: typer.Typer) -> None:
    app.command("status")(_safe(status))
    app.command("scan")(_safe(scan))
    app.command("search")(_safe(search))
    app.command("show")(_safe(show))
    app.command("collections")(_safe(collections))
    app.command("materials")(_safe(materials))
    app.command("select")(_safe(select))
    app.command("refresh")(_safe(refresh))
