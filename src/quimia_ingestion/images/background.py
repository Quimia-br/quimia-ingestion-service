from __future__ import annotations

from quimia_ingestion.core.exceptions import ConfigurationError


class RembgBackgroundRemover:
    def __init__(self, model: str = "u2net"):
        self.model = model
        self._session = None

    def remove(self, image_bytes: bytes) -> bytes:
        try:
            from rembg import new_session, remove
        except ImportError as exc:
            raise ConfigurationError('rembg não instalado; use pip install ".[images]"') from exc
        # Uma sessão por instância: remove() sem sessão recarrega o modelo a cada chamada
        # (medido em 2026-11-01: ~52 s por chamada contra ~0,8 s reaproveitando a sessão).
        if self._session is None:
            self._session = new_session(self.model)
        return remove(image_bytes, session=self._session)
