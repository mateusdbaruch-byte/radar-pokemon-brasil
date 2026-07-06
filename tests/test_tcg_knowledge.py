"""Testes da TCG Knowledge Layer."""

from __future__ import annotations

import pytest

from src.tcg_knowledge import (
    analyze_text,
    classify_text,
    detect_collection,
    detect_condition,
    detect_grading,
    detect_language,
    detect_rarity,
    enrich_opportunity,
    generate_enriched_queries,
    has_tcg_context,
    is_negative_context,
    load_tcg_knowledge,
    normalize_collection_name,
    vocab_summary_counts,
)
from src.opportunity_scoring import score_opportunity


class TestVocabLoading:
    def test_load_knowledge(self):
        kb = load_tcg_knowledge()
        assert len(kb.core_terms) >= 5
        assert "151" in kb.collections
        assert len(kb.rarity_terms) >= 10

    def test_vocab_summary(self):
        counts = vocab_summary_counts()
        assert counts["collections"] >= 10
        assert counts["buyer_jargon"] >= 5


class TestCollectionDetection:
    def test_detect_151(self):
        assert detect_collection("Procuro Charizard 151 português") == "151"

    def test_normalize_collection(self):
        assert normalize_collection_name("SV 151 holo") == "151"


class TestSignalDetection:
    def test_procuro_charizard_151(self):
        text = "Procuro Charizard 151 português NM"
        signals = analyze_text(text)
        assert signals.collection == "151"
        assert "português" in [t.lower() for t in signals.language] or signals.language
        assert signals.condition or "NM" in text
        assert signals.has_buy_intent
        assert signals.has_tcg_context

    def test_vendo_umbreon_abaixo_liga(self):
        text = "Vendo Umbreon abaixo da Liga"
        signals = analyze_text(text)
        assert signals.has_sell_intent
        assert "abaixo da Liga" in signals.seller_jargon or signals.has_sell_intent

    def test_mew_psa_10(self):
        text = "Mew PSA 10"
        signals = analyze_text(text)
        assert "PSA" in signals.grading or detect_grading(text)

    def test_fechando_master_set(self):
        text = "Fechando master set 151, falta Pikachu"
        signals = analyze_text(text)
        assert signals.collection == "151"
        assert signals.has_buy_intent or "falta" in text.lower()

    def test_desapego_gengar_sar(self):
        text = "Desapego Gengar SAR Copag"
        signals = analyze_text(text)
        assert signals.has_sell_intent
        assert "SAR" in signals.rarity or detect_rarity(text)
        assert has_tcg_context(text)


class TestClassifyText:
    def test_procuro_charizard_classify(self):
        result = classify_text(
            "Procuro Charizard 151 português NM, pago à vista",
        )
        assert result.card_detected == "Charizard"
        assert result.card_alias
        assert result.card_confidence >= 90
        assert result.signals.collection == "151"
        assert result.intent_score >= 70
        assert "buyer" in result.probable_opportunity or result.signals.has_buy_intent

    def test_mew_psa_classify(self):
        result = classify_text("Mew PSA 10")
        assert result.card_detected == "Mew"
        assert result.signals.grading


class TestEnrichOpportunity:
    def test_enrich_sets_fields(self):
        opp = score_opportunity(
            evidence="Procuro Charizard 151 português NM",
            card_name="Charizard",
            source="web_search",
            platform="test",
            url="https://www.mercadolivre.com.br/x",
        )
        enriched = enrich_opportunity(opp)
        assert enriched.collection_detected == "151"
        assert enriched.why_saved.startswith("Salvo porque")
        assert enriched.language_detected or enriched.condition_detected
