"""Testes de orçamento e cache de buscas."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.connectors.web_search import WebSearchConnector, WebSearchHit
from src.opportunity_db import (
    clear_opportunity_data,
    count_budget_usage,
    fetch_cached_query,
    record_budget_usage,
    save_query_cache,
)
from src.search_budget import (
    BudgetExceededError,
    BudgetLimits,
    BudgetMode,
    SearchBudgetContext,
    assert_budget_available,
    economy_max_templates,
    get_budget_status,
)
from src.watchlist_loader import (
    filter_cards_for_economy,
    load_watchlist_cards,
    load_watchlist_entries,
    priorities_from_watchlist,
)


@pytest.fixture
def budget_db(tmp_path):
    db = tmp_path / "budget.db"
    clear_opportunity_data(db)
    return db


class TestWatchlistPriority:
    def test_load_entries_with_priority(self):
        entries = load_watchlist_entries(Path("config/watchlist.yml"))
        assert entries[0][0] in ("Charizard", "Umbreon")
        assert entries[0][1] == "high"

    def test_load_cards_backward_compat(self):
        cards = load_watchlist_cards(Path("config/watchlist.yml"))
        assert "Charizard" in cards

    def test_economy_filters_low_priority(self):
        cards = ["Charizard", "Lugia", "Umbreon"]
        prio = {"Charizard": "high", "Umbreon": "high", "Lugia": "low"}
        filtered = filter_cards_for_economy(cards, prio)
        assert "Lugia" not in filtered
        assert "Charizard" in filtered


class TestQueryCache:
    def test_cache_roundtrip(self, budget_db):
        hits = [{"title": "T", "snippet": "S", "url": "https://x.com"}]
        save_query_cache("serpapi", "procuro Charizard", 5, hits, budget_db)
        cached = fetch_cached_query("serpapi", "procuro Charizard", 5, db_path=budget_db)
        assert cached == hits

    def test_cache_miss_different_query(self, budget_db):
        save_query_cache("serpapi", "q1", 5, [{"title": "a", "snippet": "", "url": ""}], budget_db)
        assert fetch_cached_query("serpapi", "q2", 5, db_path=budget_db) is None


class TestBudgetUsage:
    def test_record_and_count_api_calls(self, budget_db):
        record_budget_usage(
            "serpapi", "q1", profile="demand_leads", card="Charizard",
            success=True, results_count=1, cached=False, cost_unit=1, db_path=budget_db,
        )
        record_budget_usage(
            "serpapi", "q1", profile="demand_leads", card="Charizard",
            success=True, results_count=1, cached=True, cost_unit=0, db_path=budget_db,
        )
        assert count_budget_usage(1, api_only=True, db_path=budget_db) == 1
        assert count_budget_usage(1, cached_only=True, db_path=budget_db) == 1

    def test_budget_limits_from_env(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_DAILY_BUDGET", "5")
        monkeypatch.setenv("SERPAPI_MONTHLY_BUDGET", "100")
        limits = BudgetLimits.from_env()
        assert limits.daily_budget == 5
        assert limits.monthly_budget == 100


class TestWebSearchCacheIntegration:
    def test_search_uses_cache_without_api(self, monkeypatch, budget_db):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "serpapi")
        monkeypatch.setenv("SERPAPI_KEY", "test-key")
        monkeypatch.setenv("SERPAPI_DAILY_BUDGET", "100")
        monkeypatch.setenv("WEB_SEARCH_DELAY_SECONDS", "0")

        from src.opportunity_db import save_query_cache as sqc
        sqc("serpapi", "procuro Mew", 3, [
            {"title": "Cached", "snippet": "hit", "url": "https://reddit.com/x"}
        ], budget_db)

        connector = WebSearchConnector()
        calls = {"n": 0}

        def fake_request(query, limit, timeout):
            calls["n"] += 1
            return 200, {}

        connector._provider_request = fake_request  # type: ignore[method-assign]

        ctx = SearchBudgetContext(
            provider="serpapi",
            profile="demand_leads",
            card="Mew",
            budget_mode=BudgetMode.NORMAL,
        )
        # Patch db path via monkeypatching module default - use direct cache in same db
        # Connector uses DEFAULT_DB - test with tmp by patching _conn
        from src import opportunity_db as odb
        original = odb.DEFAULT_DB
        odb.DEFAULT_DB = budget_db
        try:
            result = connector.search_query("procuro Mew", limit=3, budget_ctx=ctx)
        finally:
            odb.DEFAULT_DB = original

        assert result.cached is True
        assert result.success is True
        assert calls["n"] == 0
        assert result.hits[0].title == "Cached"


class TestBudgetExceeded:
    def test_stops_when_daily_limit_reached(self, budget_db, monkeypatch):
        monkeypatch.setenv("SERPAPI_DAILY_BUDGET", "1")
        monkeypatch.setenv("SERPAPI_MONTHLY_BUDGET", "100")
        monkeypatch.setenv("SERPAPI_STOP_WHEN_BUDGET_REACHED", "true")
        record_budget_usage("serpapi", "q", cost_unit=1, db_path=budget_db)
        from src import opportunity_db as odb
        original = odb.DEFAULT_DB
        odb.DEFAULT_DB = budget_db
        try:
            ctx = SearchBudgetContext(no_cache=True)
            with pytest.raises(BudgetExceededError):
                assert_budget_available(ctx)
        finally:
            odb.DEFAULT_DB = original


class TestEconomyHelpers:
    def test_economy_max_templates(self):
        assert economy_max_templates(12) == 4
        assert economy_max_templates(4) == 2
