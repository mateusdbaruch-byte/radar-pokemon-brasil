"""Testes do módulo de relatório de mercado."""

from datetime import datetime, timezone

from src.market_intelligence import analyze_card
from src.models import IntentType, RadarResult
from src.reporting import (
    build_card_narrative,
    build_market_summary,
    format_price_brl,
)


def _make_result(card: str, intent: IntentType, score: int, source: str = "reddit", price=None):
    return RadarResult(
        source=source,
        platform=source,
        card_name_detected=card,
        normalized_card_name=card,
        url="https://example.com",
        intent_type=intent,
        intent_score=score,
        price=price,
        collected_at=datetime.now(timezone.utc),
    )


class TestFormatPrice:
    def test_none(self):
        assert format_price_brl(None) == "—"

    def test_value(self):
        assert format_price_brl(1234.56) == "R$ 1.234,56"


class TestBuildCardNarrative:
    def test_with_signals(self):
        insight = analyze_card("Charizard", [
            _make_result("Charizard", IntentType.BUY_INTENT, 95),
            _make_result("Charizard", IntentType.SELL_INTENT, 80, "mercado_livre", 150.0),
        ])
        text = build_card_narrative(insight)
        assert "Charizard" not in text  # narrativa foca nos sinais
        assert "compra" in text.lower()
        assert "R$" in text

    def test_empty(self):
        insight = analyze_card("Mew", [])
        assert "nenhum sinal" in build_card_narrative(insight).lower()


class TestBuildMarketSummary:
    def test_summary_totals(self):
        results = [
            _make_result("Charizard", IntentType.BUY_INTENT, 95),
            _make_result("Charizard", IntentType.BUY_INTENT, 90),
            _make_result("Pikachu", IntentType.SELL_INTENT, 70, "mercado_livre", 50.0),
        ]
        insights = [analyze_card("Charizard", results[:2]), analyze_card("Pikachu", results[2:])]
        summary = build_market_summary(insights, monitored_cards=["Charizard", "Pikachu", "Mew"])

        assert summary.cards_monitored == 3
        assert summary.cards_with_data == 2
        assert summary.total_buy_signals == 2
        assert summary.total_sell_signals == 1
        assert summary.top_demand_card == "Charizard"

    def test_highlights_prioritize_demand(self):
        charizard = analyze_card("Charizard", [
            _make_result("Charizard", IntentType.BUY_INTENT, 95),
            _make_result("Charizard", IntentType.BUY_INTENT, 92),
        ])
        pikachu = analyze_card("Pikachu", [
            _make_result("Pikachu", IntentType.DISCUSSION, 30),
            _make_result("Pikachu", IntentType.DISCUSSION, 25),
        ])
        summary = build_market_summary([charizard, pikachu])
        assert summary.highlight_cards[0].card_name == "Charizard"
