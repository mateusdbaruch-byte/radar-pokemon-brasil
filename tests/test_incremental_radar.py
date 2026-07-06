"""Testes do radar incremental e alocação de orçamento."""

from __future__ import annotations

import pytest

from src.incremental_radar import build_run_plan
from src.opportunity_db import clear_opportunity_data, create_scan_run, finish_scan_run, fetch_scan_runs
from src.opportunity_models import Opportunity
from src.opportunity_quality import QualityFilterConfig, evaluate_hit, is_blocked_domain
from src.opportunity_scoring import score_opportunity
from src.freshness import apply_freshness_to_opportunity, serpapi_recency_param
from src.query_template_perf import QueryTemplateSpec, prioritized_templates
from src.search_budget import BudgetMode, allocate_profile_budget
from src.search_profiles import get_search_profile, load_search_profiles


class TestProfileBudgetAllocation:
    def test_economy_allocation_sums_to_budget(self):
        alloc = allocate_profile_budget(20, BudgetMode.ECONOMY)
        assert sum(alloc.values()) == 20
        assert alloc["demand_leads"] == 10
        assert alloc["market_reference"] == 4

    def test_market_focus_favors_reference(self):
        alloc = allocate_profile_budget(10, BudgetMode.MARKET_FOCUS)
        assert alloc["market_reference"] >= alloc["demand_leads"]


class TestBlockedDomains:
    def test_olx_pt_blocked(self):
        assert is_blocked_domain("https://www.olx.pt/anuncio")

    def test_amazon_not_globally_blocked(self):
        assert not is_blocked_domain("https://www.amazon.com.br/produto")


class TestDemandLeadsAmazonBlocked:
    def test_amazon_blocked_in_demand_leads(self):
        profile = get_search_profile("demand_leads")
        cfg = profile.to_quality_config()
        opp = score_opportunity(
            evidence="Compro Charizard Pokémon TCG",
            card_name="Charizard",
            source="web_search",
            platform="serpapi",
            url="https://www.amazon.com.br/charizard",
        )
        result = evaluate_hit(
            "Compro Charizard",
            "Compro Charizard Pokémon TCG carta",
            "https://www.amazon.com.br/charizard",
            "Charizard",
            opp,
            cfg,
        )
        assert result.accepted is False
        assert result.reason_category == "profile_blocked"


class TestTemplatePrioritization:
    def test_compro_ranks_high(self):
        profile = get_search_profile("demand_leads")
        specs = profile.prioritized_specs()
        assert specs[0].template.startswith('"compro')

    def test_disabled_template_excluded(self):
        raw = [
            {"template": '"compro {card}"', "enabled": True, "priority_weight": 100},
            {"template": '"alguem vende {card}"', "enabled": False, "priority_weight": 10},
        ]
        enabled = prioritized_templates("demand_leads", raw)
        assert len(enabled) == 1


class TestScanRuns:
    def test_scan_run_lifecycle(self, tmp_path):
        db = tmp_path / "scan.db"
        clear_opportunity_data(db)
        run_id = create_scan_run(
            profiles=["demand_leads"],
            cards=["Charizard"],
            budget_mode="economy",
            query_budget=10,
            queries_planned=10,
            db_path=db,
        )
        finish_scan_run(
            run_id,
            queries_executed=8,
            opportunities_saved=3,
            rejected_count=2,
            db_path=db,
        )
        runs = fetch_scan_runs(limit=1, db_path=db)
        assert runs[0].status == "completed"
        assert runs[0].opportunities_saved == 3


class TestFreshness:
    def test_unknown_reduces_confidence(self):
        opp = Opportunity(
            source="web_search",
            platform="serpapi",
            card_name_detected="Charizard",
            normalized_card_name="Charizard",
            confidence_score=80,
        )
        apply_freshness_to_opportunity(opp, title="Charizard", snippet="carta pokemon", recency_days=30)
        assert opp.freshness_status == "unknown"
        assert opp.confidence_score == 70

    def test_recency_param_month(self):
        assert serpapi_recency_param(30) == "qdr:m"


class TestRunPlan:
    def test_build_run_plan_structure(self):
        plan = build_run_plan(
            ["Charizard", "Mew"],
            daily_budget=10,
            budget_mode=BudgetMode.ECONOMY,
        )
        assert plan.total_planned <= 10
        assert len(plan.profiles) == 3
