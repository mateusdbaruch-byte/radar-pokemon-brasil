"""Perfis de busca do Opportunity Radar — templates, filtros e domain groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.opportunity_models import OpportunityType
from src.opportunity_quality import QualityFilterConfig
from src.paths import DOMAIN_GROUPS, SEARCH_PROFILES

SEARCH_PROFILES_PATH = SEARCH_PROFILES
DOMAIN_GROUPS_PATH = DOMAIN_GROUPS

INTENT_TYPE_MAP: dict[str, OpportunityType] = {
    "BUYER_DEMAND": OpportunityType.BUYER_DEMAND,
    "HIGH_INTENT_LEAD": OpportunityType.HIGH_INTENT_LEAD,
    "DISCUSSION_SIGNAL": OpportunityType.DISCUSSION_SIGNAL,
    "SELLER_SUPPLY": OpportunityType.SELLER_SUPPLY,
    "URGENT_SALE": OpportunityType.URGENT_SALE,
    "UNDERPRICED_LISTING": OpportunityType.UNDERPRICED_LISTING,
    "ARBITRAGE_SIGNAL": OpportunityType.ARBITRAGE_SIGNAL,
    "PRICE_REFERENCE": OpportunityType.PRICE_REFERENCE,
    "SUPPLY_SIGNAL": OpportunityType.SUPPLY_SIGNAL,
    "MARKETPLACE_LISTING": OpportunityType.MARKETPLACE_LISTING,
    "WEB_SIGNAL": OpportunityType.WEB_SIGNAL,
}


@dataclass
class SearchProfile:
    name: str
    description: str = ""
    intent_filter: list[OpportunityType] = field(default_factory=list)
    strict: bool = False
    min_confidence: int = 65
    buyer_only: bool = False
    seller_only: bool = False
    domain_groups: list[str] = field(default_factory=list)
    query_templates: list[str] = field(default_factory=list)

    def queries_for_card(self, card: str) -> list[str]:
        return [t.format(card=card) for t in self.query_templates]

    def allowed_domains(self) -> list[str]:
        return resolve_domain_groups(self.domain_groups)

    def to_quality_config(
        self,
        *,
        strict_override: bool | None = None,
        buyer_only_override: bool | None = None,
        seller_only_override: bool | None = None,
        min_confidence_override: int | None = None,
    ) -> QualityFilterConfig:
        return QualityFilterConfig(
            strict=strict_override if strict_override is not None else self.strict,
            buyer_only=buyer_only_override if buyer_only_override is not None else self.buyer_only,
            seller_only=seller_only_override if seller_only_override is not None else self.seller_only,
            min_confidence=(
                min_confidence_override
                if min_confidence_override is not None
                else self.min_confidence
            ),
            intent_filter=list(self.intent_filter) if self.intent_filter else None,
            allowed_domains=self.allowed_domains() or None,
            profile_name=self.name,
        )


def load_domain_groups(path: Path = DOMAIN_GROUPS_PATH) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        group: [d.lower().strip() for d in domains]
        for group, domains in data.items()
        if isinstance(domains, list)
    }


def resolve_domain_groups(group_names: list[str]) -> list[str]:
    groups = load_domain_groups()
    domains: list[str] = []
    seen: set[str] = set()
    for name in group_names:
        for domain in groups.get(name, []):
            if domain not in seen:
                seen.add(domain)
                domains.append(domain)
    return domains


def load_search_profiles(path: Path = SEARCH_PROFILES_PATH) -> dict[str, SearchProfile]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    profiles: dict[str, SearchProfile] = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        intent_raw = cfg.get("intent_filter", []) or []
        intent_filter = [
            INTENT_TYPE_MAP[t]
            for t in intent_raw
            if t in INTENT_TYPE_MAP
        ]
        profiles[name] = SearchProfile(
            name=name,
            description=cfg.get("description", ""),
            intent_filter=intent_filter,
            strict=bool(cfg.get("strict", False)),
            min_confidence=int(cfg.get("min_confidence", 65)),
            buyer_only=bool(cfg.get("buyer_only", False)),
            seller_only=bool(cfg.get("seller_only", False)),
            domain_groups=list(cfg.get("domain_groups", []) or []),
            query_templates=list(cfg.get("query_templates", []) or []),
        )
    return profiles


def get_search_profile(name: str) -> SearchProfile | None:
    return load_search_profiles().get(name)


def list_profile_names() -> list[str]:
    return sorted(load_search_profiles().keys())
