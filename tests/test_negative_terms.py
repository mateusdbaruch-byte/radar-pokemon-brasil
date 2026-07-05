"""Testes de termos negativos e contexto bloqueado."""

from __future__ import annotations

from src.opportunity_quality import QualityFilterConfig, evaluate_hit
from src.opportunity_scoring import score_opportunity
from src.tcg_knowledge import analyze_text, classify_text, is_negative_context


class TestNegativeTerms:
    def test_significado_de_procuro(self):
        text = "significado de procuro"
        neg, terms = is_negative_context(text)
        assert neg is True
        signals = analyze_text(text)
        assert signals.negative_context

    def test_pokemon_go_charizard(self):
        text = "Pokémon GO Charizard"
        neg, _ = is_negative_context(text)
        assert neg is True
        result = classify_text(text, card_hint="Charizard")
        assert "negativo" in result.probable_opportunity

    def test_tcg_pocket_blocked(self):
        neg, _ = is_negative_context("Charizard TCG Pocket carta")
        assert neg is True

    def test_physical_tcg_not_negative(self):
        text = "Procuro Charizard Pokémon TCG português"
        neg, _ = is_negative_context(text)
        assert neg is False

    def test_evaluate_rejects_negative_context(self):
        opp = score_opportunity(
            evidence="Pokémon GO Charizard raid",
            card_name="Charizard",
            source="web_search",
            platform="test",
            url="https://example.com/go",
        )
        result = evaluate_hit(
            "Pokémon GO Charizard",
            "raid boss",
            "https://example.com/go",
            "Charizard",
            opp,
            QualityFilterConfig(strict=True),
        )
        assert result.accepted is False
        assert "negativo" in result.reason
