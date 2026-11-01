from quimia_ingestion.domain.models import ImageCandidate
from quimia_ingestion.domain.rules import BrandPolicy
from quimia_ingestion.images.matcher import rank_candidates, score_candidate


def test_official_domain_scores_above_random_source():
    policy = BrandPolicy.from_yaml("config/brands.yaml")
    brand = policy.resolve("Minuano")
    official = ImageCandidate(
        original_url="https://flora.com.br/a.jpg",
        page_url="https://flora.com.br/minuano/limpador-multiuso-original",
        source="Flora",
        title="Minuano Limpador Multiuso Original",
        width=1000,
        height=1000,
        is_product=True,
    )
    random = ImageCandidate(
        original_url="https://foo.test/a.jpg",
        page_url="https://foo.test/item",
        source="Foo",
        title="Minuano Limpador Multiuso Original",
        width=1000,
        height=1000,
        is_product=True,
    )
    assert score_candidate(official, brand=brand, product_name="Limpador Multiuso Original") > score_candidate(random, brand=brand, product_name="Limpador Multiuso Original")


def test_unsafe_candidate_scores_zero():
    policy = BrandPolicy.from_yaml("config/brands.yaml")
    brand = policy.resolve("OMO")
    candidate = ImageCandidate("x", "https://omo.com/x", "OMO", "OMO produto", unsafe=True)
    assert score_candidate(candidate, brand=brand, product_name="Produto") == 0


import pytest

from quimia_ingestion.images.matcher import REVIEW_CAP, search_name

POLICY = BrandPolicy.from_yaml("config/brands.yaml")
OFFICIAL = "https://flora.com.br/produtos/"
SHOP = "https://loja.test/p/"


def cand(title, page=SHOP, product=True):
    return ImageCandidate("https://img.test/a.png", page, "loja", title, 1000, 1000, product)


def score(title, brand, name, page=SHOP):
    return score_candidate(cand(title, page), brand=POLICY.resolve(brand), product_name=name, other_brands=POLICY.other_brands)


def test_correct_brand_in_title_on_official_domain_passes_auto_approval():
    assert score("Brisa Desinfetante Lavanda 500ml", "Brisa", "Desinfetante Lavanda 500ml", OFFICIAL + "brisa") >= 0.90


@pytest.mark.parametrize("title", ["Downy Brisa Suave 1L", "Urca Brisa Azul 500ml", "Amaciante Comfort Brisa"])
def test_other_brand_containing_our_brand_word_is_rejected(title):
    assert score(title, "Brisa", "Amaciante 1L") == 0.0
    # mesmo num domínio oficial, não é autoaprovado
    assert score(title, "Brisa", "Amaciante 1L", OFFICIAL + "x") < REVIEW_CAP


def test_brand_word_alone_inside_another_product_name_is_not_a_brand_match():
    assert score("Detergente Brisa Suave", "Minuano", "Detergente Brisa Suave") < 0.90


def test_ambiguous_title_on_official_domain_is_not_auto_approved():
    assert score("Detergente", "Minuano", "Detergente Lava Louças Neutro 500mL", OFFICIAL + "minuano") < 0.90


def test_kit_scores_below_unit_and_never_auto_approves():
    unit = score("Detergente Lava Louças Minuano Neutro 500ml", "Minuano", "Detergente Lava Louças Neutro 500ml", OFFICIAL + "minuano")
    assert unit >= 0.90
    for title in ("Kit 6 Detergente Lava Louças Minuano Neutro 500ml", "Detergente Lava Louças Minuano Neutro 500ml c/ 12 unidades",
                  "Detergente Lava Louças Minuano Neutro 24x500ml", "Combo 3 Detergente Lava Louças Minuano Neutro 500ml",
                  "24un Detergente Lava Loucas Neutro 500ml Minuano - DNAC", "12und Detergente Lava Louças Minuano Neutro 500ml"):
        kit = score(title, "Minuano", "Detergente Lava Louças Neutro 500ml", OFFICIAL + "minuano")
        assert kit < unit and kit < 0.90, title


def test_box_multiplier_is_removed_for_search_but_original_name_untouched():
    name = "Detergente Lava Louças Neutro 24x500mL"
    assert search_name(name) == "Detergente Lava Louças Neutro 500mL"
    assert search_name("Água Sanitária 2,5%") == "Água Sanitária 2,5%"
    assert search_name("Pack 12 x 1L") == "Pack 1L"
    # o candidato unitário casa com o nome sem "24x"
    assert score("Detergente Lava Louças Minuano Neutro 500 ml", "Minuano", name, OFFICIAL + "minuano") >= 0.90


def test_brand_alias_matches_as_whole_phrase():
    assert score("Mr Muscle Limpador Multiuso", "Mr. Músculo", "Limpador Multiuso", "https://mrmuscleclean.com/p") >= 0.90
    assert score("Mr Limpador Multiuso", "Mr. Músculo", "Limpador Multiuso") < 0.90


def test_similar_name_with_different_variant_goes_to_review():
    right = score("Minuano Desinfetante Lavanda 500ml", "Minuano", "Desinfetante Lavanda 500ml", OFFICIAL + "minuano")
    wrong = score("Minuano Desinfetante Marinho 500ml", "Minuano", "Desinfetante Lavanda 500ml", OFFICIAL + "minuano")
    assert right >= 0.90 and wrong <= REVIEW_CAP


def test_kit_detection_ignores_url_dimensions_and_powder_box_but_catches_5x():
    brand = POLICY.resolve("Minuano")
    url_dims = ImageCandidate("https://cdn.test/1500x1500/a.jpg", OFFICIAL + "minuano/1500x1500", "loja",
                              "Detergente Lava Louças Minuano Neutro 500ml", 1000, 1000, True)
    assert score_candidate(url_dims, brand=brand, product_name="Detergente Lava Louças Neutro 500ml") >= 0.90
    assert score("Detergente em Pó Assim Floral Caixa 400g", "Assim", "Detergente em Pó Floral 400g", OFFICIAL + "assim") >= 0.90
    assert score("5x Assim Detergente em Pó Floral 800g", "Assim", "Detergente em Pó Floral 800g", OFFICIAL + "assim") < 0.90


def test_uppercase_box_multiplier_from_fds_names_is_removed():
    assert search_name("DETERGENTE LAVA LOUÇAS MINUANO NEUTRO 24X500 ML") == "DETERGENTE LAVA LOUÇAS MINUANO NEUTRO 500 ML"
    assert search_name("AMACIANTE BRISA AZUL 6X2L") == "AMACIANTE BRISA AZUL 2L"


def test_uppercase_fds_name_with_box_multiplier_matches_store_title():
    s = score("Detergente Lava Louças Minuano Neutro 500ml", "Minuano", "DETERGENTE LAVA LOUÇAS MINUANO NEUTRO 24X500 ML", OFFICIAL + "minuano")
    assert s >= 0.90


def test_powder_detergent_synonyms_match_the_stores_wording():
    for fds_name in ("DET. PÓ ASSIM TRIPLAÇÃO MICELAR", "Detergente em Pó Assim Triplação Micelar", "SABÃO EM PÓ ASSIM TRIPLA AÇÃO MICELAR"):
        assert score("Lava Roupas Pó Assim Triplaçao Micelar 1,6Kg", "Assim", fds_name, OFFICIAL + "assim") >= 0.90, fds_name


def test_synonyms_do_not_hide_real_differences():
    page = OFFICIAL + "assim"
    # peso diferente do pedido, variante diferente e produto de outra categoria seguem em revisão
    assert score("Lava Roupas Pó Assim Triplaçao 800g", "Assim", "DET. PO ASSIM TRIPLACAO 400g", page) < 0.90
    assert score("Lava Roupas Pó Assim Triplaçao Micelar 1,6Kg", "Assim", "DET. PO ASSIM TRIPLACAO FLORAL", page) < 0.90
    assert score("Detergente Lava Louças Assim Neutro 500ml", "Assim", "DET. PÓ ASSIM TRIPLAÇÃO", page) < 0.90


def test_official_page_whose_title_contradicts_its_url_is_not_auto_approved():
    # Loja: título "Micelar" em URL "triplacao-floral". A variante pedida só aparece na URL.
    store = "https://compraflora.com.br/produtos/lava-roupas-po-assim-triplacao-floral-emb-economica-16kg/"
    contradictory = score("Lava Roupas em Pó Assim Micelar Embalagem Econômica 1,6kg", "Assim", "Detergente em Pó Assim Floral", store)
    consistent = score("Lava Roupas em Pó Assim Floral Embalagem Econômica 1,6kg", "Assim", "Detergente em Pó Assim Floral", store)
    assert contradictory < 0.90 <= consistent
