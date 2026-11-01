from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata
import yaml


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", text)


@dataclass(frozen=True)
class BrandRule:
    key: str
    display_name: str
    aliases: tuple[str, ...]
    official_domains: tuple[str, ...]
    manufacturers: tuple[str, ...]
    providers: tuple[str, ...] = ()
    # Sites oficiais só de foto (loja): contam como oficial no matcher de imagens, não na busca de FDS.
    image_domains: tuple[str, ...] = ()


class BrandPolicy:
    def __init__(self, rules: dict[str, BrandRule], other_brands: tuple[str, ...] = ()):
        self.rules = rules
        # Marcas conhecidas fora da allowlist, usadas só para rejeitar imagens de outro fabricante.
        self.other_brands = other_brands
        self._aliases: dict[str, BrandRule] = {}
        for rule in rules.values():
            for alias in set(rule.aliases + (rule.display_name,)):
                self._aliases[normalize_text(alias)] = rule

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BrandPolicy":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        rules: dict[str, BrandRule] = {}
        for key, item in data.get("brands", {}).items():
            rules[key] = BrandRule(
                key=key,
                display_name=item["display_name"],
                aliases=tuple(item.get("aliases", [])),
                official_domains=tuple(item.get("official_domains", [])),
                manufacturers=tuple(item.get("manufacturers", [])),
                providers=tuple(item.get("providers", [])),
                image_domains=tuple(item.get("image_domains", [])),
            )
        return cls(rules, tuple(data.get("other_brands", [])))

    def resolve(self, brand: str) -> BrandRule | None:
        return self._aliases.get(normalize_text(brand))

    def is_allowed(self, brand: str) -> bool:
        return self.resolve(brand) is not None

    def all_rules(self) -> tuple[BrandRule, ...]:
        return tuple(self.rules.values())
