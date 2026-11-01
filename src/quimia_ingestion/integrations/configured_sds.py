from __future__ import annotations

from datetime import date
from pathlib import Path
import yaml
import httpx

from quimia_ingestion.core.exceptions import ExternalServiceError
from quimia_ingestion.domain.models import SDSDocument
from quimia_ingestion.integrations.zenrows import FallbackHttp
from quimia_ingestion.domain.rules import BrandPolicy


class ConfiguredOfficialSDSProvider:
    """Bootstrap versionado de URLs oficiais conhecidas.

    Útil quando o fabricante publica PDFs, mas não oferece um catálogo ou sitemap
    confiável. As URLs continuam sujeitas ao validator antes da ingestão.
    """

    def __init__(self, catalog_path: str | Path, brand_policy: BrandPolicy, *, zenrows=None, transport=None, timeout: float = 30.0):
        self.catalog_path = Path(catalog_path)
        self.brand_policy = brand_policy
        self.zenrows = zenrows
        self.transport = transport
        self.timeout = timeout

    def documents(self):
        if not self.catalog_path.exists():
            return
        payload = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8")) or {}
        try:
            with FallbackHttp(self.zenrows, timeout=self.timeout, transport=self.transport) as client:
                for item in payload.get("documents", []):
                    rule = self.brand_policy.resolve(item.get("brand", ""))
                    if not rule:
                        continue
                    url = item["source_url"]
                    if not any(domain in url.lower() for domain in rule.official_domains):
                        continue
                    response = client.get(url)
                    response.raise_for_status()
                    raw_date = item.get("data_atualizacao")
                    yield SDSDocument(
                        source_id=str(item.get("source_id") or f"catalog:{url}"),
                        source_url=url,
                        brand=rule.display_name,
                        product_name=item["product_name"],
                        content=response.content,
                        version=item.get("version"),
                        update_date=date.fromisoformat(raw_date) if raw_date else None,
                        provider=item.get("provider") or "official_catalog",
                        source_score=100,
                        discovery_method="configured_official_catalog",
                    )
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"falha no catálogo oficial configurado: {exc}") from exc
