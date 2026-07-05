"""Testes de detecção de cartas."""

from __future__ import annotations

import pytest

from src.card_detection import (
    detect_card_candidates,
    detect_card_in_text,
    detect_card_match,
    normalize_text,
)
from src.tcg_knowledge import classify_text


class TestNormalizeText:
    def test_accents_and_spaces(self):
        assert normalize_text("Pokémon  TCG") == "pokemon tcg"

    def test_keeps_symbols(self):
        assert "&" in normalize_text("Latias & Latios GX")


class TestDetectCardInText:
    def test_procuro_charizard(self):
        card = detect_card_in_text("Procuro Charizard 151 português NM")
        assert card == "Charizard"

    def test_not_procuro(self):
        card = detect_card_in_text("Procuro Charizard 151 português NM")
        assert card != "Procuro"

    def test_fechando_pikachu(self):
        card = detect_card_in_text("Fechando master set 151, falta Pikachu")
        assert card == "Pikachu"

    def test_vendo_umbreon(self):
        card = detect_card_in_text("Vendo Umbreon abaixo da Liga")
        assert card == "Umbreon"

    def test_desapego_gengar(self):
        card = detect_card_in_text("Desapego Gengar SAR Copag")
        assert card == "Gengar"

    def test_mew_psa(self):
        card = detect_card_in_text("Mew PSA 10")
        assert card == "Mew"

    def test_significado_sem_carta(self):
        card = detect_card_in_text("significado de procuro")
        assert card == ""

    def test_latias_latios(self):
        card = detect_card_in_text("Procuro Latias & Latios GX")
        assert card in ("Latias & Latios", "Latias & Latios GX")

    def test_card_hint_validated(self):
        match = detect_card_match(
            "Procuro Charizard 151 português NM",
            card_hint="Charizard",
        )
        assert match.card == "Charizard"
        assert match.confidence >= 95

    def test_mew_not_mewtwo(self):
        assert detect_card_in_text("Mew PSA 10") == "Mew"
        assert detect_card_in_text("Mewtwo ex holo") == "Mewtwo"


class TestClassifyWithCardDetection:
    def test_charizard_buy_intent(self):
        r = classify_text("Procuro Charizard 151 português NM, pago à vista")
        assert r.card_detected == "Charizard"
        assert r.card_confidence >= 90
        assert r.signals.has_buy_intent

    def test_pikachu_master_set(self):
        r = classify_text("Fechando master set 151, falta Pikachu")
        assert r.card_detected == "Pikachu"
        assert r.signals.collection == "151"

    def test_umbreon_seller(self):
        r = classify_text("Vendo Umbreon abaixo da Liga")
        assert r.card_detected == "Umbreon"
        assert r.signals.has_sell_intent
        assert r.opportunity_type in ("urgent_sale", "seller_supply", "seller_intent")

    def test_gengar_sar_copag(self):
        r = classify_text("Desapego Gengar SAR Copag")
        assert r.card_detected == "Gengar"
        assert "SAR" in r.signals.rarity

    def test_negative_no_card(self):
        r = classify_text("significado de procuro")
        assert r.card_detected == ""
        assert r.signals.negative_context

    def test_pokemon_go_negative(self):
        r = classify_text("Pokémon GO Charizard")
        assert r.card_detected == "Charizard"
        assert r.signals.negative_context
        assert "negativo" in r.probable_opportunity
