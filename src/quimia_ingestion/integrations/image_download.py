from __future__ import annotations

import httpx

from quimia_ingestion.core.exceptions import ExternalServiceError


class ImageDownloader:
    def __init__(self, max_bytes: int = 15 * 1024 * 1024, transport=None):
        self.max_bytes = max_bytes
        self.transport = transport

    def download(self, url: str) -> bytes:
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True, transport=self.transport) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError(f"falha ao baixar imagem: {exc}") from exc
        content = response.content
        if len(content) > self.max_bytes:
            raise ExternalServiceError("imagem excede limite local de 15 MB")
        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.startswith("image/"):
            raise ExternalServiceError(f"URL não retornou imagem: {content_type}")
        return content
