import httpx
import pytest

from quimia_ingestion.core.exceptions import ContractError, ExternalServiceError
from quimia_ingestion.integrations.extractor import HttpExtractorClient


def valid_payload(status="processado", pendencias=None, mensagem=None):
    return {
        "status": status,
        "mensagem": mensagem,
        "secoes": {
            "03": {"encontrada": True, "compostos": []},
            "04": {"encontrada": True, "primeiros_socorros": []},
            "10": {"encontrada": True, "situacao": "nao_especificadas", "incompatibilidades": []},
        },
        "pendencias": pendencias or [],
    }


def test_extractor_sends_bearer_and_arquivo_field():
    def handler(request: httpx.Request):
        assert request.headers["authorization"] == "Bearer abc"
        body = request.read()
        assert b'name="arquivo"' in body
        assert b"fds.pdf" in body
        return httpx.Response(200, json=valid_payload())

    client = HttpExtractorClient("http://extractor.test", "abc", transport=httpx.MockTransport(handler))
    result = client.extract(b"%PDF-1.4", "fds.pdf")
    assert result.status == "processado"


def test_extractor_rejects_missing_section():
    payload = valid_payload()
    del payload["secoes"]["10"]
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    client = HttpExtractorClient("http://extractor.test", "abc", transport=transport)
    with pytest.raises(ContractError):
        client.extract(b"%PDF-1.4")


def test_extractor_http_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"detail": "bad token"}))
    client = HttpExtractorClient("http://extractor.test", "abc", transport=transport)
    with pytest.raises(ExternalServiceError):
        client.extract(b"%PDF-1.4")
