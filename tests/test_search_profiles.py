"""Testes de perfis de busca e filtros por perfil."""

from __future__ import annotations

import pytest

from src.opportunity_models import OpportunityType
from src.opportunity_quality import (
    QualityFilterConfig,
    evaluate_hit,
    rejection_label,
)
from src.opportunity_scoring import score_opportunity
from src.search_profiles import (
    get_search_profile,
    list_profile_names,
    load_search_profiles,
    resolve_domain_groups,
)


class TestSearchProfilesConfig:
    def test_profiles_loaded(self):
        profiles = load_search_profiles()
        assert "demand_leads" in profiles
        assert "supply_deals" in profiles
        assert "market_reference" in profiles

    def test_demand_leads_templates(self):
        profile = get_search_profile("demand_leads")
        assert profile is not None
        queries = profile.queries_for_card("Charizard")
        assert len(queries) >= 10
        assert any("procuro" in q for q in queries)

    def test_domain_groups_resolve(self):
        domains = resolve_domain_groups(["marketplaces", "tcg_specialized"])
        assert "mercadolivre.com.br" in domains
        assert "ligapokemon.com.br" in domains

    def test_profile_quality_config(self):
        profile = get_search_profile("supply_deals")
        cfg = profile.to_quality_config()
        assert cfg.seller_only is True
        assert cfg.strict is True
        assert OpportunityType.SELLER_SUPPLY in cfg.intent_filter


class TestProfileFiltering:
    def _opp(self, evidence: str, card: str, url: str):
        return score_opportunity(
            evidence=evidence,
            card_name=card,
            source="web_search",
            platform="serpapi",
            url=url,
        )

    def test_demand_leads_rejects_marketplace(self):
        profile = get_search_profile("demand_leads")
        cfg = profile.to_quality_config()
        opp = self._opp(
            "Charizard Pokémon TCG à venda",
            "Charizard",
            "https://www.mercadolivre.com.br/item/123",
        )
        result = evaluate_hit(
            "Charizard vendo",
            "carta pokemon charizard",
            "https://www.mercadolivre.com.br/item/123",
            "Charizard",
            opp,
            cfg,
        )
        assert result.accepted is False
        assert result.reason_category in (
            "domain_outside_profile",
            "buyer_only",
            "intent_not_allowed",
            "seller_only",
            "no_intent",
        )

    def test_market_reference_accepts_olx_without_vendo(self):
        profile = get_search_profile("market_reference")
        cfg = profile.to_quality_config()
        opp = self._opp(
            "Charizard Pokémon TCG carta",
            "Charizard",
            "https://www.olx.com.br/anuncio/charizard",
        )
        result = evaluate_hit(
            "Charizard carta pokemon",
            "Charizard holo Pokémon TCG",
            "https://www.olx.com.br/anuncio/charizard",
            "Charizard",
            opp,
            cfg,
        )
        assert result.accepted is True
        assert result.refined_type == OpportunityType.PRICE_REFERENCE

    def test_market_reference_accepts_liga(self):
        profile = get_search_profile("market_reference")
        cfg = profile.to_quality_config()
        opp = self._opp(
            "Charizard Pokémon TCG LigaPokemon",
            "Charizard",
            "https://www.ligapokemon.com.br/card/123",
        )
        result = evaluate_hit(
            "Charizard",
            "preço referência carta pokemon",
            "https://www.ligapokemon.com.br/card/123",
            "Charizard",
            opp,
            cfg,
        )
        assert result.accepted is True

    def test_rejection_labels(self):
        assert rejection_label("blocked_domain") == "domínio bloqueado"
        assert rejection_label("intent_not_allowed") == "intent não permitido pelo perfil"


class TestProfileNames:
    def test_list_profiles(self):
        names = list_profile_names()
        assert names == sorted(names)
        assert len(names) == 3
