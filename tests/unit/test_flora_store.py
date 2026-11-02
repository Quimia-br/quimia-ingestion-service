import httpx

from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.images.matcher import rank_candidates
from quimia_ingestion.integrations.flora_store import STORE, ChainedImageSearch, FloraStoreImageSearch
from quimia_ingestion.integrations.zenrows import FallbackHttp

POLICY = BrandPolicy.from_yaml("config/brands.yaml")
SLUGS = [
    "detergente-lava-loucas-minuano-neutro-500ml",
    "detergente-lava-loucas-minuano-coco-500ml",
    "amaciante-minuano-concentrado-classico-500ml",
    "multiuso-minuano-500ml",
    "multiuso-citrico-minuano-500ml",
    "kit-com-3-detergente-lava-loucas-minuano-neutro-500ml-1abc",
]
IMG = "http://acdn-us.mitiendanube.com/stores/001/289/535/products/400001_1-abc-640-0.webp"


def _page(slug: str, name: str) -> str:
    return (
        f'<meta property="og:title" content="{name}" />'
        f'<meta property="og:image" content="{IMG}" />'
        f'<meta property="og:url" content="{STORE}/produtos/{slug}/" />'
    )


def _search(max_results=5):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/sitemap.xml"):
            locs = "".join(f"<url><loc>{STORE}/produtos/{s}/</loc></url>" for s in SLUGS)
            return httpx.Response(200, text=f"<urlset>{locs}</urlset>")
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug in SLUGS:
            return httpx.Response(200, text=_page(slug, slug.replace("-", " ").title()))
        return httpx.Response(404)
    return FloraStoreImageSearch(FallbackHttp(transport=httpx.MockTransport(handler)), max_results=max_results)


QUERY = '"Minuano" "Detergente Lava Louças Neutro 500mL" produto'


def test_returns_own_product_with_larger_image_and_store_page():
    first = _search().search(QUERY)[0]
    assert first.page_url == f"{STORE}/produtos/detergente-lava-loucas-minuano-neutro-500ml/"
    assert first.title == "Detergente Lava Loucas Minuano Neutro 500Ml"
    assert first.original_url.startswith("https://") and first.original_url.endswith("-1024-1024.webp") and first.width == 1024


def test_exact_name_on_official_store_reaches_auto_approval_but_variant_does_not():
    brand = POLICY.resolve("Minuano")
    exact = rank_candidates(_search().search(QUERY), brand=brand, product_name="Detergente Lava Louças Neutro 500mL")
    assert exact[0].page_url.endswith("minuano-neutro-500ml/") and exact[0].score >= 0.90
    assert all(c.score < 0.90 for c in exact[1:])  # coco, kit: nunca auto-aprovados
    other = rank_candidates(_search().search(QUERY), brand=brand, product_name="Detergente Lava Louças Marine 500mL")
    assert all(c.score < 0.90 for c in other)


def test_prefers_slug_without_extra_words_on_ties():
    urls = [c.page_url for c in _search().search('"Minuano" "Multiuso 500mL" produto')]
    assert urls[0].endswith("/multiuso-minuano-500ml/")


def test_unrelated_query_returns_nothing_and_brand_without_store_products_is_silent():
    assert _search().search('"OMO" "Lava Roupas Líquido 3L" produto') == []


def test_chain_concatenates_sources_in_order():
    class Fake:
        def __init__(self, items): self.items = items
        def search(self, query): return self.items
    assert ChainedImageSearch(Fake([1]), Fake([2, 3])).search("x") == [1, 2, 3]


def test_store_domain_counts_as_official_only_for_images():
    rule = POLICY.resolve("Minuano")
    assert "compraflora.com.br" in rule.image_domains
    assert "compraflora.com.br" not in rule.official_domains  # a busca de FDS não passa a consultá-la
