from __future__ import annotations

from html import unescape
import re

from quimia_ingestion.domain.models import ImageCandidate
from quimia_ingestion.images.matcher import _tokens

STORE = "https://compraflora.com.br"
# A CDN da Nuvemshop serve a mesma foto em qualquer tamanho: o og:image traz 640 px, pedimos 1024.
_SIZE_SUFFIX = re.compile(r"-\d+-\d+(\.(?:webp|jpe?g|png))$", re.I)
_PRODUCT_URL = re.compile(rf"<loc>({re.escape(STORE)}/produtos/[^<]+?)/?</loc>")
MIN_OVERLAP = 0.6


class FloraStoreImageSearch:
    """Fotos da loja oficial da Flora (Minuano, Assim, Brisa), pelo sitemap e pelas tags Open Graph de cada produto
    (o JSON-LD da página só traz os produtos relacionados, não o próprio).

    Só escolhe as páginas mais parecidas com a busca; quem decide o score é o matcher.
    """

    def __init__(self, http, *, max_results: int = 5):
        self.http = http
        self.max_results = max_results
        self._urls: list[str] | None = None

    def _product_urls(self) -> list[str]:
        if self._urls is None:  # sitemap tem ~750 produtos (600 KB): uma leitura por instância
            response = self.http.get(f"{STORE}/sitemap.xml")
            response.raise_for_status()
            self._urls = _PRODUCT_URL.findall(response.text)
        return self._urls

    def search(self, query: str) -> list[ImageCandidate]:
        wanted = _tokens(query) - {"produto"}
        if not wanted:
            return []
        scored = []
        for url in self._product_urls():
            slug = _tokens(url.rsplit("/", 1)[-1].replace("-", " "))
            overlap = len(wanted & slug) / len(wanted)
            if overlap >= MIN_OVERLAP:
                # Empate: o slug com menos palavras sobrando ("Multiuso" antes de "Multiuso Cítrico").
                scored.append((-overlap, len(slug - wanted), url))
        candidates = []
        for *_, url in sorted(scored)[: self.max_results]:
            candidate = self._candidate(url)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _candidate(self, url: str) -> ImageCandidate | None:
        response = self.http.get(url + "/")
        if response.status_code != 200:
            return None
        og = {k: unescape(v) for k, v in re.findall(r'<meta property="og:(title|image|url)" content="([^"]*)"', response.text)}
        if not og.get("image") or not og.get("title") or not og.get("url", "").startswith(url):
            return None
        image = og["image"].replace("http://", "https://", 1)
        return ImageCandidate(
            original_url=_SIZE_SUFFIX.sub(r"-1024-1024\1", image),
            page_url=url + "/",
            source="compraflora.com.br",
            title=og["title"],
            width=1024,
            height=1024,
            is_product=True,
        )


class ChainedImageSearch:
    """Junta as fontes: a oficial primeiro, depois a busca aberta. O matcher reordena pelo score."""

    def __init__(self, *sources):
        self.sources = sources

    def search(self, query: str) -> list[ImageCandidate]:
        return [candidate for source in self.sources for candidate in source.search(query)]
