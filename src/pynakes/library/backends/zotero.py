"""Read-only Zotero 10 local Library backend.

Connection is explicit local IPC. There is no cloud fallback, authorization
prompt, source mutation or database access. Every response is bounded and every
scan is guarded by the local source identity and observed library revision.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import url2pathname

import httpx

from pynakes.bounded import request_digest
from pynakes.library.backends._zotero_projection import project
from pynakes.library.backends.base import (
    ItemRef,
    ReadPage,
    ReferenceView,
    Revision,
    SearchResult,
    SourceChanged,
    SourceMissing,
    SourceUnavailable,
    SourceUnsupported,
    _next_cursor,
    _page_start,
    _search_page,
)
from pynakes.model import BibEntry


@dataclass(frozen=True)
class CollectionRef:
    ref: ItemRef
    name: str
    parent: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MaterialRef:
    """Attachment metadata; no implication that its bytes are available."""

    ref: ItemRef
    owner: ItemRef
    title: str
    media_type: str
    link_mode: str

    def to_dict(self) -> dict:
        return asdict(self)


class ZoteroLibraryBackend:
    """Bounded, explicitly connected personal-library reads from local Zotero.

    Call ``close`` or use a context manager. Constructor creation performs no I/O.
    Port and read budgets are run mechanics; the host is always 127.0.0.1.
    The backend supports API 3, Zotero major version 10. It rejects untested
    major versions and missing revision headers rather than weakening guards.
    """

    def __init__(
        self,
        *,
        port: int = 23119,
        timeout: float = 10,
        max_response_bytes: int = 4 * 1024 * 1024,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid loopback port")
        if (
            not math.isfinite(timeout)
            or timeout <= 0
            or type(max_response_bytes) is not int
            or max_response_bytes < 1024
        ):
            raise ValueError("Invalid read budget")
        self._client = httpx.Client(
            base_url=f"http://127.0.0.1:{port}/api/",
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._max_bytes = max_response_bytes
        self._server: str | None = None
        self._schema: str | None = None
        self._version: str | None = None

    def __enter__(self) -> ZoteroLibraryBackend:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request(self, path: str, *, redirect: bool = False) -> tuple[httpx.Headers, object]:
        headers = {"Zotero-API-Version": "3", "User-Agent": "pynakes-local-library"}
        if self._server:
            headers["Zotero-Server-ID"] = self._server
        try:
            with self._client.stream("GET", path, headers=headers) as response:
                if response.status_code == 412:
                    raise SourceChanged("Zotero source instance changed")
                if response.status_code == 404:
                    raise SourceMissing("Zotero record or attachment is missing")
                if response.status_code == 403:
                    raise SourceUnavailable("Enable the local API in Zotero Settings > Advanced")
                if response.status_code != 200 and not (redirect and response.status_code == 302):
                    raise SourceUnavailable(f"Zotero returned HTTP {response.status_code}")
                h = response.headers
                server, schema = h.get("Zotero-Server-ID"), h.get("Zotero-Schema-Version")
                version = h.get("X-Zotero-Version", "")
                if (
                    not server
                    or not schema
                    or h.get("Zotero-API-Version") != "3"
                    or version.split(".")[0] != "10"
                ):
                    raise SourceUnsupported(
                        "Requires Zotero 10 local API 3 with identity/schema headers"
                    )
                if self._server and (
                    server != self._server or schema != self._schema or version != self._version
                ):
                    raise SourceChanged("Zotero instance or schema changed; reconnect explicitly")
                self._server, self._schema, self._version = server, schema, version
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > self._max_bytes:
                        raise SourceUnavailable("Zotero response exceeded the byte budget")
                if redirect:
                    return h, None
                if not path:
                    return h, None
                try:
                    return h, json.loads(raw)
                except (ValueError, UnicodeError) as exc:
                    raise SourceUnavailable("Malformed Zotero JSON response") from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailable(
                "Cannot reach the explicitly selected local Zotero API"
            ) from exc

    @property
    def source(self) -> str:
        if self._server is None:
            self._request("")
        return f"zotero-local:{self._server}:users/0"

    def _revision(self) -> Revision:
        h, _ = self._request("users/0/items?limit=1&format=versions")
        value = h.get("Last-Modified-Version", "")
        if not value.isdecimal():
            raise SourceUnavailable("Missing or invalid library revision")
        return Revision(self.source, f"api3/schema{self._schema}/projection1/{value}")

    def describe(self) -> dict:
        revision = self._revision()
        return {
            "backend": "zotero-local",
            "source": self.source,
            "revision": asdict(revision),
            "application_version": self._version,
            "schema": self._schema,
            "capabilities": {
                "reads": "supported",
                "collections": "supported",
                "materials": "supported",
                "source_writes": "unsupported",
            },
            "transport": "explicit-loopback",
            "authorization_required": False,
        }

    def item_ref(self, key: str) -> ItemRef:
        self._key(key)
        return ItemRef(self.source, key)

    @staticmethod
    def _key(key: str) -> str:
        if not re.fullmatch(r"[A-Z0-9]{8}", key):
            raise ValueError("Expected an eight-character Zotero key")
        return key

    def _check_ref(self, ref: ItemRef) -> str:
        if ref.source != self.source:
            raise SourceChanged("Item belongs to another source")
        return self._key(ref.key)

    def _check_revision(self, before: Revision) -> None:
        if self._revision() != before:
            raise SourceChanged("Zotero changed while reading; restart the operation")

    def _page(
        self,
        path: str,
        limit: int,
        cursor: str | None,
        *,
        params: dict | None = None,
        search_scope: dict | None = None,
    ) -> tuple[list[dict], Revision, str | None, int]:
        revision = self._revision()
        request = request_digest(
            source=self.source,
            path=path,
            limit=limit if search_scope is None else None,
            params=params,
            search_scope=search_scope,
            mapping=1,
        )
        start = _page_start(limit, cursor, revision, request)
        query = urlencode(
            {
                "limit": limit,
                "start": start,
                "sort": "dateAdded",
                "direction": "asc",
                **(params or {}),
            }
        )
        h, raw = self._request(f"{path}?{query}")
        if (
            not isinstance(raw, list)
            or len(raw) > limit
            or not all(isinstance(x, dict) and isinstance(x.get("data"), dict) for x in raw)
        ):
            raise SourceUnavailable("Malformed or oversized Zotero item page")
        keys = [x.get("key") for x in raw]
        if any(not isinstance(k, str) or not re.fullmatch(r"[A-Z0-9]{8}", k) for k in keys):
            raise SourceUnavailable("Malformed Zotero record key")
        if any(x["data"].get("key", x["key"]) != x["key"] for x in raw):
            raise SourceUnavailable("Inconsistent Zotero record identity")
        if len(set(keys)) != len(keys):
            raise SourceUnavailable("Duplicate Zotero record in page")
        total_text = h.get("Total-Results", "")
        if not total_text.isdecimal():
            raise SourceUnavailable("Missing or invalid result total")
        total = int(total_text)
        if start > total or (not raw and start < total) or start + len(raw) > total:
            raise SourceUnavailable("Inconsistent Zotero pagination")
        self._check_revision(revision)
        return raw, revision, _next_cursor(start, len(raw), total, revision, request), total

    def scan(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        collection: str | None = None,
        where: str | None = None,
    ) -> ReadPage[ReferenceView]:
        """Read library items or direct collection members, optionally filtered.

        Collection membership is not recursive. Filters apply to each bounded
        citation page; follow the cursor even when a filtered page is empty.
        """
        path = (
            f"users/0/collections/{self._key(collection)}/items"
            if collection is not None
            else "users/0/items"
        )
        if where is not None:
            return _search_page(
                partial(self.scan, collection=collection), where, limit=limit, cursor=cursor
            )
        raw, revision, following, total = self._page(path, limit, cursor)
        items = tuple(
            project(x["data"], self.item_ref(x["key"]), revision, native=False)
            for x in raw
            if x["data"].get("itemType") not in ("note", "attachment", "annotation")
        )
        return ReadPage(items, revision, following, total, len(raw), len(raw) - len(items))

    def search(
        self,
        text: str | None = None,
        *,
        where: str | None = None,
        collection: str | None = None,
        max_items: int = 1000,
        cursor: str | None = None,
    ) -> SearchResult:
        """Search across pages within an explicit raw-item budget.

        ``text`` opts into Zotero's native title/creator/year quick search.
        ``where`` independently filters citation projections with pynakes query
        syntax. With only ``where``, candidates are the whole library or direct
        collection. The cursor binds both queries, scope, budget and revision.
        No matches are returned from a read that changes revision between pages.
        """
        from pynakes.query import parse_query

        if type(max_items) is not int or max_items < 1:
            raise ValueError("Search budget must be a positive integer")
        if text is not None and not text.strip():
            raise ValueError("Native search text must not be empty")
        if text is None and where is None:
            raise ValueError("Supply native search text or --where")
        predicate = parse_query(where) if where is not None else None
        path = (
            f"users/0/collections/{self._key(collection)}/items"
            if collection is not None
            else "users/0/items"
        )
        params = {"q": text, "qmode": "titleCreatorYear"} if text is not None else None
        scope = {"where": where, "max_items": max_items}
        scanned = 0
        items = []
        observed = None
        while scanned < max_items:
            raw, revision, cursor, total = self._page(
                path,
                min(100, max_items - scanned),
                cursor,
                params=params,
                search_scope=scope,
            )
            if observed is not None and revision != observed:
                raise SourceChanged("Zotero changed during search")
            observed = revision
            scanned += len(raw)
            for row in raw:
                if row["data"].get("itemType") in ("note", "attachment", "annotation"):
                    continue
                record = project(row["data"], self.item_ref(row["key"]), revision, native=False)
                if predicate is None or (
                    record.entry_type is not None
                    and predicate.matches(
                        BibEntry(
                            key=record.citation_key or "",
                            type=record.entry_type,
                            fields=dict(record.fields),
                        )
                    )
                ):
                    items.append(record)
            if cursor is None:
                break
        return SearchResult(tuple(items), revision, cursor, total, scanned, scanned - len(items))

    def get(
        self, ref: ItemRef, *, expected_revision: Revision | None = None, native: bool = False
    ) -> ReferenceView:
        key = self._check_ref(ref)
        revision = self._revision()
        if expected_revision is not None and revision != expected_revision:
            raise SourceChanged("Source revision differs from the expected revision")
        _, raw = self._request(f"users/0/items/{key}")
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("data"), dict)
            or raw.get("key") != key
            or raw["data"].get("key", key) != key
        ):
            raise SourceUnavailable("Malformed Zotero item")
        if raw["data"].get("itemType") in ("note", "attachment", "annotation"):
            raise SourceUnsupported(
                "This item is a note, annotation or attachment, not a reference"
            )
        self._check_revision(revision)
        return project(raw["data"], ref, revision, native=native)

    def collections(self, *, limit: int = 50, cursor: str | None = None) -> ReadPage[CollectionRef]:
        raw, revision, following, total = self._page("users/0/collections", limit, cursor)
        if any(not isinstance(x["data"].get("name"), str) for x in raw):
            raise SourceUnavailable("Malformed Zotero collection")
        for row in raw:
            parent = row["data"].get("parentCollection")
            if (
                parent is not None
                and parent is not False
                and (not isinstance(parent, str) or not re.fullmatch(r"[A-Z0-9]{8}", parent))
            ):
                raise SourceUnavailable("Malformed Zotero collection parent")
        items = tuple(
            CollectionRef(
                self.item_ref(x["key"]),
                x["data"]["name"],
                x["data"].get("parentCollection") or None,
            )
            for x in raw
        )
        return ReadPage(items, revision, following, total, len(raw))

    def materials(
        self, ref: ItemRef, *, limit: int = 50, cursor: str | None = None
    ) -> ReadPage[MaterialRef]:
        key = self._check_ref(ref)
        raw, revision, following, total = self._page(f"users/0/items/{key}/children", limit, cursor)
        for row in raw:
            data = row["data"]
            if data.get("parentItem") != key:
                raise SourceUnavailable("Inconsistent Zotero child ownership")
            if any(
                not isinstance(data.get(name, ""), str)
                for name in ("itemType", "title", "contentType", "linkMode")
            ):
                raise SourceUnavailable("Malformed Zotero material metadata")
        items = tuple(
            MaterialRef(
                self.item_ref(x["key"]),
                ref,
                x["data"].get("title", ""),
                x["data"].get("contentType", ""),
                x["data"].get("linkMode", ""),
            )
            for x in raw
            if x["data"].get("itemType") == "attachment"
        )
        return ReadPage(items, revision, following, total, len(raw), len(raw) - len(items))

    def material_path(self, material: MaterialRef) -> Path:
        """Resolve a selected attachment to an existing local file; never fetch it."""
        key = self._check_ref(material.ref)
        self._check_ref(material.owner)
        revision = self._revision()
        _, raw = self._request(f"users/0/items/{key}")
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("data"), dict)
            or raw.get("key") != key
            or raw["data"].get("itemType") != "attachment"
            or raw["data"].get("parentItem") != material.owner.key
        ):
            raise SourceChanged("Attachment ownership changed")
        h, _ = self._request(f"users/0/items/{key}/file", redirect=True)
        url = urlsplit(h.get("Location", ""))
        if url.scheme != "file" or url.netloc not in ("", "localhost") or url.query or url.fragment:
            raise SourceUnsupported("Attachment does not resolve to a local file")
        try:
            # Windows locations carry a drive (file:///C:/...); url2pathname maps it.
            path = Path(url2pathname(url.path))
        except OSError:
            raise SourceUnsupported("Attachment does not resolve to a local file") from None
        if not path.is_absolute() or not path.is_file():
            raise SourceMissing("Attachment URL resolves to an absent file")
        self._check_revision(revision)
        return path
