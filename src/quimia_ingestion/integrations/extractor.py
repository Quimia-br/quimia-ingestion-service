from __future__ import annotations

import httpx
from pydantic import ValidationError

from quimia_ingestion.core.exceptions import ContractError, ExternalServiceError, ExtractorHTTPError
from quimia_ingestion.domain.models import ExtractorResponse


class HttpExtractorClient:
    def __init__(self, base_url: str, token: str, timeout_seconds: float = 60.0, transport=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def extract(self, pdf: bytes, filename: str = "fds.pdf") -> ExtractorResponse:
        headers = {"Authorization": f"Bearer {self.token}"}
        files = {"arquivo": (filename, pdf, "application/pdf")}
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(f"{self.base_url}/extracoes", headers=headers, files=files)
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"falha ao chamar extractor: {exc}") from exc

        if response.status_code != 200:
            raise ExtractorHTTPError(response.status_code, response.text[:500])
        try:
            return ExtractorResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ContractError(f"resposta do extractor fora do contrato: {exc}") from exc
