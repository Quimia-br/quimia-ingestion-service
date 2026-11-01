from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from quimia_ingestion.core.exceptions import ExternalServiceError
from quimia_ingestion.domain.models import SDSDocument
from quimia_ingestion.integrations.zenrows import FallbackHttp


class UnileverSDSProvider:
    """Catálogo público de FDS da Unilever Professional Brasil."""

    catalog_url = "https://www.unileverprofessional.com/br/pt/all-sds/"

    def __init__(self, *, zenrows=None, transport=None, timeout: float = 30.0, max_documents: int = 50):
        self.zenrows = zenrows
        self.transport = transport
        self.timeout = timeout
        self.max_documents = max_documents

    def documents(self):
        try:
            with FallbackHttp(self.zenrows, timeout=self.timeout, transport=self.transport) as client:
                response = client.get(self.catalog_url)
                response.raise_for_status()
                entries = self._parse_catalog(response.text)
                for product_name, pdf_url in entries[: self.max_documents]:
                    pdf = client.get(pdf_url)
                    pdf.raise_for_status()
                    yield SDSDocument(
                        source_id=f"unilever:{pdf_url}",
                        source_url=pdf_url,
                        brand="OMO",
                        product_name=product_name,
                        content=pdf.content,
                        provider="unilever",
                        source_score=100,
                        discovery_method="official_catalog",
                    )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"falha no catálogo Unilever: {exc}") from exc

    @classmethod
    def _parse_catalog(cls, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            label = " ".join(link.stripped_strings)
            href = urljoin(cls.catalog_url, link["href"])
            if "fds" not in label.lower() and "sds" not in label.lower():
                continue
            container = link.find_parent(["li", "div", "article", "section"]) or link.parent
            container_text = " ".join(container.stripped_strings) if container else label
            if "omo" not in container_text.lower():
                continue
            product = cls._extract_product_name(container, label)
            if not product or href in seen:
                continue
            seen.add(href)
            entries.append((product, href))
        return entries

    @staticmethod
    def _extract_product_name(container, fallback: str) -> str:
        if container:
            button = container.find("button")
            if button:
                text = " ".join(button.stripped_strings).strip()
                if text:
                    return text
            input_tag = container.find("input", attrs={"value": True})
            if input_tag and input_tag.get("value"):
                return str(input_tag["value"]).strip()
            text = " ".join(container.stripped_strings)
            parts = re.split(r"FDS\s*-|SDS\s*-", text, flags=re.IGNORECASE)
            if parts and "omo" in parts[0].lower():
                return parts[0].strip(" -")
        cleaned = re.sub(r"(?i)^\s*(FDS|SDS)\s*-\s*", "", fallback).strip()
        return cleaned
