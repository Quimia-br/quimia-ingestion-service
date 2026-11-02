from quimia_ingestion.domain.rules import BrandPolicy, normalize_text


def test_normalize_text_removes_accents():
    assert normalize_text("Mr. Músculo") == "mr musculo"


def test_brand_policy_resolves_alias():
    policy = BrandPolicy.from_yaml("config/brands.yaml")
    assert policy.resolve("mr musculo").display_name == "Mr. Músculo"
    assert policy.resolve("OMO").display_name == "OMO"


def test_brand_policy_rejects_unknown():
    policy = BrandPolicy.from_yaml("config/brands.yaml")
    assert policy.resolve("Flora") is None
