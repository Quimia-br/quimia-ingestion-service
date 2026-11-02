from __future__ import annotations

from pathlib import Path

from quimia_ingestion.discovery.composite import CompositeSDSProvider
from quimia_ingestion.integrations.configured_sds import ConfiguredOfficialSDSProvider
from quimia_ingestion.integrations.manual_inbox import ManualInboxProvider
from quimia_ingestion.integrations.search_sds import WebSearchSDSProvider
from quimia_ingestion.integrations.sitemap_sds import FloraSDSProvider
from quimia_ingestion.integrations.unilever_sds import UnileverSDSProvider
from quimia_ingestion.integrations.zenrows import ZenRowsClient


def build_public_provider(
    *,
    brand_policy,
    zenrows: ZenRowsClient | None = None,
    manual_inbox: str | Path = "./data/manual_inbox",
    official_catalog: str | Path = "./config/official_sds_catalog.yaml",
    transport=None,
):
    return CompositeSDSProvider([
        ConfiguredOfficialSDSProvider(official_catalog, brand_policy, zenrows=zenrows, transport=transport),
        UnileverSDSProvider(zenrows=zenrows, transport=transport),
        FloraSDSProvider(brand_policy, zenrows=zenrows, transport=transport),
        # Sem provider SC Johnson/Mr. Músculo (verificado em 2026-11-01): scjohnson.com.br não completa conexão
        # TCP (timeout direto e via ZenRows) e scjohnson.com/pt-br e mrmuscleclean.com não publicam FDS.
        # Mr. Músculo entra pela manual inbox.
        WebSearchSDSProvider(zenrows, brand_policy, transport=transport),
        ManualInboxProvider(manual_inbox, brand_policy),
    ])
