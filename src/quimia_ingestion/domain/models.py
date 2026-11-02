from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SectionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    encontrada: bool


class ExtractorSections(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    section_03: SectionPayload = Field(alias="03")
    section_04: SectionPayload = Field(alias="04")
    section_10: SectionPayload = Field(alias="10")


class ExtractorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["processado", "processado_com_pendencias"]
    mensagem: str | None = None
    secoes: ExtractorSections
    pendencias: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_matches_pending(self) -> "ExtractorResponse":
        has_pending = bool(self.pendencias)
        if has_pending != (self.status == "processado_com_pendencias"):
            raise ValueError("status do extractor não corresponde às pendências")
        if has_pending and not self.mensagem:
            raise ValueError("extração com pendências precisa de mensagem")
        return self


@dataclass(frozen=True)
class SDSDocument:
    source_id: str
    source_url: str
    brand: str
    product_name: str
    content: bytes
    version: str | None = None
    update_date: date | None = None
    provider: str = "unknown"
    source_score: int = 100
    discovery_method: str = "direct"


@dataclass(frozen=True)
class ProductRecord:
    id: int
    brand: str
    name: str
    tipo_produto: str | None = None
    descricao: str | None = None
    foto_url: str | None = None


@dataclass(frozen=True)
class ImageCandidate:
    original_url: str
    page_url: str
    source: str
    title: str
    width: int | None = None
    height: int | None = None
    is_product: bool = False
    unsafe: bool = False
    score: float = 0.0


@dataclass(frozen=True)
class ImageQualityReport:
    accepted: bool
    reasons: tuple[str, ...] = ()
    width: int = 0
    height: int = 0
    transparent_ratio: float = 0.0
    outer_frame_transparent_ratio: float = 0.0
    halo_ratio: float = 0.0


@dataclass(frozen=True)
class PDFValidationReport:
    accepted: bool
    review_required: bool = False
    reasons: tuple[str, ...] = ()
    extracted_text: str = ""
    version: str | None = None
    document_date: date | None = None


@dataclass(frozen=True)
class IngestionOutcome:
    source_id: str
    status: str
    fds_id: int | None = None
    message: str | None = None
    pdf_path: Path | None = None


@dataclass
class BatchReport:
    outcomes: list[IngestionOutcome] = field(default_factory=list)

    def add(self, outcome: IngestionOutcome) -> None:
        self.outcomes.append(outcome)

    def count(self, status: str) -> int:
        return sum(item.status == status for item in self.outcomes)
