"""Entry ordering for ``normalize``: sort criteria, stable sorting, crossref order.

Public through :mod:`pynakes.normalize`, which re-exports :func:`sort_entries`.
"""

from pynakes.metadata.jabref import SAVE_ORDER_KEY_FIELDS, library_sort_order
from pynakes.model import BibEntry, BibFile


def _resolve_sort_criteria(lib: BibFile, sort_by: list[str] | None) -> list[tuple[str, bool]]:
    """Resolve the entry sort order.

    An explicit CLI ``sort_by`` wins: each token is ``field`` or
    ``field:asc``/``field:desc`` (the JabRef field name; ``key`` is accepted for
    the citation key). A lone ``original`` or ``none`` token means "keep current
    order". With no CLI override, :func:`~pynakes.metadata.jabref.library_sort_order`
    drives the order: pynakes' native ``sort-order`` key first, else JabRef's
    ``saveOrderConfig`` (only when its type is ``specified``, matching JabRef,
    which leaves entries untouched for ``original``/``table``).
    """
    if sort_by:
        tokens = [token.strip() for token in sort_by if token.strip()]
        if not tokens or (len(tokens) == 1 and tokens[0].lower() in {"original", "none"}):
            return []
        criteria: list[tuple[str, bool]] = []
        for token in tokens:
            name, _, direction = token.partition(":")
            descending = direction.strip().lower() in {"desc", "descending", "true", "down"}
            criteria.append((name.strip(), descending))
        return criteria

    return list(library_sort_order(lib) or [])


def sort_entries(lib: BibFile, criteria: list[tuple[str, bool]]) -> int:
    """Reorder ``lib`` entries in-place by the given criteria.

    ``criteria`` is an ordered ``(field, descending)`` list; the first is the
    primary sort. Implemented as successive stable sorts from the least- to the
    most-significant criterion, so per-criterion ascending/descending is honored
    independently. After sorting, crossref parents are placed after all of their
    children (a BibTeX 0.99 processing requirement). Entries sharing a citation
    key keep their relative order: BibTeX uses the first, so reordering them
    would change which record a citation reaches. Returns the number of entries.
    """
    before = list(lib.entries.values())
    for field_name, descending in reversed(criteria):
        lib.entries.reorder(
            lambda entry, f=field_name: _entry_sort_key(entry, f),
            reverse=descending,
        )
    lib.entries.set_order(_keep_duplicate_order(before, list(lib.entries.values())))
    _sink_crossref_parents(lib)
    return len(lib.entries)


def _keep_duplicate_order(before: list[BibEntry], after: list[BibEntry]) -> list[BibEntry]:
    """Return ``after`` with each duplicated key's entries back in ``before`` order.

    The duplicates keep the positions the sort gave them; only which of them
    sits in each position is restored, so the one BibTeX reads stays first.
    """
    by_key: dict[str, list[BibEntry]] = {}
    for entry in before:
        by_key.setdefault(entry.key, []).append(entry)
    queues = {key: iter(group) for key, group in by_key.items() if len(group) > 1}
    if not queues:
        return after
    return [next(queues[entry.key]) if entry.key in queues else entry for entry in after]


def _sink_crossref_parents(lib: BibFile) -> None:
    """Place entries that are crossref parents after all of their children.

    BibTeX 0.99 requires a cross-referenced entry to occur later in the database
    than every entry that cross-references it. Duplicate parent keys resolve to
    their first occurrence, matching the rest of pynakes' duplicate-key behavior.
    """
    original = list(lib.entries.values())
    first_by_key: dict[str, BibEntry] = {}
    for entry in original:
        first_by_key.setdefault(entry.key, entry)

    children_by_parent: dict[int, list[BibEntry]] = {}
    parent_by_child: dict[int, BibEntry] = {}
    for entry in original:
        parent_key = entry.fields.get("crossref", "").strip()
        parent = first_by_key.get(parent_key)
        if parent is not None and parent is not entry:
            children_by_parent.setdefault(id(parent), []).append(entry)
            parent_by_child[id(entry)] = parent

    # Crossref cycles are malformed, but normalization must still be idempotent.
    # Collapse each cycle into one stable component whose members retain their
    # incoming order; ordinary children of cycle members are still emitted first.
    cycle_components: list[list[BibEntry]] = []
    cycle_by_entry: dict[int, int] = {}
    processed: set[int] = set()
    for start in original:
        path: list[BibEntry] = []
        positions: dict[int, int] = {}
        current = start
        while id(current) not in processed and id(current) not in positions:
            positions[id(current)] = len(path)
            path.append(current)
            parent = parent_by_child.get(id(current))
            if parent is None:
                break
            current = parent
        if id(current) in positions:
            members = path[positions[id(current)] :]
            member_ids = {id(member) for member in members}
            members = [entry for entry in original if id(entry) in member_ids]
            component_index = len(cycle_components)
            cycle_components.append(members)
            for member in members:
                cycle_by_entry[id(member)] = component_index
        processed.update(id(entry) for entry in path)

    ordered: list[BibEntry] = []
    emitted: set[int] = set()
    visiting: set[int] = set()
    emitted_cycles: set[int] = set()
    visiting_cycles: set[int] = set()

    def emit(entry: BibEntry) -> None:
        identity = id(entry)
        if identity in emitted:
            return
        cycle_index = cycle_by_entry.get(identity)
        if cycle_index is not None:
            if cycle_index in emitted_cycles or cycle_index in visiting_cycles:
                return
            visiting_cycles.add(cycle_index)
            members = cycle_components[cycle_index]
            member_ids = {id(member) for member in members}
            for member in members:
                for child in children_by_parent.get(id(member), []):
                    if id(child) not in member_ids:
                        emit(child)
            visiting_cycles.remove(cycle_index)
            for member in members:
                if id(member) not in emitted:
                    ordered.append(member)
                    emitted.add(id(member))
            emitted_cycles.add(cycle_index)
            return
        if identity in visiting:  # malformed crossref cycle: retain stable order
            return
        visiting.add(identity)
        for child in children_by_parent.get(identity, []):
            emit(child)
        visiting.remove(identity)
        if identity not in emitted:
            ordered.append(entry)
            emitted.add(identity)

    for entry in original:
        emit(entry)
    lib.entries.set_order(ordered)


def _entry_sort_key(entry: BibEntry, field_name: str) -> tuple:
    """Compute a stable sort key for *entry* on *field_name* (JabRef field name).

    JabRef's ``citationkey`` (and the ``bibtexkey``/``key`` aliases) sorts by the
    citation key; ``entrytype``/``type`` by the entry type; any other name is a
    bibliographic field. Entries missing the field sort last (ascending). ``year``
    is compared numerically so ``2010`` precedes ``2020``.
    """
    name = field_name.lower()
    if name in SAVE_ORDER_KEY_FIELDS:
        return (0, entry.key.lower(), "")
    if name in {"entrytype", "type"}:
        return (0, entry.type.lower(), "")
    raw = entry.fields.get(name, "")
    if not raw:
        return (1, "", "")  # missing → last
    if name == "year":
        try:
            return (0, int(raw), "")
        except ValueError:
            return (0, 0, raw.lower())
    return (0, raw.lower(), "")
