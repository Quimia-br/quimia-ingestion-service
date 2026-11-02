from pathlib import Path
from datetime import date

import pytest

from quimia_ingestion.core.exceptions import ExtractorHTTPError

from quimia_ingestion.domain.models import SDSDocument, ExtractorResponse
from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.state.sqlite import StateStore
from quimia_ingestion.storage.documents import DocumentStorage
from quimia_ingestion.workflows.ingest_fds import FDSIngestionWorkflow


class Provider:
    def __init__(self, docs): self.docs = docs
    def documents(self): return iter(self.docs)


S03_OK = {"encontrada": True, "compostos": [{"nome": "Água"}]}
S04_OK = {"encontrada": True, "primeiros_socorros": [{"via": "inalacao"}]}


def response(s03=S03_OK, s04=S04_OK, s10=None):
    return ExtractorResponse.model_validate({
        "status": "processado_com_pendencias",
        "mensagem": "revisar",
        "secoes": {"03": s03, "04": s04, "10": s10 or {"encontrada": False}},
        "pendencias": [{"secao": "03", "campo": "x", "motivo": "informacao_ausente", "descricao": "x", "evidencias": []}],
    })


class Extractor:
    def __init__(self): self.calls = 0
    def extract(self, pdf, filename="fds.pdf"):
        self.calls += 1
        return ExtractorResponse.model_validate({
            "status": "processado_com_pendencias",
            "mensagem": "revisar",
            "secoes": {
                "03": S03_OK,
                "04": S04_OK,
                "10": {"encontrada": True, "incompatibilidades": [], "situacao": "nao_especificadas"},
            },
            "pendencias": [{"secao": "03", "campo": "x", "motivo": "informacao_ausente", "descricao": "x", "evidencias": []}],
        })


class Repo:
    def __init__(self):
        self.inserted = []
        self.source_duplicate = None
        self.identity_duplicate = None
    def find_fds_by_source_url(self, source_url): return self.source_duplicate
    def get_or_create_product(self, brand, product_name): return 42
    def find_fds_by_identity(self, product_id, version, update_date): return self.identity_duplicate
    def insert_fds(self, product_id, version, update_date, source_url, raw_json):
        self.inserted.append((product_id, version, update_date, source_url, raw_json))
        return 99


def make_doc(content=b"%PDF-1.4 unique"):
    return SDSDocument(
        source_id="s1", source_url="https://source.test/1", brand="Minuano",
        product_name="Limpador Multiuso Original", content=content,
        version="3", update_date=date(2026, 8, 14),
    )


def workflow(tmp_path, provider, extractor, repo):
    return FDSIngestionWorkflow(
        provider=provider,
        extractor=extractor,
        repository=repo,
        state=StateStore(tmp_path / "state.db"),
        storage=DocumentStorage(tmp_path / "docs"),
        brand_policy=BrandPolicy.from_yaml("config/brands.yaml"),
    )


def test_success_persists_raw_json_and_pending(tmp_path):
    repo = Repo(); extractor = Extractor()
    flow = workflow(tmp_path, Provider([make_doc()]), extractor, repo)
    report = flow.run()
    assert report.count("PERSISTED") == 1
    assert extractor.calls == 1
    assert repo.inserted[0][4]["status"] == "processado_com_pendencias"
    assert repo.inserted[0][4]["pendencias"]


def test_second_run_is_idempotent_by_hash(tmp_path):
    repo = Repo(); extractor = Extractor(); provider = Provider([make_doc()])
    flow = workflow(tmp_path, provider, extractor, repo)
    assert flow.run().count("PERSISTED") == 1
    assert flow.run().count("DUPLICATE") == 1
    assert extractor.calls == 1


def test_source_url_duplicate_skips_extractor(tmp_path):
    repo = Repo(); repo.source_duplicate = 17
    extractor = Extractor()
    report = workflow(tmp_path, Provider([make_doc()]), extractor, repo).run()
    assert report.count("DUPLICATE") == 1
    assert extractor.calls == 0


def test_unknown_brand_is_rejected(tmp_path):
    repo = Repo(); extractor = Extractor()
    doc = make_doc(); doc = SDSDocument(**{**doc.__dict__, "brand": "Marca Qualquer"})
    report = workflow(tmp_path, Provider([doc]), extractor, repo).run()
    assert report.count("REJECTED") == 1
    assert extractor.calls == 0


def test_low_trust_source_requires_review_before_extractor(tmp_path):
    repo = Repo(); extractor = Extractor()
    doc = make_doc()
    doc = SDSDocument(**{**doc.__dict__, "provider": "search", "source_score": 70})
    report = workflow(tmp_path, Provider([doc]), extractor, repo).run()
    assert report.count("REVIEW_REQUIRED") == 1
    assert extractor.calls == 0


class IncompleteExtractor(Extractor):
    def extract(self, pdf, filename="fds.pdf"):
        self.calls += 1
        return ExtractorResponse.model_validate({
            "status": "processado_com_pendencias",
            "mensagem": "revisar",
            "secoes": {
                "03": {"encontrada": False, "compostos": []},
                "04": {"encontrada": True, "primeiros_socorros": []},
                "10": {"encontrada": True, "incompatibilidades": [], "situacao": "nao_especificadas"},
            },
            "pendencias": [{"secao": "03", "campo": "secao", "motivo": "secao_nao_localizada", "descricao": "x", "evidencias": []}],
        })


def test_missing_section_03_or_04_requires_review_and_is_not_reextracted(tmp_path):
    repo = Repo(); extractor = IncompleteExtractor()
    flow = workflow(tmp_path, Provider([make_doc()]), extractor, repo)
    first = flow.run()
    assert first.count("REVIEW_REQUIRED") == 1
    assert "seção 03" in first.outcomes[0].message
    assert first.outcomes[0].pdf_path.with_suffix(".extraction.json").exists()
    assert repo.inserted == []
    assert flow.run().count("REVIEW_REQUIRED") == 1
    assert extractor.calls == 1


class Fixed(Extractor):
    def __init__(self, resp): super().__init__(); self.resp = resp
    def extract(self, pdf, filename="fds.pdf"):
        self.calls += 1
        return self.resp


@pytest.mark.parametrize("resp", [
    response(s03={"encontrada": True, "compostos": []}),
    response(s04={"encontrada": True, "primeiros_socorros": []}),
    response(s03={"encontrada": False}),
    response(s04={"encontrada": False}),
    response(s03={"encontrada": True}),
])
def test_empty_or_missing_03_04_is_review_without_db_write_and_cached(tmp_path, resp):
    repo = Repo(); extractor = Fixed(resp)
    flow = workflow(tmp_path, Provider([make_doc()]), extractor, repo)
    first = flow.run()
    assert first.count("REVIEW_REQUIRED") == 1
    assert first.outcomes[0].pdf_path.with_suffix(".extraction.json").exists()
    assert repo.inserted == []
    assert flow.run().count("REVIEW_REQUIRED") == 1
    assert extractor.calls == 1


def test_valid_03_04_with_section_10_missing_still_persists(tmp_path):
    repo = Repo(); extractor = Fixed(response(s10={"encontrada": False}))
    assert workflow(tmp_path, Provider([make_doc()]), extractor, repo).run().count("PERSISTED") == 1
    assert repo.inserted[0][4]["secoes"]["10"]["encontrada"] is False


class Failing(Extractor):
    def __init__(self, status): super().__init__(); self.status = status
    def extract(self, pdf, filename="fds.pdf"):
        self.calls += 1
        raise ExtractorHTTPError(self.status, "detalhe")


@pytest.mark.parametrize("status", [400, 502])
def test_extractor_400_502_not_persisted_and_not_retried(tmp_path, status):
    repo = Repo(); extractor = Failing(status)
    flow = workflow(tmp_path, Provider([make_doc()]), extractor, repo)
    first = flow.run()
    assert first.count("REVIEW_REQUIRED") == 1
    assert first.outcomes[0].pdf_path.with_suffix(".extraction_error.json").exists()
    assert repo.inserted == []
    assert flow.run().count("REVIEW_REQUIRED") == 1
    assert extractor.calls == 1


def test_other_http_errors_stay_failed_and_retryable(tmp_path):
    extractor = Failing(401)
    flow = workflow(tmp_path, Provider([make_doc()]), extractor, Repo())
    assert flow.run().count("FAILED") == 1
    assert flow.run().count("FAILED") == 1
    assert extractor.calls == 2


def test_db_failure_after_paid_extraction_does_not_pay_again(tmp_path):
    class BrokenRepo(Repo):
        fail = True
        def insert_fds(self, *a):
            if self.fail:
                raise RuntimeError("db fora")
            return super().insert_fds(*a)
    repo = BrokenRepo(); extractor = Extractor()
    flow = workflow(tmp_path, Provider([make_doc()]), extractor, repo)
    assert flow.run().count("FAILED") == 1
    repo.fail = False
    assert flow.run().count("PERSISTED") == 1
    assert extractor.calls == 1


def test_official_source_score_alone_never_reaches_extractor_without_valid_fds(tmp_path):
    from quimia_ingestion.validation.pdf import SDSStructuralValidator
    repo = Repo(); extractor = Extractor()
    doc = SDSDocument(**{**make_doc().__dict__, "provider": "flora", "source_score": 100})
    flow = workflow(tmp_path, Provider([doc]), extractor, repo)
    flow.validator = SDSStructuralValidator()
    report = flow.run()
    assert report.count("REJECTED") == 1
    assert extractor.calls == 0 and repo.inserted == []


def test_cli_ingest_local_always_validates_pdf(tmp_path, monkeypatch):
    from quimia_ingestion import cli
    from quimia_ingestion.validation.pdf import SDSStructuralValidator
    seen = {}

    class Spy:
        def __init__(self, **kw): seen.update(kw)
        def run(self): return None

    monkeypatch.setattr(cli, "FDSIngestionWorkflow", Spy)
    monkeypatch.setattr(cli, "_repository", lambda settings: object())
    monkeypatch.setattr(cli, "LocalPDFProvider", lambda manifest: object())
    manifest = tmp_path / "m.json"; manifest.write_text("[]", encoding="utf-8")
    cli._ingest_local(manifest, Path("config/brands.yaml"), cli.Settings())
    assert isinstance(seen["validator"], SDSStructuralValidator)
