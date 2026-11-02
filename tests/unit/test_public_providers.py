from pathlib import Path
import json

import httpx

from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.integrations.manual_inbox import ManualInboxProvider
from quimia_ingestion.integrations.search_sds import WebSearchSDSProvider
from quimia_ingestion.integrations.sitemap_sds import FloraSDSProvider
from quimia_ingestion.integrations.unilever_sds import UnileverSDSProvider
from quimia_ingestion.integrations.zenrows import ZenRowsClient


POLICY = BrandPolicy.from_yaml("config/brands.yaml")


def test_unilever_provider_reads_omo_catalog_and_downloads_pdf():
    html = """
    <html><body><ul>
      <li><button>OMO LAVA ROUPAS TESTE 5 L</button>
          <a href="https://cdn.test/omo.pdf">FDS - OMO LAVA ROUPAS TESTE</a></li>
      <li><button>CIF TESTE</button><a href="https://cdn.test/cif.pdf">FDS - CIF TESTE</a></li>
    </ul></body></html>
    """
    def handler(request: httpx.Request):
        if str(request.url) == UnileverSDSProvider.catalog_url:
            return httpx.Response(200, text=html)
        if str(request.url) == "https://cdn.test/omo.pdf":
            return httpx.Response(200, content=b"%PDF-1.7 omo")
        raise AssertionError(str(request.url))

    docs = list(UnileverSDSProvider(transport=httpx.MockTransport(handler)).documents())
    assert len(docs) == 1
    assert docs[0].brand == "OMO"
    assert docs[0].product_name == "OMO LAVA ROUPAS TESTE 5 L"
    assert docs[0].provider == "unilever"
    assert docs[0].source_score == 100


def test_flora_provider_uses_sitemap_and_filters_allowed_brand():
    sitemap = """<?xml version='1.0' encoding='UTF-8'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>https://flora.com.br/files/FISPQ_MINUANO_MULTIUSO.pdf</loc></url>
      <url><loc>https://flora.com.br/files/FISPQ_OUTRA_MARCA.pdf</loc></url>
    </urlset>"""
    def handler(request: httpx.Request):
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="Sitemap: https://flora.com.br/sitemap.xml")
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=sitemap)
        if url.endswith("/wp-sitemap.xml") or url.endswith("/sitemap_index.xml"):
            return httpx.Response(404)
        if url.endswith("FISPQ_MINUANO_MULTIUSO.pdf"):
            return httpx.Response(200, content=b"%PDF-1.7 minuano", headers={"content-type": "application/pdf"})
        raise AssertionError(url)

    provider = FloraSDSProvider(POLICY, transport=httpx.MockTransport(handler))
    docs = list(provider.documents())
    assert len(docs) == 1
    assert docs[0].brand == "Minuano"
    assert docs[0].provider == "flora"


def test_web_search_sds_provider_scores_official_domain_higher():
    ddg = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fflora.com.br%2Fa.pdf&amp;rut=1">FISPQ <b>Minuano</b> Multiuso</a>
    <a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fflora.com.br%2Fa.pdf&amp;rut=1">flora.com.br</a>
    <a href="https://docs.example/b.pdf">FISPQ Minuano Multiuso</a>
    <a href="https://duckduckgo.com/x.pdf">interno</a>
    """
    def handler(request: httpx.Request):
        url = str(request.url)
        if url.startswith(ZenRowsClient.endpoint):
            assert "html.duckduckgo.com" in request.url.params["url"]
            return httpx.Response(200, text=ddg)
        if url in {"https://flora.com.br/a.pdf", "https://docs.example/b.pdf"}:
            return httpx.Response(200, content=b"%PDF-1.7 test")
        raise AssertionError(url)

    transport = httpx.MockTransport(handler)
    zenrows = ZenRowsClient("key", transport=transport)
    provider = WebSearchSDSProvider(zenrows, POLICY, transport=transport, max_results_per_brand=2)
    # Limita a política à primeira marca para não executar cinco buscas no teste.
    provider.brand_policy = BrandPolicy({"minuano": POLICY.rules["minuano"]})
    docs = list(provider.documents())
    assert [d.source_score for d in docs] == [90, 70]
    assert docs[0].product_name == "Minuano Multiuso"


def test_web_search_sds_provider_is_noop_without_zenrows():
    assert list(WebSearchSDSProvider(None, POLICY).documents()) == []


def test_manual_inbox_infers_brand_and_supports_sidecar(tmp_path):
    inbox = tmp_path / "manual"
    inbox.mkdir()
    pdf = inbox / "FDS_Minuano_Limpador_Multiuso.pdf"
    pdf.write_bytes(b"%PDF-1.7 manual")
    docs = list(ManualInboxProvider(inbox, POLICY).documents())
    assert len(docs) == 1
    assert docs[0].brand == "Minuano"
    assert "Limpador Multiuso" in docs[0].product_name
    assert docs[0].source_score == 95

    pdf2 = inbox / "x.pdf"
    pdf2.write_bytes(b"%PDF-1.7 manual 2")
    Path(str(pdf2) + ".json").write_text(json.dumps({
        "brand": "OMO", "product_name": "OMO Teste", "version": "2"
    }), encoding="utf-8")
    docs = list(ManualInboxProvider(inbox, POLICY).documents())
    assert any(d.product_name == "OMO Teste" and d.version == "2" for d in docs)


def test_configured_official_catalog_requires_official_domain(tmp_path):
    from quimia_ingestion.integrations.configured_sds import ConfiguredOfficialSDSProvider
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text("""
documents:
  - brand: Minuano
    product_name: Produto Bom
    source_url: https://flora.com.br/produto.pdf
  - brand: Minuano
    product_name: Produto Ruim
    source_url: https://example.com/produto.pdf
""", encoding="utf-8")

    def handler(request: httpx.Request):
        if str(request.url) == "https://flora.com.br/produto.pdf":
            return httpx.Response(200, content=b"%PDF-1.7 official")
        raise AssertionError(str(request.url))

    docs = list(ConfiguredOfficialSDSProvider(catalog, POLICY, transport=httpx.MockTransport(handler)).documents())
    assert len(docs) == 1
    assert docs[0].product_name == "Produto Bom"
    assert docs[0].source_score == 100


def test_default_chain_has_no_dead_sc_johnson_provider():
    from quimia_ingestion.discovery.factory import build_public_provider
    names = [type(p).__name__ for p in build_public_provider(brand_policy=POLICY).providers]
    assert "SCJohnsonSDSProvider" not in names
    assert names[-1] == "ManualInboxProvider"
    assert "sc_johnson" not in POLICY.resolve("Mr. Músculo").providers


def test_mr_musculo_enters_through_manual_inbox_with_alias_variants(tmp_path):
    for name in ("FDS_Mr_Musculo_Multiuso.pdf", "FDS Mr. Músculo Cozinha.pdf", "fispq-mr-muscle-banheiro.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.7 " + name.encode())
    docs = list(ManualInboxProvider(tmp_path, POLICY).documents())
    assert len(docs) == 3
    assert {d.brand for d in docs} == {"Mr. Músculo"}
    assert {d.provider for d in docs} == {"manual"}


def test_web_search_provider_prefers_pdf_header_name_over_snippet_title(monkeypatch):
    from quimia_ingestion.integrations import search_sds
    ddg = '<a href="https://flora.com.br/a.pdf">Brisa BR Esta informação está baseada em nosso conhecimento atual</a>'

    def handler(request: httpx.Request):
        if str(request.url).startswith(ZenRowsClient.endpoint):
            return httpx.Response(200, text=ddg)
        return httpx.Response(200, content=b"%PDF-1.7 test")

    transport = httpx.MockTransport(handler)
    provider = WebSearchSDSProvider(ZenRowsClient("key", transport=transport), POLICY, transport=transport)
    provider.brand_policy = BrandPolicy({"brisa": POLICY.rules["brisa"]})
    monkeypatch.setattr(search_sds, "product_name_from_pdf", lambda content: "DETERGENTE LAVA LOUÇAS BRISA NEUTRO 24X500ML")
    assert [d.product_name for d in provider.documents()] == ["DETERGENTE LAVA LOUÇAS BRISA NEUTRO 24X500ML"]
    monkeypatch.setattr(search_sds, "product_name_from_pdf", lambda content: None)
    assert "conhecimento" in next(iter(provider.documents())).product_name  # sem cabeçalho: mantém o fallback
