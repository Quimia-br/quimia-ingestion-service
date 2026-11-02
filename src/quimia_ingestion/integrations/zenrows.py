from __future__ import annotations

import html
import json
import re
import time
from urllib.parse import quote_plus, urlparse

import httpx

from quimia_ingestion.core.exceptions import ConfigurationError, ExternalServiceError
from quimia_ingestion.domain.models import ImageCandidate

_BLOCKED_STATUS = {403, 429, 503}
_BLOCK_MARKERS = (
    "cf-chl",
    "just a moment...",
    "attention required! | cloudflare",
    "enable javascript",
    "habilite o javascript",
    "captcha",
)


class ZenRowsClient:
    """Universal Scraper API. Cobra créditos: usar só quando HTTP direto falhar."""

    endpoint = "https://api.zenrows.com/v1/"

    def __init__(self, api_key: str, *, timeout: float = 180.0, max_attempts: int = 3, backoff_seconds: float = 2.0, transport=None):
        if not api_key:
            raise ConfigurationError("ZENROWS_API_KEY não configurada")
        self.api_key = api_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.transport = transport

    def fetch(self, url: str, **params) -> httpx.Response:
        """Retorna a resposta (2xx ou erro do alvo, ex. 422). Chave/créditos inválidos levantam erro."""
        # mode=auto: ZenRows escala para JS/proxy premium só se preciso e cobra só o que funcionou.
        # A API recusa mode=auto junto com js_render/premium_proxy explícitos (REQS004).
        query = {"apikey": self.api_key, "url": url, **(params or {"mode": "auto"})}
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            if attempt:
                time.sleep(self.backoff_seconds * 2 ** (attempt - 1))
            try:
                with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                    response = client.get(self.endpoint, params=query)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            if response.status_code in (401, 402):
                raise ExternalServiceError(f"ZenRows: chave inválida ou créditos esgotados ({response.status_code}): {response.text[:200]}")
            if response.status_code == 429 or response.status_code >= 500:
                last_error = ExternalServiceError(f"ZenRows {response.status_code}: {response.text[:200]}")
                continue
            return response
        raise ExternalServiceError(f"ZenRows falhou após {self.max_attempts} tentativas: {last_error}")


def looks_blocked(response: httpx.Response) -> bool:
    if response.status_code in _BLOCKED_STATUS:
        return True
    if "text/html" not in response.headers.get("content-type", ""):
        return False
    head = response.text[:5000].lower()
    return any(marker in head for marker in _BLOCK_MARKERS)


class FallbackHttp:
    """Cliente HTTP dos providers: tenta direto; usa ZenRows só se bloqueado/timeout."""

    def __init__(self, zenrows: ZenRowsClient | None = None, *, timeout: float = 30.0, transport=None):
        self.zenrows = zenrows
        self._client = httpx.Client(timeout=timeout, follow_redirects=True, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._client.close()

    def get(self, url: str) -> httpx.Response:
        try:
            response = self._client.get(url)
        except httpx.TimeoutException:
            if not self.zenrows:
                raise
            return self.zenrows.fetch(url)
        if self.zenrows and looks_blocked(response):
            return self.zenrows.fetch(url)
        return response


# Cada resultado do Bing Images é um <a class="iusc" m="{json}" href="...expw=..&exph=..">,
# com murl (imagem original), purl (página de origem) e t (título).
# Google Images via ZenRows foi testado e descartado: exige js_render+premium_proxy (25x o custo) e
# mesmo assim devolveu RESP001.
# ponytail: parse do HTML do Bing; se o formato mudar, a busca volta vazia (teste de fixture acusa).
_BING_ITEM = re.compile(r'<a [^>]*class="iusc"[^>]*>')
_ATTR_M = re.compile(r'\sm="([^"]+)"')
_DIM = re.compile(r'exp([wh])=(\d+)')


class ZenRowsImageSearch:
    """Bing Images via ZenRows; devolve URL da imagem original, não o thumbnail."""

    def __init__(self, zenrows: ZenRowsClient, *, country: str = "br", language: str = "pt-br", max_results: int = 20):
        self.zenrows = zenrows
        self.country = country
        self.language = language
        self.max_results = max_results

    def search(self, query: str) -> list[ImageCandidate]:
        bing_url = (
            f"https://www.bing.com/images/search?q={quote_plus(query)}"
            f"&cc={self.country}&setlang={self.language}&qft=+filterui:imagesize-large"
        )
        response = self.zenrows.fetch(bing_url)
        if response.status_code >= 400:
            raise ExternalServiceError(f"ZenRows/Bing Images {response.status_code}: {response.text[:200]}")
        return self.parse(response.text)[: self.max_results]

    @staticmethod
    def parse(page: str) -> list[ImageCandidate]:
        result: list[ImageCandidate] = []
        seen: set[str] = set()
        for tag in _BING_ITEM.findall(page):
            m = _ATTR_M.search(tag)
            if not m:
                continue
            try:
                meta = json.loads(html.unescape(m.group(1)))
            except ValueError:
                continue
            original, page_url = meta.get("murl") or "", meta.get("purl") or ""
            if not original.startswith("http") or not page_url.startswith("http") or original in seen:
                continue
            seen.add(original)
            dims = dict(_DIM.findall(tag))
            result.append(
                ImageCandidate(
                    original_url=original,
                    page_url=page_url,
                    source=(urlparse(page_url).hostname or "").removeprefix("www."),
                    title=meta.get("t") or "",
                    width=int(dims["w"]) if "w" in dims else None,
                    height=int(dims["h"]) if "h" in dims else None,
                )
            )
        return result
