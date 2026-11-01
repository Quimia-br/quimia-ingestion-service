from __future__ import annotations

import re
from urllib.parse import parse_qs, quote_plus, urlparse
from html import unescape

import httpx

from quimia_ingestion.core.exceptions import ExternalServiceError
from quimia_ingestion.domain.models import SDSDocument
from quimia_ingestion.domain.rules import BrandPolicy, normalize_text
from quimia_ingestion.integrations.zenrows import FallbackHttp, ZenRowsClient
from quimia_ingestion.validation.pdf import product_name_from_pdf

_HREF = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


class WebSearchSDSProvider:
    """Fallback de descoberta: DuckDuckGo (HTML) via ZenRows, priorizando domínios oficiais.

    Google via ZenRows foi descartado: exige JS + proxy premium e não entrega resultados.

    Sem ZenRows configurado, simplesmente não produz documentos para que providers
    gratuitos/locais continuem funcionando.
    """

    def __init__(self, zenrows: ZenRowsClient | None, brand_policy: BrandPolicy, *, transport=None, timeout: float = 30.0, max_results_per_brand: int = 5):
        self.zenrows = zenrows
        self.brand_policy = brand_policy
        self.transport = transport
        self.timeout = timeout
        self.max_results_per_brand = max_results_per_brand

    def documents(self):
        if not self.zenrows:
            return
        try:
            with FallbackHttp(self.zenrows, timeout=self.timeout, transport=self.transport) as client:
                for rule in self.brand_policy.all_rules():
                    for link, title in self._search_brand(rule):
                        try:
                            response = client.get(link)
                            response.raise_for_status()
                        except httpx.HTTPError:
                            continue
                        if not response.content.startswith(b"%PDF"):
                            continue
                        official = any(domain in link.lower() for domain in rule.official_domains)
                        yield SDSDocument(
                            source_id=f"search:{link}",
                            source_url=link,
                            brand=rule.display_name,
                            # O título do resultado costuma ser trecho do PDF ("Brisa BR Esta informação..."); o cabeçalho é melhor.
                            product_name=product_name_from_pdf(response.content) or self._product_name(title or rule.display_name, rule.display_name),
                            content=response.content,
                            provider="search",
                            source_score=90 if official else 70,
                            discovery_method="zenrows_web_search",
                        )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"falha na busca web de FDS: {exc}") from exc

    def _search_brand(self, rule) -> list[tuple[str, str]]:
        # DuckDuckGo lida mal com OR/parênteses: uma busca por domínio oficial (custo ~0.001 crédito cada).
        queries = [f"site:{domain} {rule.display_name} FISPQ filetype:pdf" for domain in rule.official_domains]
        queries = queries or [f"{rule.display_name} FISPQ filetype:pdf"]
        links: dict[str, str] = {}
        for query in queries:
            response = self.zenrows.fetch(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=br-pt")
            if response.status_code >= 400:
                raise ExternalServiceError(f"ZenRows/DuckDuckGo {response.status_code}: {response.text[:200]}")
            for link, title in self.parse_pdf_links(response.text):
                links.setdefault(link, title)
        return list(links.items())[: self.max_results_per_brand]

    @staticmethod
    def parse_pdf_links(html: str) -> list[tuple[str, str]]:
        """Links de PDF de uma página de resultados do DuckDuckGo: [(url, título)]."""
        result: dict[str, str] = {}
        for href, inner in _HREF.findall(html):
            href = unescape(href)
            if "uddg=" in href:
                href = parse_qs(urlparse(href).query).get("uddg", [""])[0]
            if not href.startswith("http") or "duckduckgo." in (urlparse(href).hostname or ""):
                continue
            if not urlparse(href).path.lower().endswith(".pdf"):
                continue
            title = " ".join(unescape(_TAGS.sub(" ", inner)).split())
            if len(title) >= len(result.get(href, "")):
                result[href] = title
        return list(result.items())

    @staticmethod
    def _product_name(title: str, brand: str) -> str:
        normalized_title = title
        for marker in ("FDS", "FISPQ", "SDS"):
            normalized_title = normalized_title.replace(marker, " ").replace(marker.lower(), " ")
        if normalize_text(brand) in normalize_text(normalized_title):
            return " ".join(normalized_title.split()).strip(" -|")
        return f"{brand} {' '.join(normalized_title.split())}".strip()
