import pytest

from quimia_ingestion.mvp import motivos_exclusao, propor_nome


def _extracao(compostos=1, socorros=1, s10=True, pendencias=()):
    return {
        "secoes": {
            "03": {"encontrada": True, "compostos": ["x"] * compostos},
            "04": {"encontrada": True, "primeiros_socorros": ["x"] * socorros},
            "10": {"encontrada": s10, "incompatibilidades": []},
        },
        "pendencias": list(pendencias),
    }


def _pend(secao, campo="concentracao", motivo="informacao_ausente"):
    return {"secao": secao, "campo": campo, "motivo": motivo}


def test_complete_extraction_has_no_exclusion_reasons():
    assert motivos_exclusao(_extracao()) == []


@pytest.mark.parametrize("kwargs,trecho", [
    ({"compostos": 0}, "seção 03"),
    ({"socorros": 0}, "seção 04"),
    ({"s10": False}, "seção 10"),
    ({"pendencias": [_pend("03", "concentracao", "dados_contraditorios")]}, "pendência 03/concentracao"),
    ({"pendencias": [_pend("03", "nome", "termo_ambiguo")]}, "pendência 03/nome"),
    ({"pendencias": [_pend("03", "compostos", "documento_nao_especifica")]}, "pendência 03/compostos"),
    ({"pendencias": [_pend("04", "primeiros_socorros")]}, "pendência 04"),
    ({"pendencias": [_pend("10", "secao", "secao_nao_localizada")]}, "seção 10 não localizada"),
])
def test_missing_content_or_pending_in_03_04_excludes_product(kwargs, trecho):
    assert any(trecho in m for m in motivos_exclusao(_extracao(**kwargs)))


def test_cas_and_concentration_absent_from_the_document_do_not_exclude():
    pendencias = [_pend("03", "cas_numero"), _pend("03", "concentracao_min", "documento_nao_especifica"),
                  _pend("03", "unidade_concentracao", "termo_ambiguo")]
    assert motivos_exclusao(_extracao(pendencias=pendencias)) == []


def test_pending_in_section_10_that_is_not_a_missing_section_does_not_exclude():
    assert motivos_exclusao(_extracao(pendencias=[_pend("10", "incompatibilidades", "documento_nao_especifica")])) == []


@pytest.mark.parametrize("fds,marca,esperado", [
    ("DETERGENTE LAVA LOUÇAS MINUANO NEUTRO 24X500 ML", "Minuano", "Detergente Lava Louças Neutro 24x500mL"),
    ("DET. PO ASSIM TRIPLACAO", "Assim", "Detergente Pó Triplação"),
    ("DETERGENTE EM PÓ MINUANO FLORAL 24X500G", "Minuano", "Detergente em Pó Floral 24x500g"),
    ("SABAO BARRA BRISA AZUL 50X200G", "Brisa", "Sabão Barra Azul 50x200g"),
])
def test_name_proposal_drops_brand_and_normalizes_box_size(fds, marca, esperado):
    assert propor_nome(fds, marca) == esperado
