from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

from quimia_ingestion.domain.models import SDSDocument
from quimia_ingestion.domain.rules import BrandPolicy, normalize_text


class ManualInboxProvider:
    """Fallback local: basta colocar PDFs em data/manual_inbox.

    Opcionalmente, `arquivo.pdf.json` pode informar brand/product_name/version/data_atualizacao/source_url.
    Sem sidecar, marca e nome são inferidos do filename.
    """

    def __init__(self, inbox: str | Path, brand_policy: BrandPolicy):
        self.inbox = Path(inbox)
        self.brand_policy = brand_policy

    def documents(self):
        if not self.inbox.exists():
            return
        for path in sorted(self.inbox.glob("*.pdf")):
            meta = self._metadata(path)
            brand = meta.get("brand") or self._infer_brand(path.stem)
            if not brand:
                continue
            rule = self.brand_policy.resolve(brand)
            if not rule:
                continue
            product_name = meta.get("product_name") or self._infer_product(path.stem, rule.display_name)
            raw_date = meta.get("data_atualizacao")
            yield SDSDocument(
                source_id=str(meta.get("source_id") or f"manual:{path.name}"),
                source_url=str(meta.get("source_url") or path.resolve().as_uri()),
                brand=rule.display_name,
                product_name=product_name,
                content=path.read_bytes(),
                version=meta.get("version"),
                update_date=date.fromisoformat(raw_date) if raw_date else None,
                provider="manual",
                source_score=95,
                discovery_method="manual_inbox",
            )

    def _metadata(self, path: Path) -> dict:
        sidecar = Path(str(path) + ".json")
        if not sidecar.exists():
            return {}
        return json.loads(sidecar.read_text(encoding="utf-8"))

    def _infer_brand(self, stem: str) -> str | None:
        normalized = normalize_text(stem)
        for rule in self.brand_policy.all_rules():
            for alias in rule.aliases + (rule.display_name,):
                if normalize_text(alias) in normalized:
                    return rule.display_name
        return None

    @staticmethod
    def _infer_product(stem: str, brand: str) -> str:
        cleaned = re.sub(r"(?i)\b(fds|fispq|sds)\b", " ", stem)
        cleaned = re.sub(re.escape(brand), " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"[_\-]+", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip() or brand
