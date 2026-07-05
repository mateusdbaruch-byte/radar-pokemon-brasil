"""Testes de calibração de perfis e radar unificado."""

from __future__ import annotations

import pytest

from src.opportunity_models import Opportunity, OpportunityType
from src.opportunity_quality import (
    QualityFilterConfig,
    classify_market_reference_type,
    evaluate_hit,
    is_market_reference_domain,
)
from src.opportunity_reporting import (
    build_card_unified_stats,
    compute_market_opportunity_score,
    compute_strategic_reading,
)
from src.opportunity_scoring import score_opportunity
from src.search_profiles import get_search_profile


class TestMarketReferenceCalibration:
    def _opp(self, evidence: str, card: str, url: str):
        return score_opportunity(
            evidence=evidence,
            card_name=card,
            source="web_search",
            platform="serpapi",
            url=url,
        )

    def test_market_reference_domains(self):
        assert is_market_reference_domain("mercadolivre.com.br")
        assert is_market_reference_domain("ligapokemon.com.br")
        assert is_market_reference_domain("droper.app")

    def test_market_reference_accepts_ml_without_intent(self):
        profile = get_search_profile("market_reference")
        cfg = profile.to_quality_config()
        evidence = "Charizard carta pokemon holo rara Pokémon TCG"
        url = "https://www.mercadolivre.com.br/charizard-carta"
        opp = self._opp(evidence, "Charizard", url)
        opp.confidence_score = 50
        result = evaluate_hit(
            "Charizard carta pokemon",
            evidence,
            url,
            "Charizard",
            opp,
            cfg,
        )
        assert result.accepted is True
        assert result.refined_type in (
            OpportunityType.PRICE_REFERENCE,
            OpportunityType.SUPPLY_SIGNAL,
        )

    def test_market_reference_accepts_shopee_listing(self):
        profile = get_search_profile("market_reference")
        cfg = profile.to_quality_config()
        evidence = "Umbreon VMAX Pokémon TCG carta"
        url = "https://shopee.com.br/umbreon-vmax"
        opp = self._opp(evidence, "Umbreon", url)
        result = evaluate_hit(
            "Umbreon VMAX",
            evidence,
            url,
            "Umbreon",
            opp,
            cfg,
        )
        assert result.accepted is True

    def test_classify_market_reference_type(self):
        assert classify_market_reference_type(
            "ligapokemon.com.br", "Charizard preço"
        ) == OpportunityType.PRICE_REFERENCE
        assert classify_market_reference_type(
            "mercadolivre.com.br", "Charizard carta pokemon"
        ) == OpportunityType.PRICE_REFERENCE

    def test_demand_leads_rejects_marketplace_even_with_compro(self):
        profile = get_search_profile("demand_leads")
        cfg = profile.to_quality_config()
        evidence = "Compro Charizard Pokémon TCG carta"
        url = "https://www.mercadolivre.com.br/item/123"
        opp = self._opp(evidence, "Charizard", url)
        opp.confidence_score = 80
        result = evaluate_hit(
            "Compro Charizard",
            evidence,
            url,
            "Charizard",
            opp,
            cfg,
        )
        assert result.accepted is False
        assert result.reason_category in (
            "domain_outside_profile",
            "buyer_only",
        )


class TestUnifiedReporting:
    def _make_opp(
        self,
        card: str,
        opp_type: OpportunityType,
        profile: str,
        score: int,
        domain: str,
    ) -> Opportunity:
        return Opportunity(
            source="web_search",
            platform="serpapi",
            card_name_detected=card,
            normalized_card_name=card,
            opportunity_type=opp_type,
            opportunity_score=score,
            confidence_score=70,
            profile=profile,
            domain=domain,
            url=f"https://{domain}/item",
        )

    def test_build_card_unified_stats(self):
        opps = [
            self._make_opp(
                "Charizard",
                OpportunityType.BUYER_DEMAND,
                "demand_leads",
                80,
                "facebook.com",
            ),
            self._make_opp(
                "Charizard",
                OpportunityType.PRICE_REFERENCE,
                "market_reference",
                70,
                "ligapokemon.com.br",
            ),
            self._make_opp(
                "Charizard",
                OpportunityType.URGENT_SALE,
                "supply_deals",
                90,
                "olx.com.br",
            ),
        ]
        stats = build_card_unified_stats("Charizard", opps)
        assert stats.buyer_demand_count == 1
        assert stats.market_reference_count == 1
        assert stats.urgent_sale_count == 1
        assert stats.average_opportunity_score == pytest.approx(80.0)
        assert stats.market_opportunity_score > 0

    def test_strategic_reading_scarcity(self):
        from src.opportunity_reporting import CardUnifiedStats

        stats = CardUnifiedStats(
            card_name="Mew",
            buyer_demand_count=3,
            market_reference_count=0,
            seller_supply_count=0,
            urgent_sale_count=0,
            total_opportunities=3,
        )
        readings = compute_strategic_reading(stats)
        assert "possível escassez" in readings[0]

    def test_market_opportunity_score_zero_when_empty(self):
        from src.opportunity_reporting import CardUnifiedStats

        stats = CardUnifiedStats(card_name="Mew")
        assert compute_market_opportunity_score(stats) == 0


class TestProfileField:
    def test_opportunity_profile_roundtrip(self):
        opp = Opportunity(
            source="web_search",
            platform="serpapi",
            card_name_detected="Charizard",
            normalized_card_name="Charizard",
            profile="market_reference",
        )
        row = opp.to_db_row()
        assert row["profile"] == "market_reference"
        restored = Opportunity.from_db_row(row)
        assert restored.profile == "market_reference"
