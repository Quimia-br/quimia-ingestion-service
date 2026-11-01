import csv
import json
from io import BytesIO
from PIL import Image, ImageDraw

from quimia_ingestion.domain.models import ProductRecord, ImageCandidate
from quimia_ingestion.publishers.local_bd import LocalBdPublisher


def make_png():
    image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((200, 100, 310, 420), fill=(20, 30, 40, 255))
    out = BytesIO(); image.save(out, "PNG"); return out.getvalue()


def test_publisher_writes_only_local_seed_asset_manifest(tmp_path):
    repo = tmp_path / "quimia-bd-local"
    seed = repo / "src/database/sql/data_load/seeds/seed_produto.csv"
    seed.parent.mkdir(parents=True)
    seed.write_text("nome,marca,tipo_produto,descricao,foto_url\nMultiuso,Minuano,limpeza_geral,Teste,\n", encoding="utf-8")

    publisher = LocalBdPublisher(repo)
    product = ProductRecord(7, "Minuano", "Multiuso", "limpeza_geral", "Teste")
    candidate = ImageCandidate("https://img.test/x.png", "https://site.test/item", "Site", "Minuano Multiuso")
    target = publisher.publish_product_image(product, make_png(), candidate, 0.95)

    assert target.exists()
    with seed.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["foto_url"].endswith(target.name)

    manifest = json.loads((repo / "src/database/assets/manifest_produtos.json").read_text(encoding="utf-8"))
    assert manifest["products"][0]["product_id"] == 7
    assert manifest["products"][0]["edges_validated"] is True
