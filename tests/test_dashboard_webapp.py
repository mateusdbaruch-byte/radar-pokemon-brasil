"""Testes da dashboard webapp (ações, config, CLI webapp)."""

from __future__ import annotations

import pytest

from src.dashboard import actions, config_info
from src.search_budget import BudgetMode


class TestDashboardActions:
    def test_serpapi_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        assert actions.serpapi_configured() is False

    def test_serpapi_configured_with_key(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_KEY", "test-key")
        assert actions.serpapi_configured() is True

    def test_run_manual_daily_radar_without_key(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        result = actions.run_manual_daily_radar()
        assert result["ok"] is False
        assert "SERPAPI_KEY" in result["error"]

    def test_default_radar_params(self):
        assert actions.DEFAULT_RADAR_CARDS == ["Charizard", "Umbreon", "Mew"]
        assert actions.DEFAULT_DAILY_BUDGET == 20
        assert actions.DEFAULT_BUDGET_MODE == BudgetMode.ECONOMY


class TestDashboardConfigInfo:
    def test_app_config_summary_structure(self, monkeypatch):
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        monkeypatch.setenv("SERPAPI_DAILY_BUDGET", "15")
        cfg = config_info.app_config_summary()
        assert cfg["serpapi_configured"] is False
        assert cfg["daily_budget"] == 15
        assert len(cfg["profiles"]) == 3
        profile_ids = {p["id"] for p in cfg["profiles"]}
        assert profile_ids == {"demand_leads", "supply_deals", "market_reference"}
        assert any(name == "Charizard" for name, _ in cfg["watched_cards"])

    def test_app_config_summary_with_key(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_KEY", "secret")
        cfg = config_info.app_config_summary()
        assert cfg["serpapi_configured"] is True


class TestWebappCommand:
    def test_webapp_cmd_uses_host_0_0_0_0(self, monkeypatch):
        from src.main import webapp_cmd
        from src.paths import PROJECT_ROOT

        calls: list[dict] = []

        def fake_start(port=8501, *, address="localhost", headless=False):
            calls.append({"port": port, "address": address, "headless": headless})
            return 0

        monkeypatch.setattr("src.main._start_streamlit_server", fake_start)
        with pytest.raises(Exception) as exc:
            webapp_cmd(port=8501, host="0.0.0.0")
        assert exc.value.exit_code == 0
        assert calls[0]["address"] == "0.0.0.0"
        assert calls[0]["headless"] is True

    def test_dashboard_cmd_uses_localhost(self, monkeypatch):
        from src.main import dashboard_cmd

        calls: list[dict] = []

        def fake_start(port=8501, *, address="localhost", headless=False):
            calls.append({"address": address})
            return 0

        monkeypatch.setattr("src.main._start_streamlit_server", fake_start)
        with pytest.raises(Exception) as exc:
            dashboard_cmd(port=8501)
        assert exc.value.exit_code == 0
        assert calls[0]["address"] == "localhost"


class TestDashboardPages:
    def test_home_and_config_in_pages(self):
        from src.dashboard import app as dashboard_app

        assert "Início" in dashboard_app.PAGES
        assert "Configuração" in dashboard_app.PAGES
        assert dashboard_app.PAGES[0] == "Início"
