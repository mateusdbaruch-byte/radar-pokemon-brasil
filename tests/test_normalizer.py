"""Testes do módulo de normalização."""

import pytest

from src.normalizer import (
    build_search_query,
    detect_card_in_text,
    normalize_card_name,
    normalize_text,
)


class TestNormalizeCardName:
    def test_basic(self):
        assert normalize_card_name("charizard") == "Charizard"
        assert normalize_card_name("UMBREON") == "Umbreon"

    def test_alias(self):
        assert normalize_card_name("evoli") == "Eevee"

    def test_compound(self):
        assert normalize_card_name("rayquaza") == "Rayquaza"


class TestNormalizeText:
    def test_accents(self):
        assert normalize_text("Pokémon") == "pokemon"
        assert normalize_text("  Múltiplos   espaços  ") == "multiplos espacos"


class TestDetectCard:
    def test_detects_card(self):
        cards = ["Charizard", "Pikachu", "Mew"]
        assert detect_card_in_text("Procuro um Charizard VMAX", cards) == "Charizard"
        assert detect_card_in_text("quero pikachu", cards) == "Pikachu"

    def test_not_found(self):
        cards = ["Charizard"]
        assert detect_card_in_text("procuro magic the gathering", cards) is None


class TestBuildSearchQuery:
    def test_with_suffix(self):
        query = build_search_query("Umbreon", "pokemon card")
        assert "Umbreon" in query
        assert "pokemon" in query
        assert "tcg" in query

    def test_without_suffix(self):
        query = build_search_query("Mew")
        assert "Mew" in query
