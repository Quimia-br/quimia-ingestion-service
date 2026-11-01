from __future__ import annotations

import json
from pathlib import Path
import re

from quimia_ingestion.domain.rules import normalize_text
from quimia_ingestion.storage.documents import DocumentStorage
from quimia_ingestion.validation.pdf import SDSStructuralValidator


class PublicDiscoveryExportWorkflow:
    """Descobre e valida FDS públicas, mas não toca no PostgreSQL.

    Os PDFs e um manifest compatível com LocalPDFProvider são escritos localmente.
    """

    def __init__(self, *, provider, output_dir: str | Path, validator: SDSStructuralValidator, min_auto_source_score: int = 85):
        self.provider = provider
        self.output_dir = Path(output_dir)
        self.validator = validator
        self.min_auto_source_score = min_auto_source_score
        self.pdf_dir = self.output_dir / "pdfs"
        self.pdf_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict:
        manifest = {"documents": []}
        review: list[dict] = []
        rejected: list[dict] = []
        seen_hashes: set[str] = set()
        storage = DocumentStorage(self.pdf_dir)

        for doc in self.provider.documents():
            digest = storage.sha256(doc.content)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            report = self.validator.validate(doc.content, expected_brand=doc.brand, expected_product=doc.product_name)
            common = {
                "source_id": doc.source_id,
                "source_url": doc.source_url,
                "brand": doc.brand,
                "product_name": doc.product_name,
                "provider": doc.provider,
                "source_score": doc.source_score,
                "reasons": list(report.reasons),
            }
            if not report.accepted:
                rejected.append(common)
                continue
            if report.review_required or doc.source_score < self.min_auto_source_score:
                review.append(common)
                continue

            filename = self._filename(doc.brand, doc.product_name, digest)
            path = self.pdf_dir / filename
            path.write_bytes(doc.content)
            resolved_version = doc.version or report.version
            resolved_date = doc.update_date or report.document_date
            manifest["documents"].append({
                "file": str(Path("pdfs") / filename),
                "source_id": doc.source_id,
                "source_url": doc.source_url,
                "brand": doc.brand,
                "product_name": doc.product_name,
                "version": resolved_version,
                "data_atualizacao": resolved_date.isoformat() if resolved_date else None,
            })

        self.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.output_dir / "manifest.json"
        review_path = self.output_dir / "review_required.json"
        rejected_path = self.output_dir / "rejected.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
        rejected_path.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "accepted": len(manifest["documents"]),
            "provider_errors": getattr(self.provider, "errors", []),
            "review_required": len(review),
            "rejected": len(rejected),
            "manifest": str(manifest_path),
            "review_file": str(review_path),
            "rejected_file": str(rejected_path),
        }

    @staticmethod
    def _filename(brand: str, product: str, digest: str) -> str:
        slug = normalize_text(f"{brand} {product}").replace(" ", "-")
        slug = re.sub(r"-+", "-", slug).strip("-")[:90]
        return f"{slug}-{digest[:10]}.pdf"
