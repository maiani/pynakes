"""Publisher landing-page discovery for entitled PDF downloads.

This provider does not authenticate or bypass access controls. It follows a
DOI to the publisher landing page and extracts conventional PDF metadata and
supplement links. Whether a discovered URL is accessible is decided by the
normal HTTP download step, using the caller's existing network entitlement.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import quote, urljoin

import httpx

from pynakes._identifiers import normalize_doi
from pynakes.providers._http import USER_AGENT, ProviderFetchError


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


def discover_artifacts_for_doi(doi: str, *, timeout: float = 20.0) -> PublisherArtifacts:
    """Follow *doi* and discover publisher PDF and supplement URLs.

    The request relies only on normal HTTP behavior, including IP-based access
    supplied by the user's university network, VPN, or configured proxy.
    Browser cookies and interactive SSO sessions are deliberately not imported.
    """
    normalized = normalize_doi(doi)
    url = f"https://doi.org/{quote(normalized, safe='/')}"
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf"}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProviderFetchError(
            f"Publisher returned HTTP {exc.response.status_code} for DOI {normalized}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderFetchError(f"Network error resolving DOI {normalized}: {exc}") from exc

    landing_url = str(response.url)
    if response.content.startswith(b"%PDF"):
        return PublisherArtifacts(landing_url=landing_url, published_pdf_url=landing_url)

    parser = _LandingPageParser(landing_url)
    parser.feed(response.text)
    supplements = tuple(dict.fromkeys(parser.supplement_urls))
    return PublisherArtifacts(
        landing_url=landing_url,
        published_pdf_url=parser.published_pdf_url,
        supplement_pdf_urls=supplements,
    )


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
