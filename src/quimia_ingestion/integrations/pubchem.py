from __future__ import annotations


class PubChemEnricher:
    """Ponto de extensão para enriquecimento químico futuro.

    A descoberta de FDS continua baseada em produto/marca. PubChem deve ser usado depois,
    a partir de CAS/nome de substância extraídos da seção 3. Não é acionado na v0.2.
    """

    def enrich(self, *, cas: str | None = None, substance_name: str | None = None) -> dict:
        raise NotImplementedError("PubChem ainda não habilitado na v0.2")
