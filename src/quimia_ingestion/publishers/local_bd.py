from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import unicodedata

from quimia_ingestion.domain.models import ProductRecord, ImageCandidate


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-+", "-", value)


def product_key(brand: str, name: str) -> str:
    """Identidade do produto entre seed, manifest e state. Não usa o id: ele difere entre bancos."""
    return f"{brand.casefold()}|{name.casefold()}"


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class LocalBdPublisher:
    """Escreve SOMENTE em um checkout local informado explicitamente."""

    SEED_REL = Path("src/database/sql/data_load/seeds/seed_produto.csv")
    ASSET_REL = Path("src/database/assets/produtos")
    MANIFEST_REL = Path("src/database/assets/manifest_produtos.json")

    def __init__(self, repo_path: str | Path):
        self.repo = Path(repo_path).resolve()
        if not self.repo.exists():
            raise FileNotFoundError(self.repo)

    @staticmethod
    def _filename(product: ProductRecord) -> str:
        return f"produto-{slugify(product.brand)}-{slugify(product.name)}.png"

    def _read_manifest(self) -> dict:
        path = self.repo / self.MANIFEST_REL
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": 1, "products": []}

    def find_published(self, product: ProductRecord) -> dict | None:
        """Entrada do manifest só se PNG, seed e manifest estiverem consistentes entre si; senão None."""
        filename = self._filename(product)
        key = product_key(product.brand, product.name)
        entry = next(
            (p for p in self._read_manifest().get("products", []) if product_key(p.get("brand", ""), p.get("product", "")) == key),
            None,
        )
        target = self.repo / self.ASSET_REL / filename
        if not entry or entry.get("file") != filename or not target.exists():
            return None
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry.get("processed_sha256"):
            return None
        seed = self.repo / self.SEED_REL
        if not seed.exists():
            return None
        with seed.open("r", encoding="utf-8-sig", newline="") as fh:
            has_row = any(
                product_key(r.get("marca", ""), r.get("nome", "")) == key and r.get("foto_url", "").endswith("/" + filename)
                for r in csv.DictReader(fh)
            )
        return entry if has_row else None

    def publish_product_image(self, product: ProductRecord, png_bytes: bytes, source: ImageCandidate, score: float) -> Path:
        assets = self.repo / self.ASSET_REL
        assets.mkdir(parents=True, exist_ok=True)
        filename = self._filename(product)
        target = assets / filename
        # Ordem PNG -> seed -> manifest: o manifest é o último a ser gravado, então um crash no meio
        # deixa find_published() = None e a próxima execução refaz tudo sobre os mesmos arquivos.
        _atomic_write(target, png_bytes)
        foto_url = f"https://raw.githubusercontent.com/Quimia-br/quimia-bd/main/{self.ASSET_REL.as_posix()}/{filename}"
        self._upsert_seed(product, foto_url)
        self._upsert_manifest(product, target, source, score)
        return target

    def _upsert_seed(self, product: ProductRecord, foto_url: str) -> None:
        seed = self.repo / self.SEED_REL
        seed.parent.mkdir(parents=True, exist_ok=True)
        fields = ["nome", "marca", "tipo_produto", "descricao", "foto_url"]
        rows: list[dict[str, str]] = []
        if seed.exists():
            with seed.open("r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
        key = (product.name.casefold(), product.brand.casefold())
        updated = False
        for row in rows:
            if (row.get("nome", "").casefold(), row.get("marca", "").casefold()) == key:
                row["foto_url"] = foto_url
                updated = True
                break
        if not updated:
            rows.append({
                "nome": product.name,
                "marca": product.brand,
                "tipo_produto": product.tipo_produto or "",
                "descricao": product.descricao or "",
                "foto_url": foto_url,
            })
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        _atomic_write(seed, buf.getvalue().encode("utf-8"))

    def _upsert_manifest(self, product: ProductRecord, target: Path, source: ImageCandidate, score: float) -> None:
        manifest_path = self.repo / self.MANIFEST_REL
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = self._read_manifest()
        entry = {
            "product_id": product.id,
            "brand": product.brand,
            "product": product.name,
            "file": target.name,
            "source_url": source.page_url,
            "source_image_url": source.original_url,
            "source": source.source,
            "processed_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "match_score": round(score, 4),
            "background_removed": True,
            "alpha_validated": True,
            "edges_validated": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        products = manifest.setdefault("products", [])
        # Por marca+produto, não por id: o id difere entre bancos e colidiria com outro produto.
        key = product_key(product.brand, product.name)
        products[:] = [p for p in products if product_key(p.get("brand", ""), p.get("product", "")) != key]
        products.append(entry)
        _atomic_write(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
