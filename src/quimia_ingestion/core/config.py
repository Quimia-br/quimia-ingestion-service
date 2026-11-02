from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Carrega .env sem sobrescrever variáveis já definidas no ambiente."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    extractor_api_url: str = os.getenv("EXTRACTOR_API_URL", "http://localhost:8000")
    extractor_api_token: str = os.getenv("EXTRACTOR_API_TOKEN", "")
    extractor_timeout_seconds: float = _float("EXTRACTOR_TIMEOUT_SECONDS", 60.0)

    # Mantido apenas para compatibilidade futura; não é requisito da v0.2.
    bridgesds_api_url: str = os.getenv("BRIDGESDS_API_URL", "")
    bridgesds_api_key: str = os.getenv("BRIDGESDS_API_KEY", "")

    db_host: str = os.getenv("QUIMIA_DB_HOST", "")
    db_port: int = _int("QUIMIA_DB_PORT", 5432)
    db_name: str = os.getenv("QUIMIA_DB_NAME", "")
    db_user: str = os.getenv("QUIMIA_DB_USER", "")
    db_password: str = os.getenv("QUIMIA_DB_PASSWORD", "")
    db_sslmode: str = os.getenv("QUIMIA_DB_SSLMODE", "require")

    state_db_path: Path = Path(os.getenv("STATE_DB_PATH", "./data/state.db"))
    document_storage_path: Path = Path(os.getenv("DOCUMENT_STORAGE_PATH", "./data/documents"))
    manual_inbox_path: Path = Path(os.getenv("MANUAL_INBOX_PATH", "./data/manual_inbox"))
    official_sds_catalog_path: Path = Path(os.getenv("OFFICIAL_SDS_CATALOG_PATH", "./config/official_sds_catalog.yaml"))

    zenrows_api_key: str = os.getenv("ZENROWS_API_KEY", "")
    image_search_country: str = os.getenv("IMAGE_SEARCH_COUNTRY", "br")
    image_search_language: str = os.getenv("IMAGE_SEARCH_LANGUAGE", "pt-br")
    image_search_max_results: int = _int("IMAGE_SEARCH_MAX_RESULTS", 20)

    fds_min_auto_source_score: int = _int("FDS_MIN_AUTO_SOURCE_SCORE", 85)

    # Padrão dos PNGs já existentes em quimia-bd/src/database/assets/produtos.
    image_canvas_size: int = _int("IMAGE_CANVAS_SIZE", 1254)
    image_min_size: int = _int("IMAGE_MIN_SIZE", 256)
    image_outer_frame_ratio: float = _float("IMAGE_OUTER_FRAME_RATIO", 0.03)
    image_outer_frame_transparent_ratio: float = _float("IMAGE_OUTER_FRAME_TRANSPARENT_RATIO", 0.98)
    image_auto_approve_score: float = _float("IMAGE_AUTO_APPROVE_SCORE", 0.90)
    image_review_score: float = _float("IMAGE_REVIEW_SCORE", 0.70)

    quimia_bd_local_path: Path | None = (
        Path(os.environ["QUIMIA_BD_LOCAL_PATH"]) if os.getenv("QUIMIA_BD_LOCAL_PATH") else None
    )
