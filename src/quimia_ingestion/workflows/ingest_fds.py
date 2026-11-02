from __future__ import annotations

import json

from quimia_ingestion.core.exceptions import ExtractorHTTPError
from quimia_ingestion.domain.models import BatchReport, ExtractorResponse, IngestionOutcome
from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.storage.documents import DocumentStorage
from quimia_ingestion.validation.pdf import SDSStructuralValidator

# Prefixos do last_error que marcam extração já paga (incompleta ou recusada): não reenviar ao extractor.
INCOMPLETE_EXTRACTION = "extração incompleta"
EXTRACTOR_FAILED = "extractor falhou"
# 400 (seções não localizadas) e 502 (LLM sem extração válida) são determinísticos para o mesmo PDF.
NON_RETRYABLE_HTTP = {400, 502}


def incomplete_sections(extraction: ExtractorResponse) -> list[str]:
    """Seções obrigatórias (03 composição, 04 primeiros socorros) ausentes ou sem conteúdo.

    `encontrada: true` não basta: o extractor devolve 200 com a lista vazia quando não reconhece o título.
    """
    checks = (
        ("03", extraction.secoes.section_03, "compostos"),
        ("04", extraction.secoes.section_04, "primeiros_socorros"),
    )
    return [n for n, sec, field in checks if not (sec.encontrada and (sec.model_extra or {}).get(field))]


class FDSIngestionWorkflow:
    def __init__(
        self,
        *,
        provider,
        extractor,
        repository,
        state,
        storage: DocumentStorage,
        brand_policy: BrandPolicy,
        validator: SDSStructuralValidator | None = None,
        min_auto_source_score: int = 85,
    ):
        self.provider = provider
        self.extractor = extractor
        self.repository = repository
        self.state = state
        self.storage = storage
        self.brand_policy = brand_policy
        self.validator = validator
        self.min_auto_source_score = min_auto_source_score

    @staticmethod
    def _load_cached(path) -> ExtractorResponse | None:
        if not path.exists():
            return None
        try:
            return ExtractorResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            return None  # cache corrompido: cai para nova extração

    def run(self) -> BatchReport:
        report = BatchReport()
        for document in self.provider.documents():
            version = document.version
            update_date = document.update_date
            digest = self.storage.sha256(document.content)
            existing_state = self.state.get_by_hash(digest)
            if existing_state and existing_state.get("status") in {"PERSISTED", "DUPLICATE"}:
                report.add(IngestionOutcome(document.source_id, "DUPLICATE", existing_state.get("fds_id"), "hash já processado"))
                continue
            if existing_state and existing_state.get("status") == "REVIEW_REQUIRED" and (existing_state.get("last_error") or "").startswith((INCOMPLETE_EXTRACTION, EXTRACTOR_FAILED)):
                report.add(IngestionOutcome(document.source_id, "REVIEW_REQUIRED", message=existing_state["last_error"]))
                continue

            brand_rule = self.brand_policy.resolve(document.brand)
            if not brand_rule:
                self.state.upsert(
                    digest=digest, source_id=document.source_id, source_url=document.source_url,
                    brand=document.brand, product_name=document.product_name, version=version,
                    update_date=update_date.isoformat() if update_date else None,
                    status="REJECTED", last_error="marca fora da allowlist",
                )
                report.add(IngestionOutcome(document.source_id, "REJECTED", message="marca fora da allowlist"))
                continue

            pdf_path = self.storage.save_pdf(document.content, digest)

            if document.source_score < self.min_auto_source_score:
                message = f"fonte exige revisão (score={document.source_score}, provider={document.provider})"
                self.state.upsert(
                    digest=digest, source_id=document.source_id, source_url=document.source_url,
                    brand=brand_rule.display_name, product_name=document.product_name, version=version,
                    update_date=update_date.isoformat() if update_date else None,
                    status="REVIEW_REQUIRED", pdf_path=str(pdf_path), last_error=message,
                )
                report.add(IngestionOutcome(document.source_id, "REVIEW_REQUIRED", message=message, pdf_path=pdf_path))
                continue

            if self.validator:
                validation = self.validator.validate(
                    document.content,
                    expected_brand=brand_rule.display_name,
                    expected_product=document.product_name,
                )
                version = version or validation.version
                update_date = update_date or validation.document_date
                if not validation.accepted:
                    message = "; ".join(validation.reasons) or "PDF rejeitado pela validação"
                    self.state.upsert(
                        digest=digest, source_id=document.source_id, source_url=document.source_url,
                        brand=brand_rule.display_name, product_name=document.product_name, version=version,
                        update_date=update_date.isoformat() if update_date else None,
                        status="REJECTED", pdf_path=str(pdf_path), last_error=message,
                    )
                    report.add(IngestionOutcome(document.source_id, "REJECTED", message=message, pdf_path=pdf_path))
                    continue
                if validation.review_required:
                    message = "; ".join(validation.reasons) or "PDF exige revisão"
                    self.state.upsert(
                        digest=digest, source_id=document.source_id, source_url=document.source_url,
                        brand=brand_rule.display_name, product_name=document.product_name, version=version,
                        update_date=update_date.isoformat() if update_date else None,
                        status="REVIEW_REQUIRED", pdf_path=str(pdf_path), last_error=message,
                    )
                    report.add(IngestionOutcome(document.source_id, "REVIEW_REQUIRED", message=message, pdf_path=pdf_path))
                    continue

            try:
                by_source = self.repository.find_fds_by_source_url(document.source_url)
                if by_source:
                    self.state.upsert(
                        digest=digest, source_id=document.source_id, source_url=document.source_url,
                        brand=brand_rule.display_name, product_name=document.product_name, version=version,
                        update_date=update_date.isoformat() if update_date else None,
                        status="DUPLICATE", fds_id=by_source, pdf_path=str(pdf_path),
                    )
                    report.add(IngestionOutcome(document.source_id, "DUPLICATE", by_source, "fonte_url já cadastrada", pdf_path))
                    continue

                cache_path = pdf_path.with_suffix(".extraction.json")
                extraction = self._load_cached(cache_path)
                if extraction is None:
                    try:
                        extraction = self.extractor.extract(document.content, filename=pdf_path.name)
                    except ExtractorHTTPError as exc:
                        if exc.status_code not in NON_RETRYABLE_HTTP:
                            raise
                        pdf_path.with_suffix(".extraction_error.json").write_text(
                            json.dumps({"http": exc.status_code, "detail": exc.detail}, ensure_ascii=False), encoding="utf-8"
                        )
                        message = f"{EXTRACTOR_FAILED}: HTTP {exc.status_code}: {exc.detail[:200]}"
                        self.state.upsert(
                            digest=digest, source_id=document.source_id, source_url=document.source_url,
                            brand=brand_rule.display_name, product_name=document.product_name, version=version,
                            update_date=update_date.isoformat() if update_date else None,
                            status="REVIEW_REQUIRED", pdf_path=str(pdf_path), last_error=message,
                        )
                        report.add(IngestionOutcome(document.source_id, "REVIEW_REQUIRED", message=message, pdf_path=pdf_path))
                        continue
                    # Resposta paga fica em disco antes de qualquer outra decisão (revisão, falha no banco...).
                    cache_path.write_text(
                        json.dumps(extraction.model_dump(mode="json", by_alias=True), ensure_ascii=False), encoding="utf-8"
                    )
                missing = incomplete_sections(extraction)
                if missing:
                    message = f"{INCOMPLETE_EXTRACTION}: seção {', '.join(missing)} ausente ou vazia no extractor"
                    self.state.upsert(
                        digest=digest, source_id=document.source_id, source_url=document.source_url,
                        brand=brand_rule.display_name, product_name=document.product_name, version=version,
                        update_date=update_date.isoformat() if update_date else None,
                        status="REVIEW_REQUIRED", pdf_path=str(pdf_path), last_error=message,
                    )
                    report.add(IngestionOutcome(document.source_id, "REVIEW_REQUIRED", message=message, pdf_path=pdf_path))
                    continue
                product_id = self.repository.get_or_create_product(brand_rule.display_name, document.product_name)
                by_identity = self.repository.find_fds_by_identity(product_id, version, update_date)
                if by_identity:
                    self.state.upsert(
                        digest=digest, source_id=document.source_id, source_url=document.source_url,
                        brand=brand_rule.display_name, product_name=document.product_name, version=version,
                        update_date=update_date.isoformat() if update_date else None,
                        status="DUPLICATE", fds_id=by_identity, pdf_path=str(pdf_path),
                    )
                    report.add(IngestionOutcome(document.source_id, "DUPLICATE", by_identity, "produto/versão/data já cadastrados", pdf_path))
                    continue

                raw_json = extraction.model_dump(mode="json", by_alias=True)
                fds_id = self.repository.insert_fds(
                    product_id, version, update_date, document.source_url, raw_json
                )
                self.state.upsert(
                    digest=digest, source_id=document.source_id, source_url=document.source_url,
                    brand=brand_rule.display_name, product_name=document.product_name, version=version,
                    update_date=update_date.isoformat() if update_date else None,
                    status="PERSISTED", fds_id=fds_id, pdf_path=str(pdf_path),
                )
                report.add(IngestionOutcome(document.source_id, "PERSISTED", fds_id, extraction.status, pdf_path))
            except Exception as exc:
                self.state.upsert(
                    digest=digest, source_id=document.source_id, source_url=document.source_url,
                    brand=brand_rule.display_name, product_name=document.product_name, version=version,
                    update_date=update_date.isoformat() if update_date else None,
                    status="FAILED", pdf_path=str(pdf_path), last_error=str(exc),
                )
                report.add(IngestionOutcome(document.source_id, "FAILED", message=str(exc), pdf_path=pdf_path))
        return report
