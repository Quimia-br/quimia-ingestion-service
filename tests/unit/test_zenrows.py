import httpx
import pytest

from quimia_ingestion.core.exceptions import ConfigurationError, ExternalServiceError
from quimia_ingestion.integrations.zenrows import FallbackHttp, ZenRowsClient, ZenRowsImageSearch


def _zenrows(handler, **kwargs):
    return ZenRowsClient("key", transport=httpx.MockTransport(handler), backoff_seconds=0, **kwargs)


def test_requires_api_key():
    with pytest.raises(ConfigurationError):
        ZenRowsClient("")


def test_fallback_uses_direct_http_when_it_works():
    def handler(request):
        assert not str(request.url).startswith(ZenRowsClient.endpoint), "não deve gastar crédito"
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})

    with FallbackHttp(_zenrows(handler), transport=httpx.MockTransport(handler)) as http:
        assert http.get("https://flora.com.br/").text == "<html>ok</html>"


@pytest.mark.parametrize("blocked", [
    httpx.Response(403),
    httpx.Response(200, text="<title>Just a moment...</title>", headers={"content-type": "text/html"}),
])
def test_fallback_goes_to_zenrows_when_blocked(blocked):
    def handler(request):
        if str(request.url).startswith(ZenRowsClient.endpoint):
            assert request.url.params["url"] == "https://flora.com.br/"
            assert request.url.params["mode"] == "auto"
            return httpx.Response(200, text="via zenrows")
        return blocked

    with FallbackHttp(_zenrows(handler), transport=httpx.MockTransport(handler)) as http:
        assert http.get("https://flora.com.br/").text == "via zenrows"


def test_fallback_without_zenrows_returns_blocked_response():
    with FallbackHttp(None, transport=httpx.MockTransport(lambda r: httpx.Response(403))) as http:
        assert http.get("https://flora.com.br/").status_code == 403


def test_fallback_on_timeout():
    def handler(request):
        if str(request.url).startswith(ZenRowsClient.endpoint):
            return httpx.Response(200, text="via zenrows")
        raise httpx.ReadTimeout("lento", request=request)

    with FallbackHttp(_zenrows(handler), transport=httpx.MockTransport(handler)) as http:
        assert http.get("https://flora.com.br/").text == "via zenrows"


def test_retries_rate_limit_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, text="ok")

    assert _zenrows(handler).fetch("https://x.test").text == "ok"
    assert len(calls) == 3


def test_gives_up_after_max_attempts():
    with pytest.raises(ExternalServiceError, match="3 tentativas"):
        _zenrows(lambda r: httpx.Response(503)).fetch("https://x.test")


def test_no_credits_fails_fast():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(402, text="no credits")

    with pytest.raises(ExternalServiceError, match="créditos"):
        _zenrows(handler).fetch("https://x.test")
    assert len(calls) == 1


BING_IMAGES_HTML = """
<a aria-label="x" class="iusc" style="h" m="{&quot;purl&quot;:&quot;https://www.flora.com.br/produtos/minuano&quot;,&quot;murl&quot;:&quot;https://www.flora.com.br/img/minuano-multiuso.png?v=2&quot;,&quot;turl&quot;:&quot;https://ts4.mm.bing.net/th?id=1&quot;,&quot;t&quot;:&quot;Minuano Limpador Multiuso &amp; Lavanda&quot;}" href="/images/search?view=detailV2&amp;exph=1200&amp;expw=800">
<a class="iusc" m="{&quot;purl&quot;:&quot;https://loja.test/p/omo&quot;,&quot;murl&quot;:&quot;https://loja.test/omo.jpg&quot;,&quot;t&quot;:&quot;OMO&quot;}" href="/images/search?view=detailV2">
<a class="iusc" m="{&quot;purl&quot;:&quot;https://loja.test/p/omo&quot;,&quot;murl&quot;:&quot;https://loja.test/omo.jpg&quot;,&quot;t&quot;:&quot;dup&quot;}" href="/x">
<a class="iusc" m="quebrado" href="/x">
"""


def test_image_search_parses_bing_originals():
    def handler(request):
        target = request.url.params["url"]
        assert target.startswith("https://www.bing.com/images/search") and "cc=br" in target
        assert request.url.params["mode"] == "auto"
        return httpx.Response(200, text=BING_IMAGES_HTML)

    results = ZenRowsImageSearch(_zenrows(handler), max_results=20).search("Minuano Multiuso")
    assert len(results) == 2
    first = results[0]
    assert first.original_url == "https://www.flora.com.br/img/minuano-multiuso.png?v=2"
    assert first.page_url == "https://www.flora.com.br/produtos/minuano"
    assert first.source == "flora.com.br"
    assert first.title == "Minuano Limpador Multiuso & Lavanda"
    assert (first.width, first.height) == (800, 1200)
    assert (results[1].width, results[1].height) == (None, None)


def test_image_search_raises_on_target_failure():
    with pytest.raises(ExternalServiceError):
        ZenRowsImageSearch(_zenrows(lambda r: httpx.Response(422, text="RESP001"))).search("x")
