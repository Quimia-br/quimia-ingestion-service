from __future__ import annotations

from collections import deque
import re
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from quimia_ingestion.core.exceptions import ExternalServiceError
from quimia_ingestion.domain.models import SDSDocument
from quimia_ingestion.integrations.zenrows import FallbackHttp
from quimia_ingestion.domain.rules import BrandPolicy, normalize_text


class SitemapSDSProvider:
    """Descoberta gratuita via robots/sitemaps e links públicos do fabricante."""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        brand_policy: BrandPolicy,
        allowed_brand_keys: tuple[str, ...],
        source_score: int = 100,
        zenrows=None,
        transport=None,
        timeout: float = 20.0,
        max_sitemaps: int = 20,
        max_pages: int = 120,
        max_documents: int = 50,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.brand_policy = brand_policy
        self.allowed_brand_keys = set(allowed_brand_keys)
        self.source_score = source_score
        self.zenrows = zenrows
        self.transport = transport
        self.timeout = timeout
        self.max_sitemaps = max_sitemaps
        self.max_pages = max_pages
        self.max_documents = max_documents

    def documents(self):
        try:
            with FallbackHttp(self.zenrows, timeout=self.timeout, transport=self.transport) as client:
                urls = self._discover_urls(client)
                count = 0
                for url in urls:
                    if count >= self.max_documents:
                        break
                    info = self._match_brand_product(url)
                    if not info:
                        continue
                    brand, product = info
                    response = client.get(url)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if not (response.content.startswith(b"%PDF") or "application/pdf" in content_type):
                        continue
                    count += 1
                    yield SDSDocument(
                        source_id=f"{self.name}:{url}",
                        source_url=url,
                        brand=brand,
                        product_name=product,
                        content=response.content,
                        provider=self.name,
                        source_score=self.source_score,
                        discovery_method="sitemap",
                    )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"falha no provider {self.name}: {exc}") from exc

    def _discover_urls(self, client: FallbackHttp) -> list[str]:
        candidates: list[str] = []
        sitemaps = deque(self._initial_sitemaps(client))
        seen_sitemaps: set[str] = set()
        pages: list[str] = []
        while sitemaps and len(seen_sitemaps) < self.max_sitemaps:
            sitemap = sitemaps.popleft()
            if sitemap in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap)
            try:
                response = client.get(sitemap)
                if response.status_code >= 400:
                    continue
                locs = self._xml_locs(response.text)
            except (httpx.HTTPError, ElementTree.ParseError):
                continue
            for loc in locs:
                low = loc.lower()
                if low.endswith(".xml") or "sitemap" in low:
                    sitemaps.append(loc)
                elif self._looks_like_pdf_url(loc):
                    candidates.append(loc)
                elif len(pages) < self.max_pages and self._looks_relevant_page(loc):
                    pages.append(loc)

        # Alguns sitemaps não incluem attachments. Varremos só páginas com marca/FDS.
        for page_url in pages:
            try:
                response = client.get(page_url)
                if response.status_code >= 400:
                    continue
                for href in re.findall(r'href=["\']([^"\']+)["\']', response.text, flags=re.IGNORECASE):
                    url = urljoin(page_url, href)
                    if self._looks_like_pdf_url(url):
                        candidates.append(url)
            except httpx.HTTPError:
                continue
        return list(dict.fromkeys(candidates))

    def _initial_sitemaps(self, client: FallbackHttp) -> list[str]:
        result = [f"{self.base_url}/wp-sitemap.xml", f"{self.base_url}/sitemap_index.xml", f"{self.base_url}/sitemap.xml"]
        try:
            robots = client.get(f"{self.base_url}/robots.txt")
            if robots.status_code < 400:
                for line in robots.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        result.append(line.split(":", 1)[1].strip())
        except httpx.HTTPError:
            pass
        return list(dict.fromkeys(result))

    @staticmethod
    def _xml_locs(xml_text: str) -> list[str]:
        root = ElementTree.fromstring(xml_text)
        return [element.text.strip() for element in root.iter() if element.tag.endswith("loc") and element.text]

    def _looks_like_pdf_url(self, url: str) -> bool:
        low = url.lower()
        return low.endswith(".pdf") and any(marker in low for marker in ("fds", "fispq", "sds", "seguranca", "safety"))

    def _looks_relevant_page(self, url: str) -> bool:
        normalized = normalize_text(url)
        if any(marker in normalized for marker in ("fds", "fispq", "sds", "seguranca")):
            return True
        return any(normalize_text(rule.display_name) in normalized for rule in self._allowed_rules())

    def _allowed_rules(self):
        return [rule for rule in self.brand_policy.all_rules() if rule.key in self.allowed_brand_keys]

    def _match_brand_product(self, url: str) -> tuple[str, str] | None:
        decoded = urlparse(url).path.rsplit("/", 1)[-1]
        normalized = normalize_text(decoded)
        for rule in self._allowed_rules():
            aliases = rule.aliases + (rule.display_name,)
            if any(normalize_text(alias) in normalized for alias in aliases):
                product = re.sub(r"(?i)\.(pdf)$", "", decoded)
                product = re.sub(r"(?i)\b(fds|fispq|sds)\b", " ", product)
                product = re.sub(r"[_\-]+", " ", product)
                product = re.sub(r"\s+", " ", product).strip()
                return rule.display_name, product
        return None


class FloraSDSProvider(SitemapSDSProvider):
    def __init__(self, brand_policy: BrandPolicy, **kwargs):
        super().__init__(
            name="flora",
            base_url="https://flora.com.br",
            brand_policy=brand_policy,
            allowed_brand_keys=("minuano", "assim", "brisa"),
            source_score=100,
            **kwargs,
        )

