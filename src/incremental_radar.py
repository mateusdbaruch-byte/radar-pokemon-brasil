"""Execução incremental do Opportunity Radar com orçamento por perfil."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from src.connectors.web_search import WebSearchConfig, WebSearchConnector
from src.opportunity_db import (
    create_scan_run,
    fetch_cached_query,
    fetch_query_runs,
    finish_scan_run,
    save_opportunities,
)
from src.query_template_perf import ALL_PROFILES, update_stats_from_query_runs
from src.search_budget import (
    BudgetMode,
    SearchBudgetContext,
    allocate_profile_budget,
    get_budget_status,
)
from src.search_profiles import (
    get_search_profile,
    profiles_template_config,
)


@dataclass
class PlannedQuery:
    profile: str
    card: str
    query: str
    from_cache: bool = False


@dataclass
class ProfilePlan:
    profile: str
    query_budget: int
    queries: list[PlannedQuery] = field(default_factory=list)


@dataclass
class RunPlan:
    cards: list[str]
    budget_mode: BudgetMode
    daily_budget: int
    effective_budget: int
    profiles: list[ProfilePlan] = field(default_factory=list)
    cache_hits: int = 0
    api_calls_estimated: int = 0

    @property
    def total_planned(self) -> int:
        return sum(len(p.queries) for p in self.profiles)

    def all_queries(self) -> list[PlannedQuery]:
        out: list[PlannedQuery] = []
        for p in self.profiles:
            out.extend(p.queries)
        return out


def _effective_daily_budget(requested: int) -> int:
    status = get_budget_status()
    remaining = status.remaining_daily if status.remaining_daily > 0 else requested
    return max(0, min(requested, remaining))


def _provider_name() -> str:
    return os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower() or "serpapi"


def _build_profile_queries(
    profile_name: str,
    cards: list[str],
    budget: int,
    *,
    limit_per_query: int,
    cache_ttl_hours: float,
    provider: str,
) -> ProfilePlan:
    profile = get_search_profile(profile_name)
    plan = ProfilePlan(profile=profile_name, query_budget=budget)
    if not profile or budget <= 0:
        return plan

    specs = profile.prioritized_specs()
    if not specs:
        return plan

    idx = 0
    spec_i = 0
    card_i = 0
    seen_queries: set[str] = set()
    max_attempts = budget * max(len(specs), 1) * max(len(cards), 1) * 2

    while len(plan.queries) < budget and idx < max_attempts:
        idx += 1
        card = cards[card_i % len(cards)]
        spec = specs[spec_i % len(specs)]
        query = spec.template.format(card=card)
        card_i += 1
        spec_i += 1
        if query in seen_queries:
            continue
        seen_queries.add(query)
        cached = fetch_cached_query(
            provider, query, limit_per_query, ttl_hours=cache_ttl_hours,
        )
        plan.queries.append(
            PlannedQuery(
                profile=profile_name,
                card=card,
                query=query,
                from_cache=cached is not None,
            )
        )

    return plan


def build_run_plan(
    cards: list[str],
    *,
    daily_budget: int = 20,
    budget_mode: BudgetMode = BudgetMode.ECONOMY,
    limit_per_query: int = 5,
    cache_ttl_hours: float = 24.0,
    profiles: tuple[str, ...] = ALL_PROFILES,
) -> RunPlan:
    effective = _effective_daily_budget(daily_budget)
    allocation = allocate_profile_budget(effective, budget_mode, profiles=profiles)
    provider = _provider_name()

    plan = RunPlan(
        cards=cards,
        budget_mode=budget_mode,
        daily_budget=daily_budget,
        effective_budget=effective,
    )

    cache_hits = 0
    api_est = 0
    for profile_name in profiles:
        budget = allocation.get(profile_name, 0)
        pplan = _build_profile_queries(
            profile_name,
            cards,
            budget,
            limit_per_query=limit_per_query,
            cache_ttl_hours=cache_ttl_hours,
            provider=provider,
        )
        plan.profiles.append(pplan)
        for q in pplan.queries:
            if q.from_cache:
                cache_hits += 1
            else:
                api_est += 1

    plan.cache_hits = cache_hits
    plan.api_calls_estimated = api_est
    return plan


@dataclass
class DailyRadarResult:
    scan_run_id: str
    plan: RunPlan
    saved: int = 0
    merged: int = 0
    rejected: int = 0
    timeouts: int = 0
    queries_executed: int = 0
    budget_stopped: bool = False
    message: str = ""


def run_daily_radar(
    cards: list[str],
    *,
    daily_budget: int = 20,
    budget_mode: BudgetMode = BudgetMode.ECONOMY,
    limit_per_query: int = 5,
    cache_ttl_hours: float = 24.0,
    recency_days: int = 30,
    no_cache: bool = False,
    on_progress=None,
) -> DailyRadarResult:
    profiles = list(ALL_PROFILES)
    plan = build_run_plan(
        cards,
        daily_budget=daily_budget,
        budget_mode=budget_mode,
        limit_per_query=limit_per_query,
        cache_ttl_hours=cache_ttl_hours,
    )

    run_id = create_scan_run(
        profiles=profiles,
        cards=cards,
        budget_mode=budget_mode.value,
        query_budget=plan.effective_budget,
        queries_planned=plan.total_planned,
    )

    result = DailyRadarResult(scan_run_id=run_id, plan=plan)
    if plan.effective_budget <= 0:
        result.budget_stopped = True
        result.message = "Orçamento diário esgotado — nenhuma query planejada."
        finish_scan_run(
            run_id,
            queries_executed=0,
            opportunities_saved=0,
            rejected_count=0,
            status="budget_exhausted",
        )
        return result

    connector = WebSearchConnector(config=WebSearchConfig.from_env())
    if not connector.is_configured():
        result.message = "web_search não configurado"
        finish_scan_run(run_id, 0, 0, 0, status="failed")
        return result

    all_opps = []
    total_rejected = 0
    total_timeouts = 0
    queries_executed = 0

    for profile_plan in plan.profiles:
        if not profile_plan.queries:
            continue
        profile = get_search_profile(profile_plan.profile)
        if not profile:
            continue

        templates = [s.template for s in profile.prioritized_specs()]
        planned = [(q.card, q.query) for q in profile_plan.queries]

        budget_ctx = SearchBudgetContext(
            provider=connector.provider,
            profile=profile_plan.profile,
            no_cache=no_cache,
            cache_ttl_hours=cache_ttl_hours,
            daily_budget=daily_budget,
            budget_mode=budget_mode,
            recency_days=recency_days,
        )

        scan = connector.scan_cards(
            cards,
            limit_per_query=limit_per_query,
            quality_config=profile.to_quality_config(),
            profile_name=profile_plan.profile,
            query_templates=templates,
            budget_ctx=budget_ctx,
            max_queries=len(planned),
            planned_queries=planned,
            recency_days=recency_days,
            on_progress=on_progress,
        )

        stats = scan.stats
        queries_executed += stats.queries_executed
        total_rejected += stats.results_rejected
        total_timeouts += stats.queries_timeout
        all_opps.extend(scan.opportunities)

        if stats.budget_stopped:
            result.budget_stopped = True
            result.message = stats.budget_message
            break

    save_result = save_opportunities(all_opps) if all_opps else None
    result.saved = save_result.saved if save_result else 0
    result.merged = save_result.merged if save_result else 0
    result.rejected = total_rejected
    result.timeouts = total_timeouts
    result.queries_executed = queries_executed

    update_stats_from_query_runs(
        fetch_query_runs(limit=500),
        profiles_template_config(),
    )

    finish_scan_run(
        run_id,
        queries_executed=queries_executed,
        opportunities_saved=result.saved + result.merged,
        rejected_count=total_rejected,
        timeout_count=total_timeouts,
        status="budget_stopped" if result.budget_stopped else "completed",
    )
    return result
