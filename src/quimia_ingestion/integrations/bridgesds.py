from __future__ import annotations

from quimia_ingestion.core.exceptions import ConfigurationError


class BridgeSDSProvider:
    """Placeholder explícito até termos o contrato oficial do BridgeSDS."""

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key

    def documents(self):
        raise ConfigurationError(
            "BridgeSDS ainda não foi implementado: faltam base URL, autenticação e contrato oficial de busca/download."
        )
