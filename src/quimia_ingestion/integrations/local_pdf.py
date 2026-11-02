from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from quimia_ingestion.domain.models import SDSDocument


class LocalPDFProvider:
    """Provider de desenvolvimento. Lê PDFs descritos por um manifest JSON local."""

    def __init__(self, manifest_path: str | Path):
        self.manifest_path = Path(manifest_path)

    def documents(self):
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        base = self.manifest_path.parent
        for item in payload.get("documents", []):
            path = base / item["file"]
            raw_date = item.get("data_atualizacao")
            yield SDSDocument(
                source_id=str(item.get("source_id") or path.name),
                source_url=item.get("source_url") or path.resolve().as_uri(),
                brand=item["brand"],
                product_name=item["product_name"],
                version=item.get("version"),
                update_date=date.fromisoformat(raw_date) if raw_date else None,
                content=path.read_bytes(),
                provider="local",
                source_score=100,
                discovery_method="local_manifest",
            )
