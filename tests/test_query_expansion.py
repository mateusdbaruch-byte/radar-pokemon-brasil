"""Testes de expansão de queries enriquecidas."""

from __future__ import annotations

from src.connectors.web_search import ScanMode, WebSearchConnector
from src.tcg_knowledge import generate_enriched_queries


class TestQueryExpansion:
    def test_light_queries_contain_card(self):
        queries = generate_enriched_queries("Charizard", "light")
        assert len(queries) >= 4
        assert all("Charizard" in q for q in queries)

    def test_deep_more_than_light(self):
        light = generate_enriched_queries("Umbreon", "light")
        deep = generate_enriched_queries("Umbreon", "deep")
        assert len(deep) >= len(light)

    def test_buyer_only_queries(self):
        queries = generate_enriched_queries("Pikachu", "light", buyer_only=True)
        assert any("procuro" in q.lower() or "compro" in q.lower() for q in queries)
        assert not any(q.startswith("vendo") for q in queries)

    def test_seller_only_queries(self):
        queries = generate_enriched_queries("Gengar", "light", seller_only=True)
        assert any("vendo" in q.lower() or "desapego" in q.lower() for q in queries)

    def test_connector_uses_enriched_queries(self):
        connector = WebSearchConnector()
        queries = connector.get_queries_for_card("Charizard", ScanMode.LIGHT, buyer_only=True)
        assert len(queries) >= 3
        assert "Charizard" in queries[0]

    def test_queries_include_tcg_terms(self):
        queries = generate_enriched_queries("Charizard", "deep")
        joined = " ".join(queries).lower()
        assert "pokémon" in joined or "copag" in joined or "151" in joined
