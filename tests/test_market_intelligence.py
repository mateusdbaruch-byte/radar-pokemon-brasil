"""Testes do módulo de inteligência de mercado."""

from datetime import datetime, timezone

import pytest

from src.market_intelligence import (
    analyze_all_cards,
    analyze_card,
    compute_recommendation,
)
from src.models import IntentType, RadarResult


def _make_result(
    card: str,
    intent: IntentType,
    score: int,
    source: str = "reddit",
    price: float | None = None,
) -> RadarResult:
    return RadarResult(
        source=source,
        platform=source,
        card_name_detected=card,
        normalized_card_name=card,
        url=f"https://example.com/{card}",
        intent_type=intent,
        intent_score=score,
        price=price,
        collected_at=datetime.now(timezone.utc),
    )


class TestComputeRecommendation:
    def test_insufficient_data(self):
        assert compute_recommendation(1, 0, 0, 0, 0) == "dados insuficientes"

    def test_good_demand(self):
        rec = compute_recommendation(5, 3, 1, 1, 85.0)
        assert rec == "boa demanda"

    def test_high_supply(self):
        rec = compute_recommendation(8, 1, 4, 5, 30.0)
        assert rec == "muita oferta"

    def test_opportunity(self):
        rec = compute_recommendation(4, 2, 1, 2, 60.0)
        assert rec == "possível oportunidade"

    def test_observe(self):
        rec = compute_recommendation(3, 1, 1, 1, 40.0)
        assert rec == "observar"


class TestAnalyzeCard:
    def test_price_stats(self):
        results = [
            _make_result("Charizard", IntentType.SELL_INTENT, 80, "mercado_livre", 100.0),
            _make_result("Charizard", IntentType.SELL_INTENT, 75, "mercado_livre", 200.0),
            _make_result("Charizard", IntentType.BUY_INTENT, 95, "reddit"),
        ]
        insight = analyze_card("Charizard", results)
        assert insight.min_price == 100.0
        assert insight.max_price == 200.0
        assert insight.avg_price == 150.0
        assert insight.listing_count == 2
        assert insight.buy_signals == 1
        assert insight.sell_signals == 2
        assert insight.demand_score_avg == 95.0
        assert insight.main_source == "Mercado Livre"

    def test_price_reference_counts_as_sell(self):
        results = [
            _make_result("Mew", IntentType.PRICE_REFERENCE, 55, "mercado_livre", 80.0),
        ]
        insight = analyze_card("Mew", results)
        assert insight.sell_signals == 1
        assert insight.listing_count == 1

    def test_empty_results(self):
        insight = analyze_card("Mew", [])
        assert insight.recommendation == "dados insuficientes"
        assert insight.total_signals == 0


class TestAnalyzeAllCards:
    def test_groups_by_card(self):
        results = [
            _make_result("Pikachu", IntentType.BUY_INTENT, 90),
            _make_result("Umbreon", IntentType.SELL_INTENT, 70, "mercado_livre", 50.0),
        ]
        insights = analyze_all_cards(results)
        assert len(insights) == 2
        cards = {i.card_name for i in insights}
        assert cards == {"Pikachu", "Umbreon"}

    def test_sorted_by_demand(self):
        results = [
            _make_result("Pikachu", IntentType.DISCUSSION, 30),
            _make_result("Charizard", IntentType.BUY_INTENT, 95),
            _make_result("Charizard", IntentType.BUY_INTENT, 90),
        ]
        insights = analyze_all_cards(results)
        assert insights[0].card_name == "Charizard"

    def test_includes_monitored_cards_without_data(self):
        results = [_make_result("Pikachu", IntentType.BUY_INTENT, 90)]
        insights = analyze_all_cards(results, monitored_cards=["Pikachu", "Mew"])
        assert len(insights) == 2
        assert insights[0].card_name == "Pikachu"
        assert insights[1].card_name == "Mew"
        assert insights[1].total_signals == 0
        assert insights[1].recommendation == "dados insuficientes"
