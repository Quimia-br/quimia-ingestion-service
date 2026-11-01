from __future__ import annotations

import json
from pathlib import Path
import typer

from quimia_ingestion.core.config import Settings
from quimia_ingestion.discovery.factory import build_public_provider
from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.images.background import RembgBackgroundRemover
from quimia_ingestion.integrations.image_download import ImageDownloader
from quimia_ingestion.integrations.local_pdf import LocalPDFProvider
from quimia_ingestion.integrations.extractor import HttpExtractorClient
from quimia_ingestion.core.exceptions import ConfigurationError
from quimia_ingestion.integrations.postgres import PostgresQuimiaRepository, non_local_db_hosts
from quimia_ingestion.integrations.flora_store import ChainedImageSearch, FloraStoreImageSearch
from quimia_ingestion.integrations.zenrows import FallbackHttp, ZenRowsClient, ZenRowsImageSearch
from quimia_ingestion.publishers.local_bd import LocalBdPublisher
from quimia_ingestion.state.sqlite import StateStore
from quimia_ingestion.storage.documents import DocumentStorage
from quimia_ingestion.validation.pdf import SDSStructuralValidator
from quimia_ingestion.workflows.discover_fds import PublicDiscoveryExportWorkflow
from quimia_ingestion.workflows.ingest_fds import FDSIngestionWorkflow
from quimia_ingestion.workflows.enrich_images import ProductImageWorkflow

app = typer.Typer(no_args_is_help=True, help="Quimia ingestion service (local-first; sem escrita remota no GitHub).")


def _brand_policy(path: Path) -> BrandPolicy:
    return BrandPolicy.from_yaml(path)


def _repository(settings: Settings):
    try:
        return PostgresQuimiaRepository(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            sslmode=settings.db_sslmode,
        )
    except ConfigurationError as exc:
        typer.echo(f"ERRO: {exc}", err=True)
        raise typer.Exit(2) from exc


def _zenrows(settings: Settings) -> ZenRowsClient | None:
    return ZenRowsClient(settings.zenrows_api_key) if settings.zenrows_api_key else None


def _ingest_local(manifest: Path, brands: Path, settings: Settings):
    workflow = FDSIngestionWorkflow(
        provider=LocalPDFProvider(manifest),
        extractor=HttpExtractorClient(settings.extractor_api_url, settings.extractor_api_token, settings.extractor_timeout_seconds),
        repository=_repository(settings),
        state=StateStore(settings.state_db_path),
        storage=DocumentStorage(settings.document_storage_path),
        brand_policy=_brand_policy(brands),
        # Score de fonte (mesmo oficial) nunca basta: PDF e produto sempre passam pela validação estrutural.
        validator=SDSStructuralValidator(),
        min_auto_source_score=settings.fds_min_auto_source_score,
    )
    return workflow.run()


def _enrich_images(repo_path: Path, brands: Path, settings: Settings):
    zenrows = ZenRowsClient(settings.zenrows_api_key)
    workflow = ProductImageWorkflow(
        repository=_repository(settings),
        # Loja oficial da Flora primeiro (única fonte que alcança o limiar de auto-aprovação), depois o Bing.
        search=ChainedImageSearch(
            FloraStoreImageSearch(FallbackHttp(zenrows)),
            ZenRowsImageSearch(
                zenrows,
                country=settings.image_search_country,
                language=settings.image_search_language,
                max_results=settings.image_search_max_results,
            ),
        ),
        downloader=ImageDownloader(),
        remover=RembgBackgroundRemover(),
        publisher=LocalBdPublisher(repo_path),
        brand_policy=_brand_policy(brands),
        canvas_size=settings.image_canvas_size,
        min_size=settings.image_min_size,
        outer_frame_ratio=settings.image_outer_frame_ratio,
        required_outer_transparency=settings.image_outer_frame_transparent_ratio,
        auto_approve_score=settings.image_auto_approve_score,
        state=StateStore(settings.state_db_path),
    )
    return workflow.run()


@app.command("discover-public")
def discover_public(
    output: Path = typer.Option(Path("data/discovered"), "--output"),
    brands: Path = typer.Option(Path("config/brands.yaml"), exists=True),
):
    """Descobre FDS públicas e gera PDFs/manifest LOCALMENTE; não escreve no banco."""
    settings = Settings()
    policy = _brand_policy(brands)
    provider = build_public_provider(
        brand_policy=policy,
        zenrows=_zenrows(settings),
        manual_inbox=settings.manual_inbox_path,
        official_catalog=settings.official_sds_catalog_path,
    )
    result = PublicDiscoveryExportWorkflow(
        provider=provider,
        output_dir=output,
        validator=SDSStructuralValidator(),
        min_auto_source_score=settings.fds_min_auto_source_score,
    ).run()
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("ingest-local")
def ingest_local(
    manifest: Path = typer.Argument(..., exists=True, readable=True),
    brands: Path = typer.Option(Path("config/brands.yaml"), exists=True),
    validate_pdf: bool = typer.Option(True, "--validate-pdf", hidden=True, help="Sem efeito: a validação é sempre aplicada."),
):
    """Ingere PDFs locais descritos num manifest."""
    report = _ingest_local(manifest, brands, Settings())
    typer.echo(json.dumps([item.__dict__ | {"pdf_path": str(item.pdf_path) if item.pdf_path else None} for item in report.outcomes], ensure_ascii=False, indent=2))


@app.command("ingest-public")
def ingest_public(
    brands: Path = typer.Option(Path("config/brands.yaml"), exists=True),
    write_db: bool = typer.Option(False, "--write-db", help="Confirma explicitamente escrita no PostgreSQL configurado."),
):
    """Descobre e ingere FDS públicas. Exige --write-db para impedir escrita acidental."""
    if not write_db:
        raise typer.BadParameter("ingest-public exige --write-db; use discover-public para revisar sem escrever no banco")
    settings = Settings()
    policy = _brand_policy(brands)
    provider = build_public_provider(
        brand_policy=policy,
        zenrows=_zenrows(settings),
        manual_inbox=settings.manual_inbox_path,
        official_catalog=settings.official_sds_catalog_path,
    )
    report = FDSIngestionWorkflow(
        provider=provider,
        extractor=HttpExtractorClient(settings.extractor_api_url, settings.extractor_api_token, settings.extractor_timeout_seconds),
        repository=_repository(settings),
        state=StateStore(settings.state_db_path),
        storage=DocumentStorage(settings.document_storage_path),
        brand_policy=policy,
        validator=SDSStructuralValidator(),
        min_auto_source_score=settings.fds_min_auto_source_score,
    ).run()
    typer.echo(json.dumps([item.__dict__ | {"pdf_path": str(item.pdf_path) if item.pdf_path else None} for item in report.outcomes], ensure_ascii=False, indent=2))


@app.command("enrich-images")
def enrich_images(
    bd_repo: Path = typer.Option(..., "--bd-repo", exists=True, file_okay=False, resolve_path=True),
    brands: Path = typer.Option(Path("config/brands.yaml"), exists=True),
):
    """Busca/processa imagens e altera somente o checkout LOCAL informado em --bd-repo."""
    result = _enrich_images(bd_repo, brands, Settings())
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("run-all-local")
def run_all_local(
    manifest: Path = typer.Argument(..., exists=True, readable=True),
    bd_repo: Path = typer.Option(..., "--bd-repo", exists=True, file_okay=False, resolve_path=True),
    brands: Path = typer.Option(Path("config/brands.yaml"), exists=True),
):
    """Roda ingestão de manifest local e enriquecimento; não faz push ou PR."""
    settings = Settings()
    ingestion = _ingest_local(manifest, brands, settings)
    images = _enrich_images(bd_repo, brands, settings)
    typer.echo(json.dumps({
        "ingestion": [item.__dict__ | {"pdf_path": str(item.pdf_path) if item.pdf_path else None} for item in ingestion.outcomes],
        "images": images,
    }, ensure_ascii=False, indent=2))


@app.command("status")
def status():
    """Resumo do estado operacional local."""
    typer.echo(json.dumps(StateStore(Settings().state_db_path).summary(), ensure_ascii=False, indent=2))


@app.command("bridge-status")
def bridge_status():
    """BridgeSDS é opcional nesta versão; só informa configuração."""
    settings = Settings()
    ready = bool(settings.bridgesds_api_url and settings.bridgesds_api_key)
    typer.echo("optional-configured" if ready else "optional-not-configured")


@app.command("safety-check")
def safety_check():
    """Mostra o destino efetivo do banco (sem credenciais) e falha se não for local."""
    settings = Settings()
    typer.echo(f"banco: host={settings.db_host or '<ausente>'} port={settings.db_port} dbname={settings.db_name or '<ausente>'}")
    blocked = non_local_db_hosts(settings.db_host)
    if blocked:
        typer.echo(f"REMOTO/BLOQUEADO: {', '.join(blocked)}. Escrita no banco desabilitada; use localhost.")
        raise typer.Exit(1)
    typer.echo("LOCAL_ONLY: destino local; nenhum push/PR/API de escrita do GitHub está implementado nesta versão.")


if __name__ == "__main__":
    app()
