from __future__ import annotations

import hashlib

from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.images.matcher import rank_candidates, search_name
from quimia_ingestion.images.normalize import normalize_png
from quimia_ingestion.images.quality import validate_cutout, validate_png
from quimia_ingestion.publishers.local_bd import product_key


class ProductImageWorkflow:
    def __init__(
        self, *, repository, search, downloader, remover, publisher, brand_policy: BrandPolicy,
        canvas_size: int = 1254, min_size: int = 256, outer_frame_ratio: float = 0.03,
        required_outer_transparency: float = 0.98, auto_approve_score: float = 0.90, state=None,
    ):
        self.repository = repository
        self.search = search
        self.downloader = downloader
        self.remover = remover
        self.publisher = publisher
        self.brand_policy = brand_policy
        self.canvas_size = canvas_size
        self.min_size = min_size
        self.outer_frame_ratio = outer_frame_ratio
        self.required_outer_transparency = required_outer_transparency
        self.auto_approve_score = auto_approve_score
        self.state = state

    def run(self) -> list[dict]:
        results: list[dict] = []
        for product in self.repository.list_products_without_image():
            brand = self.brand_policy.resolve(product.brand)
            if not brand:
                results.append({"product_id": product.id, "status": "REJECTED", "reason": "marca fora da allowlist"})
                continue
            key = product_key(product.brand, product.name)
            # Já publicado (PNG, seed e manifest consistentes): nenhuma busca, download ou rembg.
            # Se o state.db perdeu o registro, ele é recriado a partir dos arquivos (reconciliação).
            published = self.publisher.find_published(product)
            if published:
                if self.state and not self.state.get_image(key):
                    self.state.set_image(key, product.id, published["file"], published["processed_sha256"])
                results.append({"product_id": product.id, "status": "ALREADY_PUBLISHED", "file": published["file"]})
                continue
            # Só a busca/matching usa o nome sem multiplicador de caixa; product.name segue intacto.
            query = f'"{brand.display_name}" "{search_name(product.name)}" produto'
            candidates = rank_candidates(
                self.search.search(query), brand=brand, product_name=product.name,
                other_brands=self.brand_policy.other_brands,
            )
            accepted = False
            for candidate in candidates:
                if candidate.score < self.auto_approve_score:
                    break
                try:
                    original = self.downloader.download(candidate.original_url)
                    removed = self.remover.remove(original)
                    # O gate é absoluto: nem match_score 0.99 compensa fundo, borda ou halo.
                    cutout = validate_cutout(
                        removed,
                        original=original,
                        min_object_size=self.min_size,
                        outer_frame_ratio=self.outer_frame_ratio,
                        required_outer_transparency=self.required_outer_transparency,
                    )
                    if not cutout.accepted:
                        results.append({"product_id": product.id, "status": "CANDIDATE_REJECTED", "url": candidate.original_url, "reasons": list(cutout.reasons)})
                        continue
                    normalized = normalize_png(removed, self.canvas_size)
                    quality = validate_png(normalized, canvas_size=self.canvas_size, min_size=self.min_size)
                    if not quality.accepted:
                        results.append({"product_id": product.id, "status": "CANDIDATE_REJECTED", "url": candidate.original_url, "reasons": list(quality.reasons)})
                        continue
                    path = self.publisher.publish_product_image(product, normalized, candidate, candidate.score)
                    if self.state:
                        self.state.set_image(key, product.id, str(path), hashlib.sha256(normalized).hexdigest())
                    results.append({"product_id": product.id, "status": "PUBLISHED_LOCAL", "path": str(path), "score": candidate.score})
                    accepted = True
                    break
                except Exception as exc:
                    results.append({"product_id": product.id, "status": "CANDIDATE_FAILED", "reason": str(exc)})
            if not accepted:
                top_score = candidates[0].score if candidates else 0.0
                # candidates=0 é busca vazia (falha do buscador/layout), não "só candidatos fracos".
                results.append({"product_id": product.id, "status": "REVIEW_REQUIRED", "top_score": top_score, "candidates": len(candidates)})
        return results
