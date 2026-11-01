from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw

from quimia_ingestion.domain.models import ProductRecord, ImageCandidate
from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.workflows.enrich_images import ProductImageWorkflow


class Repo:
    def list_products_without_image(self):
        return [ProductRecord(1, "Minuano", "Limpador Multiuso Original")]

class Search:
    def search(self, query):
        return [ImageCandidate(
            "https://img.test/x.png", "https://flora.com.br/minuano/limpador-multiuso-original",
            "Flora", "Minuano Limpador Multiuso Original", 1000, 1000, True, False
        )]

class Downloader:
    def download(self, url): return b"original"

class Remover:
    def remove(self, data):
        image = Image.new("RGBA", (600, 700), (0,0,0,0))
        ImageDraw.Draw(image).rectangle((150, 60, 450, 640), fill=(10,20,30,255))
        out=BytesIO(); image.save(out,"PNG"); return out.getvalue()

class Publisher:
    def __init__(self, root): self.root=Path(root)
    def find_published(self, product): return None
    def publish_product_image(self, product, png_bytes, source, score):
        p=self.root/"out.png"; p.write_bytes(png_bytes); return p


def test_image_workflow_auto_publishes_good_candidate(tmp_path):
    workflow = ProductImageWorkflow(
        repository=Repo(), search=Search(), downloader=Downloader(), remover=Remover(),
        publisher=Publisher(tmp_path), brand_policy=BrandPolicy.from_yaml("config/brands.yaml"),
        auto_approve_score=0.85,
    )
    result = workflow.run()
    assert any(item["status"] == "PUBLISHED_LOCAL" for item in result)
    assert (tmp_path / "out.png").exists()


def test_empty_search_is_reported_as_zero_candidates_not_just_low_score(tmp_path):
    class Empty(Search):
        def search(self, query): return []
    workflow = ProductImageWorkflow(
        repository=Repo(), search=Empty(), downloader=Downloader(), remover=Remover(),
        publisher=Publisher(tmp_path), brand_policy=BrandPolicy.from_yaml("config/brands.yaml"),
    )
    assert workflow.run() == [{"product_id": 1, "status": "REVIEW_REQUIRED", "top_score": 0.0, "candidates": 0}]


import csv
import json

from quimia_ingestion.publishers.local_bd import LocalBdPublisher
from quimia_ingestion.state.sqlite import StateStore


class CountingSearch(Search):
    calls = 0
    def search(self, query):
        CountingSearch.calls += 1
        return super().search(query)


class CountingDownloader(Downloader):
    calls = 0
    def download(self, url):
        CountingDownloader.calls += 1
        return super().download(url)


class CountingRemover(Remover):
    calls = 0
    def remove(self, data):
        CountingRemover.calls += 1
        return super().remove(data)


def _real_flow(bd, state):
    for cls in (CountingSearch, CountingDownloader, CountingRemover):
        cls.calls = 0
    return ProductImageWorkflow(
        repository=Repo(), search=CountingSearch(), downloader=CountingDownloader(), remover=CountingRemover(),
        publisher=LocalBdPublisher(bd), brand_policy=BrandPolicy.from_yaml("config/brands.yaml"),
        auto_approve_score=0.85, state=state,
    )


def _snapshot(bd):
    seed = bd / LocalBdPublisher.SEED_REL
    manifest = bd / LocalBdPublisher.MANIFEST_REL
    pngs = sorted(p.name for p in (bd / LocalBdPublisher.ASSET_REL).glob("*"))
    with seed.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return pngs, rows, json.loads(manifest.read_text(encoding="utf-8"))["products"]


def test_second_run_does_not_search_download_or_process_again(tmp_path):
    bd = tmp_path / "bd"; bd.mkdir()
    state = StateStore(tmp_path / "state.db")
    first = _real_flow(bd, state).run()
    assert [r["status"] for r in first] == ["PUBLISHED_LOCAL"]
    assert (CountingSearch.calls, CountingDownloader.calls, CountingRemover.calls) == (1, 1, 1)
    before = _snapshot(bd)
    manifest_bytes = (bd / LocalBdPublisher.MANIFEST_REL).read_bytes()

    second = _real_flow(bd, state).run()
    assert [r["status"] for r in second] == ["ALREADY_PUBLISHED"]
    assert (CountingSearch.calls, CountingDownloader.calls, CountingRemover.calls) == (0, 0, 0)
    assert _snapshot(bd) == before
    assert len(before[0]) == 1 and len(before[1]) == 1 and len(before[2]) == 1
    assert (bd / LocalBdPublisher.MANIFEST_REL).read_bytes() == manifest_bytes  # nem reescrito
    record = state.get_image("minuano|limpador multiuso original")
    assert record["status"] == "PUBLISHED" and len(record["sha256"]) == 64 and record["published_at"]


def test_lost_state_db_is_rebuilt_from_files_without_reprocessing(tmp_path):
    bd = tmp_path / "bd"; bd.mkdir()
    _real_flow(bd, StateStore(tmp_path / "a.db")).run()
    fresh = StateStore(tmp_path / "b.db")
    assert [r["status"] for r in _real_flow(bd, fresh).run()] == ["ALREADY_PUBLISHED"]
    assert CountingSearch.calls == 0
    assert fresh.get_image("minuano|limpador multiuso original")["status"] == "PUBLISHED"


def test_partial_failure_is_reconciled_without_duplicates(tmp_path):
    bd = tmp_path / "bd"; bd.mkdir()
    state = StateStore(tmp_path / "state.db")
    _real_flow(bd, state).run()
    # Queda entre PNG/seed e manifest: o manifest (último a gravar) não existe.
    (bd / LocalBdPublisher.MANIFEST_REL).unlink()
    assert [r["status"] for r in _real_flow(bd, state).run()] == ["PUBLISHED_LOCAL"]
    pngs, rows, products = _snapshot(bd)
    assert len(pngs) == 1 and len(rows) == 1 and len(products) == 1
    assert [r["status"] for r in _real_flow(bd, state).run()] == ["ALREADY_PUBLISHED"]


def test_tampered_png_or_missing_seed_row_triggers_reprocess(tmp_path):
    bd = tmp_path / "bd"; bd.mkdir()
    state = StateStore(tmp_path / "state.db")
    _real_flow(bd, state).run()
    png = next((bd / LocalBdPublisher.ASSET_REL).glob("*.png"))
    png.write_bytes(b"corrompido")
    assert [r["status"] for r in _real_flow(bd, state).run()] == ["PUBLISHED_LOCAL"]
    (bd / LocalBdPublisher.SEED_REL).write_text("nome,marca,tipo_produto,descricao,foto_url\n", encoding="utf-8")
    assert [r["status"] for r in _real_flow(bd, state).run()] == ["PUBLISHED_LOCAL"]
    pngs, rows, products = _snapshot(bd)
    assert len(pngs) == 1 and len(rows) == 1 and len(products) == 1


def test_manifest_entry_of_other_product_with_same_id_is_not_clobbered(tmp_path):
    bd = tmp_path / "bd"; bd.mkdir()
    manifest = bd / LocalBdPublisher.MANIFEST_REL
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"schema_version": 1, "products": [
        {"product_id": 1, "brand": "Outra", "product": "Outro Produto", "file": "x.png"}]}), encoding="utf-8")
    _real_flow(bd, None).run()  # Repo() usa product id 1
    assert {p["product"] for p in _snapshot(bd)[2]} == {"Outro Produto", "Limpador Multiuso Original"}


def test_search_query_drops_box_multiplier_but_product_keeps_original_name(tmp_path):
    queries = []

    class Q(Search):
        def search(self, query):
            queries.append(query)
            return []

    class R:
        def list_products_without_image(self):
            return [ProductRecord(1, "Minuano", "Detergente Lava Louças Neutro 24x500mL")]

    ProductImageWorkflow(
        repository=R(), search=Q(), downloader=Downloader(), remover=Remover(), publisher=Publisher(tmp_path),
        brand_policy=BrandPolicy.from_yaml("config/brands.yaml"),
    ).run()
    assert queries == ['"Minuano" "Detergente Lava Louças Neutro 500mL" produto']
