"""Synthetic Zotero transport shared by backend and CLI contract tests."""

import httpx


class LocalAPI:
    def __init__(self):
        self.revision = 7
        self.server = "synthetic-instance"
        self.version = "10.0.7"
        self.calls = []
        self.items = [
            {
                "key": "ABCDEFGH",
                "data": {
                    "itemType": "book",
                    "title": "Principia",
                    "date": "1687",
                    "creators": [
                        {"creatorType": "author", "firstName": "Isaac", "lastName": "Newton"}
                    ],
                    "extra": "private memo",
                    "tags": [{"tag": "reading"}],
                    "collections": ["DEFGHJKL"],
                },
            },
            {
                "key": "BCDEFGHJ",
                "data": {
                    "itemType": "attachment",
                    "parentItem": "ABCDEFGH",
                    "title": "Scan",
                    "contentType": "application/pdf",
                    "linkMode": "imported_file",
                    "collections": ["DEFGHJKL"],
                },
            },
            {
                "key": "CDEFGHJK",
                "data": {
                    "itemType": "journalArticle",
                    "title": "An invented experiment",
                    "publicationTitle": "Example Journal",
                    "DOI": "10.1234/example",
                    "date": "1901-02-03",
                },
            },
        ]
        self.override = None
        self.collections = [
            {"key": "DEFGHJKL", "data": {"name": "History", "parentCollection": False}},
            {"key": "EFGHJKLM", "data": {"name": "Books", "parentCollection": "DEFGHJKL"}},
        ]
        self.location = "file:///absent/scan.pdf"
        self.change_after_page = False

    def __call__(self, request):
        self.calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "127.0.0.1"
        assert "Zotero-API-Key" not in request.headers
        headers = {
            "Zotero-API-Version": "3",
            "Zotero-Schema-Version": "44",
            "Zotero-Server-ID": self.server,
            "X-Zotero-Version": self.version,
            "Last-Modified-Version": str(self.revision),
        }
        if self.override:
            response = self.override(request, headers)
            if response is not None:
                return response
        path = request.url.path
        if path == "/api/":
            return httpx.Response(200, headers=headers, text="Local API")
        if request.url.params.get("format") == "versions":
            return httpx.Response(200, headers=headers, json={})
        if path.endswith("/file"):
            return httpx.Response(302, headers={**headers, "Location": self.location})
        if "limit" in request.url.params:
            if path.endswith("collections"):
                rows = self.collections
            elif path.endswith("children"):
                owner = path.split("/")[-2]
                rows = [x for x in self.items if x["data"].get("parentItem") == owner]
            elif "/collections/" in path:
                collection = path.split("/")[-2]
                if collection not in {x["key"] for x in self.collections}:
                    return httpx.Response(404, headers=headers)
                rows = [x for x in self.items if collection in x["data"].get("collections", [])]
            else:
                rows = self.items
            start = int(request.url.params.get("start", 0))
            limit = int(request.url.params["limit"])
            headers["Total-Results"] = str(len(rows))
            if self.change_after_page:
                self.revision += 1
            return httpx.Response(200, headers=headers, json=rows[start : start + limit])
        found = next((x for x in self.items if path.endswith(x["key"])), None)
        return httpx.Response(200 if found else 404, headers=headers, json=found)
