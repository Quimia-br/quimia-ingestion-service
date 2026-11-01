from __future__ import annotations

from datetime import date
from io import BytesIO
import re

from quimia_ingestion.domain.models import PDFValidationReport
from quimia_ingestion.domain.rules import normalize_text


class SDSStructuralValidator:
    """Validação barata antes de gastar uma chamada no extractor.

    Não interpreta química; apenas verifica se o arquivo parece ser uma FDS/FISPQ,
    se contém as seções mínimas esperadas e tenta recuperar versão/data documental.
    """

    def __init__(self, *, max_pages: int = 20):
        self.max_pages = max_pages

    def validate(self, content: bytes, *, expected_brand: str | None = None, expected_product: str | None = None) -> PDFValidationReport:
        reasons: list[str] = []
        review = False
        if not content.startswith(b"%PDF"):
            return PDFValidationReport(False, reasons=("arquivo não possui assinatura PDF",))
        if len(content) < 512:
            return PDFValidationReport(False, reasons=("PDF pequeno demais",))

        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(content))
            if not reader.pages:
                return PDFValidationReport(False, reasons=("PDF sem páginas",))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[: self.max_pages])
        except Exception as exc:
            return PDFValidationReport(False, reasons=(f"PDF ilegível: {exc}",))

        normalized = normalize_text(text)
        if not any(marker in normalized for marker in (
            "ficha de informacoes de seguranca",
            "ficha com dados de seguranca",
            "ficha de dados de seguranca",  # nome da ABNT NBR 14725:2023
            "fispq",
            "safety data sheet",
        )):
            reasons.append("documento não identificado como FDS/FISPQ")

        section_markers = {
            "03": ("3 composicao", "3 informacoes sobre", "composicao e informacoes"),
            "04": ("4 medidas de primeiros", "medidas de primeiros socorros"),
            # Variantes reais: Flora usa "reatividade e estabilidade"; FDS em pt-PT, "reactividade".
            "10": ("estabilidade e reatividade", "reatividade e estabilidade", "estabilidade e reactividade"),
        }
        for section, markers in section_markers.items():
            if not any(marker in normalized for marker in markers):
                reasons.append(f"seção {section} não localizada")

        if expected_brand and normalize_text(expected_brand) not in normalized:
            reasons.append("marca esperada não localizada no texto")
            review = True

        if expected_product:
            tokens = [t for t in normalize_text(expected_product).split() if len(t) >= 4]
            if tokens and sum(token in normalized for token in tokens) < max(1, len(tokens) // 3):
                reasons.append("nome do produto tem baixa correspondência com o PDF")
                review = True

        fatal = [r for r in reasons if r.startswith("documento não") or r.startswith("seção ")]
        return PDFValidationReport(
            accepted=not fatal,
            review_required=review,
            reasons=tuple(reasons),
            extracted_text=text[:12000],
            version=self._extract_version(text),
            document_date=self._extract_date(text),
        )

    @staticmethod
    def _extract_version(text: str) -> str | None:
        match = re.search(r"(?i)\bvers(?:a|ã)o\s*[:\-]?\s*([A-Za-z0-9._-]{1,20})", text)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_date(text: str) -> date | None:
        patterns = (
            r"(?i)data\s+(?:de\s+)?(?:emiss[aã]o|revis[aã]o|atualiza[cç][aã]o)\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})",
            r"(?i)(?:emiss[aã]o|revis[aã]o|atualiza[cç][aã]o)\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    day, month, year = map(int, match.group(1).split("/"))
                    return date(year, month, day)
                except ValueError:
                    return None
        return None


# Cabeçalho das FDS da Flora (Minuano/Assim/Brisa): "... Versão: 01 NOME DO PRODUTO PT (português - BR)".
# Medido em 2026-11-01: 23 de 23 PDFs da Flora. Outros formatos não têm esse padrão e devolvem None;
# o rótulo "Nome do produto" foi testado e descartado (pegava "Código", "CAS/CE Faixa de concentração"...).
_FLORA_HEADER = re.compile(r"(?is)vers[ãa]o\s*:?\s*[\w.]+\s+(.{3,120}?)\s+PT\s*\(portugu")


def product_name_from_text(text: str) -> str | None:
    match = _FLORA_HEADER.search(text)
    if not match:
        return None
    name = " ".join(match.group(1).split())
    name = re.sub(r"\s*/\s*\d{3,}\s*$", "", name)  # código interno após a barra: "... 12X500ML / 400352"
    return name if len(name) >= 3 else None


def product_name_from_pdf(content: bytes, *, pages: int = 2) -> str | None:
    """Nome do produto lido do cabeçalho do PDF, ou None se o formato não for reconhecido."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(content))
        return product_name_from_text("\n".join((p.extract_text() or "") for p in reader.pages[:pages]))
    except Exception:
        return None
