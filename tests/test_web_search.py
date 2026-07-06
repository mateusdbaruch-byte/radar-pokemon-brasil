"""Testes do conector web_search e estabilização do scan."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.connectors.web_search import (
    DEEP_QUERY_TEMPLATES,
    LIGHT_QUERY_TEMPLATES,
    ScanMode,
    WebSearchConfig,
    WebSearchConnector,
    WebSearchHit,
)
from src.models import DataMode
from src.opportunity_db import (
    fetch_opportunity_by_url,
    normalize_url,
    save_opportunities,
    save_opportunity,
)
from src.opportunity_models import Opportunity, OpportunityType
from src.opportunity_scoring import score_opportunity, wishlist_lead_to_opportunity
from src.opportunity_models import WishlistLead
from src.opportunity_scanner import scan_opportunities


class TestWebSearchConfig:
    def test_from_env_defaults(self, monkeypatch):
        monkeypatch.delenv("WEB_SEARCH_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("WEB_SEARCH_DELAY_SECONDS", raising=False)
        monkeypatch.delenv("WEB_SEARCH_MAX_RETRIES", raising=False)
        monkeypatch.delenv("WEB_SEARCH_MAX_QUERIES_PER_RUN", raising=False)
        cfg = WebSearchConfig.from_env(ScanMode.LIGHT)
        assert cfg.timeout_seconds == 20.0
        assert cfg.delay_seconds == 2.0
        assert cfg.max_retries == 2
        assert cfg.max_queries_per_run == 20

    def test_deep_mode_doubles_delay(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_DELAY_SECONDS", "2")
        light = WebSearchConfig.from_env(ScanMode.LIGHT)
        deep = WebSearchConfig.from_env(ScanMode.DEEP)
        assert deep.delay_seconds == light.delay_seconds * 2


class TestWebSearchTemplates:
    def test_light_has_four_templates(self):
        assert len(LIGHT_QUERY_TEMPLATES) == 4

    def test_deep_has_more_than_light(self):
        assert len(DEEP_QUERY_TEMPLATES) > len(LIGHT_QUERY_TEMPLATES)


class TestWebSearchRetry:
  def test_retries_on_timeout(self, monkeypatch):
      monkeypatch.setenv("WEB_SEARCH_PROVIDER", "serpapi")
      monkeypatch.setenv("SERPAPI_KEY", "test-key")
      monkeypatch.setenv("WEB_SEARCH_MAX_RETRIES", "2")
      monkeypatch.setenv("WEB_SEARCH_DELAY_SECONDS", "0")
      monkeypatch.setenv("SERPAPI_DAILY_BUDGET", "1000")

      connector = WebSearchConnector(
          config=WebSearchConfig(timeout_seconds=1, delay_seconds=0, max_retries=2)
      )

      call_count = {"n": 0}

      def fake_request(query, limit, timeout, recency_days=None):
          call_count["n"] += 1
          raise requests.Timeout("timed out")

      connector._provider_request = fake_request  # type: ignore[method-assign]
      result = connector.search_query("procuro Charizard", limit=3)

      assert result.timed_out is True
      assert result.success is False
      assert call_count["n"] == 3  # initial + 2 retries
      assert result.retries == 2

  def test_success_without_retry(self, monkeypatch):
      monkeypatch.setenv("WEB_SEARCH_PROVIDER", "serpapi")
      monkeypatch.setenv("SERPAPI_KEY", "test-key")
      monkeypatch.setenv("SERPAPI_DAILY_BUDGET", "1000")

      connector = WebSearchConnector(
          config=WebSearchConfig(timeout_seconds=5, delay_seconds=0, max_retries=2)
      )

      def fake_request(query, limit, timeout, recency_days=None):
          return 200, {
              "organic_results": [
                  {"title": "Procuro Charizard", "snippet": "compro", "link": "https://ex.com/a"},
              ]
          }

      connector._provider_request = fake_request  # type: ignore[method-assign]
      result = connector.search_query("procuro Charizard", limit=5)

      assert result.success is True
      assert len(result.hits) == 1
      assert result.hits[0].url == "https://ex.com/a"


class TestWebSearchScan:
    def test_scan_respects_max_queries(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "serpapi")
        monkeypatch.setenv("SERPAPI_KEY", "test-key")
        monkeypatch.setenv("WEB_SEARCH_DELAY_SECONDS", "0")

        connector = WebSearchConnector(
            config=WebSearchConfig(delay_seconds=0, max_queries_per_run=20)
        )

        queries_seen: list[str] = []

        def mock_search_query(query, limit=10, budget_ctx=None):
            queries_seen.append(query)
            from src.connectors.web_search import WebSearchQueryResult
            return WebSearchQueryResult(query=query, success=True, hits=[])

        connector.search_query = mock_search_query  # type: ignore[method-assign]
        scan = connector.scan_cards(
            ["Charizard", "Pikachu"],
            mode=ScanMode.LIGHT,
            max_queries=3,
        )

        assert scan.stats.queries_executed == 3
        assert len(queries_seen) == 3

    def test_scan_dedup_urls_across_cards(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "serpapi")
        monkeypatch.setenv("SERPAPI_KEY", "test-key")
        monkeypatch.setenv("WEB_SEARCH_DELAY_SECONDS", "0")

        connector = WebSearchConnector(config=WebSearchConfig(delay_seconds=0))

        shared_hit = WebSearchHit(
            title="Oferta Charizard Pokémon TCG",
            snippet="vendo carta holo procuro compradores",
            url="https://ex.com/shared",
        )

        def mock_search_query(query, limit=10, budget_ctx=None):
            from src.connectors.web_search import WebSearchQueryResult
            return WebSearchQueryResult(query=query, success=True, hits=[shared_hit])

        connector.search_query = mock_search_query  # type: ignore[method-assign]
        scan = connector.scan_cards(
            ["Charizard"],
            mode=ScanMode.LIGHT,
            max_queries=2,
        )

        assert len(scan.opportunities) == 1
        assert scan.stats.urls_deduplicated == 1
        raw = json.loads(scan.opportunities[0].raw_data_json)
        assert "Charizard" in raw.get("related_cards", [])


class TestUrlDedupDb:
    def test_normalize_url_strips_trailing_slash(self):
        assert normalize_url("https://Example.com/path/") == normalize_url(
            "https://example.com/path"
        )

    def test_save_merges_same_url(self, tmp_path):
        db = tmp_path / "radar.db"
        opp1 = score_opportunity(
            evidence="Procuro Charizard",
            card_name="Charizard",
            source="web_search",
            platform="serpapi",
            url="https://example.com/post/1",
        )
        opp1.data_mode = DataMode.LIVE
        opp2 = score_opportunity(
            evidence="Compro Pikachu",
            card_name="Pikachu",
            source="web_search",
            platform="serpapi",
            url="https://example.com/post/1/",
        )
        opp2.data_mode = DataMode.LIVE

        assert save_opportunity(opp1, db) == "saved"
        assert save_opportunity(opp2, db) == "merged"

        stored = fetch_opportunity_by_url("https://example.com/post/1", db)
        assert stored is not None
        raw = json.loads(stored.raw_data_json)
        assert "Charizard" in raw.get("related_cards", [])
        assert "Pikachu" in raw.get("related_cards", [])

    def test_save_opportunities_result(self, tmp_path):
        db = tmp_path / "radar.db"
        opp = score_opportunity(
            evidence="test",
            card_name="Mew",
            source="web_search",
            platform="test",
            url="https://example.com/mew",
        )
        result = save_opportunities([opp], db)
        assert result.saved == 1


class TestWishlistOptIn:
    def test_wishlist_data_mode_opt_in(self):
        lead = WishlistLead(name="Ana", card_name="Umbreon", urgency="alta")
        opp = wishlist_lead_to_opportunity(lead)
        assert opp.data_mode == DataMode.OPT_IN


class TestScanOpportunitiesModes:
    def test_scan_wishlist_only(self):
        result = scan_opportunities(["Charizard"], "wishlist", limit=5, mode=ScanMode.LIGHT)
        assert isinstance(result.skipped_sources, list)

    def test_scan_does_not_crash_on_web_search_timeout(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "serpapi")
        monkeypatch.setenv("SERPAPI_KEY", "test-key")
        monkeypatch.setenv("WEB_SEARCH_DELAY_SECONDS", "0")

        connector = WebSearchConnector(config=WebSearchConfig(delay_seconds=0, max_retries=0))

        def mock_search_query(self, query, limit=10, budget_ctx=None):
            from src.connectors.web_search import WebSearchQueryResult
            return WebSearchQueryResult(query=query, timed_out=True, error="timeout")

        with patch.object(WebSearchConnector, "search_query", mock_search_query):
            result = scan_opportunities(
                ["Charizard"],
                "web_search",
                limit=3,
                mode=ScanMode.LIGHT,
                max_queries=2,
            )

        assert result.web_search_stats is not None
        assert result.web_search_stats.queries_timeout == 2
        assert result.opportunities == []
