"""Testes da camada de dados da dashboard."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.dashboard import charts, data
from src.opportunity_db import clear_opportunity_data, create_scan_run, finish_scan_run
from src.opportunity_models import Opportunity, OpportunityType
from src.opportunity_db import save_opportunity


@pytest.fixture
def dash_db(tmp_path):
    db = tmp_path / "dash.db"
    clear_opportunity_data(db)
    return db


class TestDashboardDataEmpty:
    def test_has_any_data_false_on_empty(self, dash_db):
        assert data.has_any_data(dash_db) is False

    def test_load_opportunities_empty(self, dash_db):
        df = data.load_opportunities(dash_db)
        assert df.empty

    def test_overview_metrics_zero(self, dash_db):
        m = data.overview_metrics(dash_db)
        assert m["total"] == 0
        assert m["budget_today"] == 0

    def test_distinct_cards_empty(self, dash_db):
        assert data.distinct_cards(dash_db) == []

    def test_charts_empty_df(self):
        import pandas as pd
        empty = pd.DataFrame()
        fig = charts.bar_chart(empty, "x", "y", "Teste")
        assert fig is not None


class TestDashboardDataWithRows:
    def test_load_opportunities(self, dash_db):
        opp = Opportunity(
            source="web_search",
            platform="serpapi",
            card_name_detected="Charizard",
            normalized_card_name="Charizard",
            opportunity_type=OpportunityType.BUYER_DEMAND,
            opportunity_score=90,
            confidence_score=85,
            profile="demand_leads",
            url="https://facebook.com/post/1",
            domain="facebook.com",
        )
        save_opportunity(opp, dash_db)
        df = data.load_opportunities(dash_db)
        assert len(df) == 1
        assert df.iloc[0]["display_id"] == 1
        assert data.has_any_data(dash_db) is True

    def test_card_radar_summary(self, dash_db):
        opp = Opportunity(
            source="web_search",
            platform="serpapi",
            card_name_detected="Mew",
            normalized_card_name="Mew",
            opportunity_type=OpportunityType.PRICE_REFERENCE,
            opportunity_score=70,
            profile="market_reference",
            url="https://ligapokemon.com.br/mew",
        )
        save_opportunity(opp, dash_db)
        summary = data.card_radar_summary("Mew", dash_db)
        assert summary["found"] is True
        assert summary["market_reference_count"] >= 1

    def test_scan_runs_load(self, dash_db):
        run_id = create_scan_run(
            profiles=["demand_leads"],
            cards=["Charizard"],
            budget_mode="economy",
            query_budget=10,
            queries_planned=10,
            db_path=dash_db,
        )
        finish_scan_run(run_id, queries_executed=5, opportunities_saved=2, rejected_count=1, db_path=dash_db)
        df = data.load_scan_runs(dash_db)
        assert len(df) == 1
        assert data.has_any_data(dash_db) is True


class TestDashboardImports:
    def test_app_module_imports(self):
        from src.dashboard import app as dashboard_app
        assert dashboard_app.PAGES
        assert "Visão Geral" in dashboard_app.PAGES
