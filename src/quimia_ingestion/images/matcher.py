from __future__ import annotations

from dataclasses import replace
import re
from urllib.parse import urlparse

from quimia_ingestion.domain.models import ImageCandidate
from quimia_ingestion.domain.rules import BrandRule, normalize_text

# Teto de quem tem dúvida (produto incompleto, kit): fica abaixo de qualquer limiar de auto-aprovação.
REVIEW_CAP = 0.69
# "caixa" fica de fora: é a embalagem normal do detergente em pó, não um kit.
KIT_WORDS = {"kit", "combo", "pack", "fardo"}
_KIT_PATTERNS = (
    re.compile(r"\b(\d+) ?x ?\d"),                                    # 6x500ml, 24 x 1l
    re.compile(r"\b(\d+)x\b"),                                        # 5x Assim
    re.compile(r"\bx ?(\d+)\b"),                                      # x6
    re.compile(r"\b(?:com|c|leve|pague) (\d+)\b"),                    # com 6, c 12, leve 3
    re.compile(r"\b(\d+) ?(?:un|und|unid|unids|unidades|pcs|pecas)\b"),  # "12 unidades" e "24un" colado
)
_UNIT_GLUE = re.compile(r"(\d) (ml|l|lt|g|kg)\b")


# Mesma coisa dita de jeitos diferentes (FDS x loja). Vale para o nome pedido e para o candidato, então é simétrico.
# O peso não entra: 400g e 800g seguem sendo produtos diferentes.
_SYNONYMS = (
    (re.compile(r"\bdet\b"), "detergente"),                                          # "DET. PÓ ASSIM"
    (re.compile(r"\b(?:detergente|sabao|lava roupas)(?: em)? po\b"), "lavaroupas po"),  # pó: detergente = sabão = lava-roupas
    (re.compile(r"\btripla acao\b"), "triplacao"),
)


def search_name(name: str) -> str:
    """Nome para busca/matching: tira o multiplicador de caixa ("24x500mL" -> "500mL"). O original não é alterado.

    Sem diferenciar caixa alta: as FDS trazem "24X500 ML".
    """
    return re.sub(r"\s+", " ", re.sub(r"\b\d+\s*[x×]\s*(?=\d)", "", name, flags=re.I)).strip()


def _norm(value: str) -> str:
    text = normalize_text(value)
    for pattern, replacement in _SYNONYMS:
        text = pattern.sub(replacement, text)
    return _UNIT_GLUE.sub(r"\1\2", text)


def _tokens(value: str) -> set[str]:
    return {x for x in _norm(value).split() if len(x) >= 2}


def _has_phrase(tokens: list[str], phrase: str) -> bool:
    words = _norm(phrase).split()
    return bool(words) and any(tokens[i:i + len(words)] == words for i in range(len(tokens) - len(words) + 1))


def _is_kit(text: str) -> bool:
    if set(text.split()) & KIT_WORDS:
        return True
    return any(int(m.group(1)) >= 2 for pattern in _KIT_PATTERNS for m in pattern.finditer(text))


def score_candidate(
    candidate: ImageCandidate, *, brand: BrandRule, product_name: str, other_brands: tuple[str, ...] = ()
) -> float:
    if candidate.unsafe:
        return 0.0
    product_name = search_name(product_name)
    text = _norm(f"{candidate.title} {candidate.source} {candidate.page_url}")
    words = text.split()
    haystack = set(words)

    # Marca por frase inteira (alias incluído), nunca por pedaço de outra palavra/produto.
    brand_match = 1.0 if any(_has_phrase(words, a) for a in (brand.display_name, *brand.aliases)) else 0.0
    # Marca explícita de outro fabricante ("Downy Brisa Suave", "Urca Brisa Azul"): rejeita, a menos
    # que o nome pedido contenha essa palavra.
    own = _norm(product_name).split()
    if any(_has_phrase(words, other) and not _has_phrase(own, other) for other in other_brands):
        return 0.0

    product_tokens = _tokens(product_name)
    product_match = len(product_tokens & haystack) / max(1, len(product_tokens))

    host = urlparse(candidate.page_url).hostname or ""
    official = any(host == domain or host.endswith("." + domain) for domain in (*brand.official_domains, *brand.image_domains))
    score = 0.30 * brand_match + 0.40 * product_match
    if official:
        score += 0.20
    elif candidate.is_product:
        score += 0.08
    if candidate.width and candidate.height and min(candidate.width, candidate.height) >= 500:
        score += 0.07
    if candidate.original_url.lower().split("?")[0].endswith(".png"):
        score += 0.03

    # Nunca auto-aprovados: sem a marca, com nome/variante incompletos ou kit no lugar da unidade.
    if brand_match == 0 or product_match < 1.0:
        score = min(score, REVIEW_CAP)
    # Em site oficial o título é o dado confiável: palavra do produto que só aparece na URL (título diz
    # "Micelar", URL diz "floral") é contradição, não confirmação.
    if official and product_tokens - set(_norm(candidate.title).split()):
        score = min(score, REVIEW_CAP)
    # Kit só pelo título: a URL traz dimensões ("1500x1500") que parecem multiplicador.
    if _is_kit(_norm(candidate.title)) and not (set(_norm(product_name).split()) & KIT_WORDS):
        score = max(0.0, score - 0.35)
    return min(1.0, score)


def rank_candidates(
    candidates: list[ImageCandidate], *, brand: BrandRule, product_name: str, other_brands: tuple[str, ...] = ()
) -> list[ImageCandidate]:
    ranked = [
        replace(item, score=score_candidate(item, brand=brand, product_name=product_name, other_brands=other_brands))
        for item in candidates
    ]
    return sorted(ranked, key=lambda item: item.score, reverse=True)
