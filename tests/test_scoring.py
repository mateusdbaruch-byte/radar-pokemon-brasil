"""Testes do módulo de scoring."""

from pathlib import Path

import pytest

from src.models import IntentType
from src.scoring import (
    classify_intent,
    extract_price_from_text,
    load_keywords,
)


@pytest.fixture
def keywords():
    config_path = Path(__file__).parent.parent / "config" / "keywords.yml"
    return load_keywords(config_path)


class TestClassifyIntent:
    def test_explicit_buy_pt(self, keywords):
        text = "Procuro Charizard VMAX, compro na hora!"
        intent, score = classify_intent(text, keywords)
        assert intent == IntentType.BUY_INTENT
        assert score >= 90

    def test_explicit_buy_en(self, keywords):
        text = "WTB Umbreon alt art, paying well"
        intent, score = classify_intent(text, keywords)
        assert intent == IntentType.BUY_INTENT
        assert score >= 90

    def test_probable_buy(self, keywords):
        text = "Alguém tem Pikachu illustrator? Onde acho?"
        intent, score = classify_intent(text, keywords)
        assert intent == IntentType.BUY_INTENT
        assert 70 <= score <= 89

    def test_sell_intent(self, keywords):
        text = "Vendo Gengar ex, à venda, desapego"
        intent, score = classify_intent(text, keywords)
        assert intent == IntentType.SELL_INTENT
        assert score >= 65

    def test_marketplace_listing(self, keywords):
        text = "Cartão Pokémon Mew ex TCG"
        intent, score = classify_intent(text, keywords, is_marketplace_listing=True)
        assert intent in (IntentType.PRICE_REFERENCE, IntentType.SELL_INTENT)
        assert score >= 40

    def test_discussion(self, keywords):
        text = "O que vocês acham do meta com Lugia VSTAR neste formato?"
        intent, score = classify_intent(text, keywords)
        assert intent == IntentType.DISCUSSION
        assert score < 50

    def test_unknown_short(self, keywords):
        text = "ok"
        intent, score = classify_intent(text, keywords)
        assert intent == IntentType.UNKNOWN
        assert score < 40


class TestExtractPrice:
    def test_brl_format(self):
        price, currency = extract_price_from_text("Vendo por R$ 1.234,56")
        assert price == 1234.56
        assert currency == "BRL"

    def test_brl_simple(self):
        price, currency = extract_price_from_text("Pago R$500")
        assert price == 500.0
        assert currency == "BRL"

    def test_usd_format(self):
        price, currency = extract_price_from_text("Paying $75 for mint")
        assert price == 75.0
        assert currency == "USD"

    def test_no_price(self):
        price, currency = extract_price_from_text("Sem preço aqui")
        assert price is None
        assert currency == "BRL"
