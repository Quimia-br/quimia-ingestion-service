import pypdf
import pytest

from quimia_ingestion.validation.pdf import SDSStructuralValidator


class FakePage:
    def extract_text(self):
        return """
        Ficha de Informações de Segurança de Produtos Químicos
        Produto: Minuano Limpador Multiuso
        3. Composição e informações sobre os ingredientes
        4. Medidas de primeiros-socorros
        10. Estabilidade e reatividade
        Data de emissão: 23/10/2020
        Versão: 00
        """


class FakeReader:
    pages = [FakePage()]


def test_pdf_validator_accepts_structural_fds(monkeypatch):
    monkeypatch.setattr(pypdf, "PdfReader", lambda *_: FakeReader())
    report = SDSStructuralValidator().validate(
        b"%PDF" + b"x" * 600,
        expected_brand="Minuano",
        expected_product="Limpador Multiuso",
    )
    assert report.accepted
    assert not report.review_required
    assert report.version == "00"
    assert report.document_date.isoformat() == "2020-10-23"


def test_pdf_validator_rejects_non_pdf():
    report = SDSStructuralValidator().validate(b"hello")
    assert not report.accepted


@pytest.mark.parametrize("title, section_10", [
    ("FICHA DE DADOS DE SEGURANÇA", "10. REATIVIDADE E ESTABILIDADE"),
    ("Ficha de Dados de Segurança", "SECÇÃO 10: Estabilidade e reactividade"),
])
def test_pdf_validator_accepts_real_world_heading_variants(monkeypatch, title, section_10):
    class Page:
        def extract_text(self):
            return f"""
            {title}
            3. Composição e informações sobre os ingredientes
            4. Medidas de primeiros-socorros
            {section_10}
            """

    class Reader:
        pages = [Page()]

    monkeypatch.setattr(pypdf, "PdfReader", lambda *_: Reader())
    assert SDSStructuralValidator().validate(b"%PDF" + b"x" * 600).accepted


import pytest

from quimia_ingestion.validation.pdf import product_name_from_pdf, product_name_from_text

# Cabeçalhos reais das FDS da Flora (primeira página, texto extraído pelo pypdf).
FLORA_HEADERS = [
    ("Ficha de Informações de Segurança de Produtos Químicos De acordo com ABNT NBR 14725-4: 2014 Data de emissão: 30/12/2022 Versão: 01 DETERGENTE LAVA LOUÇAS BRISA MAÇÃ 24X500ML PT (português - BR) 1/7",
     "DETERGENTE LAVA LOUÇAS BRISA MAÇÃ 24X500ML"),
    ("CÓPIA NÃO CON TRO LADA Ficha de Informações de Segurança Data de emissão: 27/06/2022 Versão: 00 DET. PO ASSIM ANTIBAC 20X800G / 403791 PT (português - BR)",
     "DET. PO ASSIM ANTIBAC 20X800G"),
    ("Ficha com Dados de Segurança (FDS) De acordo com a ABNT NBR 14725:2023 Data de emissão: 20/03/2024 Versão: 09 DET. PO ASSIM TRIPLACAO PT (português - BR) 1/9 SEÇÃO 1: Identificação",
     "DET. PO ASSIM TRIPLACAO"),
    ("Data de emissão: 05/11/2019 Versão:1.0 DETERGENTE EM PÓ ASSIM TRIPLA AÇÃO PT (português - BR) 1/8", "DETERGENTE EM PÓ ASSIM TRIPLA AÇÃO"),
    ("Versão: 00\nAMACIANTE MINUANO CONCENTRADO AZUL 12X500ML / 400352\nPT (português - BR)", "AMACIANTE MINUANO CONCENTRADO AZUL 12X500ML"),
]


@pytest.mark.parametrize("text,expected", FLORA_HEADERS)
def test_product_name_from_flora_header(text, expected):
    assert product_name_from_text(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "Nome do produto Ácido Sulfúrico 1.1 Identificação",                       # sem padrão de cabeçalho: não adivinha
    "CAS/CE Faixa de concentração (%) Peróxido de hidrogênio 7722-84-1",       # OMO: sem nome no cabeçalho
    "Versão: 2.1 Página 1 de 9",                                               # versão sem nome e sem "PT (português"
])
def test_product_name_from_text_returns_none_when_header_has_no_name(text):
    assert product_name_from_text(text) is None


def test_product_name_from_pdf_returns_none_for_unreadable_content():
    assert product_name_from_pdf(b"%PDF-1.7 lixo") is None
    assert product_name_from_pdf(b"") is None
