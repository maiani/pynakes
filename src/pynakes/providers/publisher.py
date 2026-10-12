"""Publisher landing-page discovery for entitled PDF downloads.

This provider does not authenticate or bypass access controls. It follows a
DOI to the publisher landing page and extracts conventional PDF metadata and
supplement links. Whether a discovered URL is accessible is decided by the
normal HTTP download step, using the caller's existing network entitlement.
"""

from __future__ import annotations

import codecs
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

from pynakes._identifiers import normalize_doi
from pynakes.providers._http import ProviderFetchError, fetch_bytes


@dataclass(frozen=True)
class PublisherArtifacts:
    """Artifact URLs advertised by one publisher landing page."""

    landing_url: str
    published_pdf_url: str | None = None
    supplement_pdf_urls: tuple[str, ...] = ()


class _LandingPageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.published_pdf_url: str | None = None
        self.supplement_urls: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value for name, value in attrs if value is not None}
        if tag.lower() == "meta":
            name = (values.get("name") or values.get("property") or "").lower()
            content = values.get("content")
            if name == "citation_pdf_url" and content and self.published_pdf_url is None:
                self.published_pdf_url = urljoin(self.base_url, content.strip())
        elif tag.lower() == "a":
            self._anchor_href = values.get("href")
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._anchor_href is None:
            return
        href = self._anchor_href.strip()
        text = " ".join(self._anchor_text).strip()
        if href and _looks_like_supplement(href, text):
            self.supplement_urls.append(urljoin(self.base_url, href))
        self._anchor_href = None
        self._anchor_text = []


def discover_artifacts_for_doi(
    doi: str,
    *,
    timeout: float = 20.0,
    opener: Callable[..., object] | None = None,
) -> PublisherArtifacts:
    """Follow *doi* and discover publisher PDF and supplement URLs.

    The request goes through the same guarded client as every other provider
    request (``fetch_bytes`` in ``pynakes.providers._http``): every hop, redirects
    included, must be a public ``http(s)`` destination without embedded
    credentials, under one overall deadline and response-size cap. It relies
    only on the network location the process already has — a campus network or
    VPN whose addresses the publisher recognizes. Environment proxy variables
    (``HTTP_PROXY``/``HTTPS_PROXY``) are not used, and browser cookies and
    interactive SSO sessions are deliberately not imported.

    ``opener`` is injectable for testing (same signature as
    :func:`urllib.request.urlopen`).
    """
    normalized = normalize_doi(doi)
    url = f"https://doi.org/{quote(normalized, safe='/')}"
    info: dict = {}
    data = fetch_bytes(
        url,
        accept="text/html,application/pdf",
        timeout=timeout,
        error_class=ProviderFetchError,
        label=f"DOI {normalized}",
        opener=opener,
        response_info=info,
    )
    landing_url = info.get("final_url") or url
    if data.startswith(b"%PDF"):
        return PublisherArtifacts(landing_url=landing_url, published_pdf_url=landing_url)

    parser = _LandingPageParser(landing_url)
    parser.feed(data.decode(_charset(info.get("content_type")), errors="replace"))
    supplements = tuple(dict.fromkeys(parser.supplement_urls))
    return PublisherArtifacts(
        landing_url=landing_url,
        published_pdf_url=parser.published_pdf_url,
        supplement_pdf_urls=supplements,
    )


def _charset(content_type: str | None) -> str:
    """Return the charset a ``Content-Type`` names when Python knows it, else UTF-8."""
    for param in (content_type or "").split(";")[1:]:
        name, _, value = param.partition("=")
        if name.strip().lower() == "charset":
            charset = value.strip().strip('"')
            try:
                codecs.lookup(charset)
            except LookupError:
                break
            return charset
    return "utf-8"


def _looks_like_supplement(href: str, text: str) -> bool:
    value = f"{href} {text}".lower()
    markers = (
        "supplement",
        "supporting information",
        "supporting-information",
        "suppinfo",
        "suppl_file",
        "additional file",
        "electronic supplementary",
    )
    return any(marker in value for marker in markers)
