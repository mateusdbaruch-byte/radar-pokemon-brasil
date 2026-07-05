"""Testes de filtros de qualidade do Opportunity Radar."""

from __future__ import annotations

import pytest

from src.opportunity_models import OpportunityType
from src.opportunity_quality import (
    QualityFilterConfig,
    evaluate_hit,
    is_blocked_domain,
    mentions_card,
)
from src.opportunity_scoring import score_opportunity


class TestBlockedDomains:
    def test_dicio_blocked(self):
        assert is_blocked_domain("https://www.dicio.com.br/procuro/")

    def test_mercadolivre_not_blocked(self):
        assert not is_blocked_domain("https://www.mercadolivre.com.br/item/123")


class TestEvaluateHit:
    def _opp(self, evidence: str, card: str, url: str):
        return score_opportunity(
            evidence=evidence,
            card_name=card,
            source="web_search",
            platform="serpapi",
            url=url,
        )

    def test_rejects_blocked_domain(self):
        opp = self._opp("Procuro Charizard Pokémon TCG", "Charizard", "https://dicio.com.br/procuro/")
        result = evaluate_hit(
            "Procuro", "definição de procuro", "https://dicio.com.br/procuro/",
            "Charizard", opp, QualityFilterConfig(),
        )
        assert result.accepted is False
        assert "bloqueado" in result.reason

    def test_rejects_intent_without_pokemon_context(self):
        opp = self._opp("Procuro algo", "Charizard", "https://example.com/x")
        result = evaluate_hit(
            "Procuro", "algo genérico", "https://example.com/x",
            "Charizard", opp, QualityFilterConfig(),
        )
        assert result.accepted is False

    def test_accepts_marketplace_with_card_and_tcg(self):
        evidence = "Charizard Pokémon TCG carta rara holo"
        url = "https://www.mercadolivre.com.br/charizard-carta"
        opp = self._opp(evidence, "Charizard", url)
        opp.confidence_score = 70
        result = evaluate_hit(
            "Charizard carta", evidence, url,
            "Charizard", opp, QualityFilterConfig(strict=True),
        )
        assert result.accepted is True
        assert result.why_saved
        assert mentions_card(evidence, "Charizard")

    def test_strict_rejects_low_confidence(self):
        evidence = "Charizard Pokémon TCG procuro comprar"
        url = "https://www.reddit.com/r/pokemontcg/comments/abc"
        opp = self._opp(evidence, "Charizard", url)
        opp.confidence_score = 50
        result = evaluate_hit(
            "Procuro Charizard", evidence, url,
            "Charizard", opp, QualityFilterConfig(strict=True),
        )
        assert result.accepted is False
        assert "confidence" in result.reason

    def test_buyer_only_rejects_seller(self):
        evidence = "Vendo Charizard Pokémon TCG desapego R$ 200"
        url = "https://www.olx.com.br/anuncio/charizard"
        opp = self._opp(evidence, "Charizard", url)
        opp.confidence_score = 80
        result = evaluate_hit(
            "Vendo Charizard", evidence, url,
            "Charizard", opp, QualityFilterConfig(strict=True, buyer_only=True),
        )
        assert result.accepted is False
        assert "buyer-only" in result.reason

    def test_seller_only_accepts_listing(self):
        evidence = "Vendo Charizard Pokémon TCG desapego abaixo da Liga"
        url = "https://www.olx.com.br/anuncio/charizard"
        opp = self._opp(evidence, "Charizard", url)
        opp.confidence_score = 75
        result = evaluate_hit(
            "Vendo Charizard", evidence, url,
            "Charizard", opp, QualityFilterConfig(strict=True, seller_only=True),
        )
        assert result.accepted is True
        assert result.refined_type in (
            OpportunityType.SELLER_SUPPLY,
            OpportunityType.URGENT_SALE,
        )

    def test_rejects_generic_tiktok(self):
        evidence = "Charizard dance trend"
        url = "https://www.tiktok.com/@user/video/123"
        opp = self._opp(evidence, "Charizard", url)
        result = evaluate_hit(
            "Charizard trend", evidence, url,
            "Charizard", opp, QualityFilterConfig(),
        )
        assert result.accepted is False
