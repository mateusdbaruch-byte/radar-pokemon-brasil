"""Controle de orçamento e cache de buscas SerpAPI/web_search."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from rich.console import Console
from rich.panel import Panel

from src.opportunity_db import (
    count_budget_usage,
    count_budget_usage_by_card,
    count_budget_usage_by_profile,
    count_budget_usage_by_query,
    fetch_cached_query,
    get_last_profile_usage_today,
    record_budget_usage,
    save_query_cache,
)


class BudgetMode(str, Enum):
    NORMAL = "normal"
    ECONOMY = "economy"
    BALANCED = "balanced"
    MARKET_FOCUS = "market_focus"


PROFILE_BUDGET_SHARES: dict[BudgetMode, dict[str, float]] = {
    BudgetMode.ECONOMY: {
        "demand_leads": 0.50,
        "supply_deals": 0.30,
        "market_reference": 0.20,
    },
    BudgetMode.BALANCED: {
        "demand_leads": 0.40,
        "supply_deals": 0.30,
        "market_reference": 0.30,
    },
    BudgetMode.MARKET_FOCUS: {
        "demand_leads": 0.20,
        "supply_deals": 0.30,
        "market_reference": 0.50,
    },
}

DEFAULT_PROFILE_ORDER = ("demand_leads", "supply_deals", "market_reference")


def allocate_profile_budget(
    total_queries: int,
    budget_mode: BudgetMode,
    *,
    profiles: tuple[str, ...] = DEFAULT_PROFILE_ORDER,
) -> dict[str, int]:
    """Distribui orçamento de queries API entre perfis."""
    if total_queries <= 0:
        return {p: 0 for p in profiles}

    shares = PROFILE_BUDGET_SHARES.get(budget_mode)
    if not shares:
        per = max(1, total_queries // len(profiles))
        return {p: per for p in profiles}

    raw = {p: total_queries * shares.get(p, 0) for p in profiles}
    allocated = {p: int(raw[p]) for p in profiles}
    remainder = total_queries - sum(allocated.values())
    order = sorted(profiles, key=lambda p: raw[p] - allocated[p], reverse=True)
    idx = 0
    while remainder > 0 and order:
        allocated[order[idx % len(order)]] += 1
        remainder -= 1
        idx += 1
    return allocated


class BudgetExceededError(Exception):
    """Orçamento diário ou mensal atingido."""

    def __init__(self, message: str, *, remaining_daily: int = 0, remaining_monthly: int = 0):
        super().__init__(message)
        self.remaining_daily = remaining_daily
        self.remaining_monthly = remaining_monthly


@dataclass
class BudgetLimits:
    monthly_budget: int = 250
    daily_budget: int = 20
    stop_when_reached: bool = True

    @classmethod
    def from_env(cls) -> BudgetLimits:
        return cls(
            monthly_budget=int(os.getenv("SERPAPI_MONTHLY_BUDGET", "250")),
            daily_budget=int(os.getenv("SERPAPI_DAILY_BUDGET", "20")),
            stop_when_reached=os.getenv("SERPAPI_STOP_WHEN_BUDGET_REACHED", "true").lower()
            in ("1", "true", "yes"),
        )


@dataclass
class SearchBudgetContext:
    provider: str = ""
    profile: str = ""
    card: str = ""
    use_cache: bool = True
    no_cache: bool = False
    cache_ttl_hours: float = 24.0
    daily_budget: int | None = None
    monthly_budget: int | None = None
    stop_when_reached: bool | None = None
    budget_mode: BudgetMode = BudgetMode.NORMAL
    recency_days: int | None = None

    def effective_limits(self) -> BudgetLimits:
        base = BudgetLimits.from_env()
        if self.daily_budget is not None:
            base.daily_budget = self.daily_budget
        if self.monthly_budget is not None:
            base.monthly_budget = self.monthly_budget
        if self.stop_when_reached is not None:
            base.stop_when_reached = self.stop_when_reached
        return base

    @property
    def cache_enabled(self) -> bool:
        if self.no_cache:
            return False
        if self.budget_mode in (BudgetMode.ECONOMY, BudgetMode.BALANCED, BudgetMode.MARKET_FOCUS):
            return True
        return self.use_cache


@dataclass
class BudgetStatus:
    daily_used: int = 0
    monthly_used: int = 0
    daily_limit: int = 0
    monthly_limit: int = 0
    remaining_daily: int = 0
    remaining_monthly: int = 0
    allowed: bool = True
    message: str = ""


def get_budget_status(ctx: SearchBudgetContext | None = None) -> BudgetStatus:
    limits = (ctx or SearchBudgetContext()).effective_limits()
    daily_used = count_budget_usage(days=1, api_only=True)
    monthly_used = count_budget_usage(days=30, api_only=True)
    remaining_daily = max(0, limits.daily_budget - daily_used)
    remaining_monthly = max(0, limits.monthly_budget - monthly_used)
    allowed = remaining_daily > 0 and remaining_monthly > 0
    message = ""
    if not allowed:
        if remaining_daily <= 0:
            message = (
                f"Limite diário atingido ({daily_used}/{limits.daily_budget} buscas). "
                f"Restam {remaining_monthly} no mês."
            )
        else:
            message = (
                f"Limite mensal atingido ({monthly_used}/{limits.monthly_budget} buscas)."
            )
    return BudgetStatus(
        daily_used=daily_used,
        monthly_used=monthly_used,
        daily_limit=limits.daily_budget,
        monthly_limit=limits.monthly_budget,
        remaining_daily=remaining_daily,
        remaining_monthly=remaining_monthly,
        allowed=allowed,
        message=message,
    )


def assert_budget_available(ctx: SearchBudgetContext) -> BudgetStatus:
    limits = ctx.effective_limits()
    status = get_budget_status(ctx)
    if limits.stop_when_reached and not status.allowed:
        raise BudgetExceededError(status.message, remaining_daily=status.remaining_daily, remaining_monthly=status.remaining_monthly)
    return status


def check_profile_mix_economy(profile: str) -> str | None:
    """Economy: evita misturar market_reference com demand_leads no mesmo dia."""
    if profile != "market_reference":
        return None
    last = get_last_profile_usage_today(api_only=True)
    if last and last != "market_reference" and last in ("demand_leads", "supply_deals"):
        return (
            f"Modo economy: perfil '{last}' já usado hoje. "
            "Evite misturar market_reference com leads no mesmo dia."
        )
    return None


def economy_max_templates(total: int) -> int:
    return min(4, max(2, total // 2))


def economy_queries_per_card() -> int:
    return 3


def record_search(
    ctx: SearchBudgetContext,
    query: str,
    *,
    success: bool,
    results_count: int,
    cached: bool,
    cost_unit: int = 1,
) -> None:
    record_budget_usage(
        provider=ctx.provider or "unknown",
        profile=ctx.profile,
        card=ctx.card,
        query=query,
        success=success,
        results_count=results_count,
        cached=cached,
        cost_unit=0 if cached else cost_unit,
    )


def try_cache_hit(
    ctx: SearchBudgetContext,
    query: str,
    limit: int,
) -> list[dict] | None:
    if not ctx.cache_enabled:
        return None
    cached = fetch_cached_query(
        ctx.provider,
        query,
        limit,
        ttl_hours=ctx.cache_ttl_hours,
    )
    return cached


def store_cache(
    ctx: SearchBudgetContext,
    query: str,
    limit: int,
    hits: list[dict],
) -> None:
    if not hits:
        return
    save_query_cache(ctx.provider, query, limit, hits)


def estimate_monthly_pace(daily_avg: float) -> int:
    return int(round(daily_avg * 30))


def build_budget_recommendations(
    *,
    daily_used: int,
    monthly_used: int,
    daily_limit: int,
    monthly_limit: int,
    monthly_pace: int,
    top_profiles: list[tuple[str, int]],
) -> list[str]:
    tips: list[str] = []
    if monthly_pace > monthly_limit:
        tips.append(
            f"Ritmo atual (~{monthly_pace}/mês) excede o orçamento ({monthly_limit}). "
            "Use --budget-mode economy e --daily-budget."
        )
    if daily_used >= daily_limit * 0.8:
        tips.append("Próximo do limite diário — ative cache (padrão 24h) e reduza templates.")
    if top_profiles:
        top_name, top_count = top_profiles[0]
        if top_count > daily_used * 0.5 and daily_used > 3:
            tips.append(f"Perfil '{top_name}' consome mais buscas — rode perfis separadamente.")
    if not tips:
        tips.append("Consumo sob controle — use search-budget-report antes de cada scan.")
    tips.append("Plano gratuito: prefira scan com --budget-mode economy --limit 5.")
    return tips


def display_search_budget_report(console: Console) -> None:
    """Relatório de consumo de buscas API."""
    limits = BudgetLimits.from_env()
    today = count_budget_usage(days=1, api_only=True)
    week = count_budget_usage(days=7, api_only=True)
    month = count_budget_usage(days=30, api_only=True)
    cached_today = count_budget_usage(days=1, api_only=False, cached_only=True)
    pace = estimate_monthly_pace(week / 7.0 if week else today)
    status = get_budget_status()

    console.print("[bold blue]💰 Search Budget Report — SerpAPI[/bold blue]\n")

    console.print(Panel(
        f"[bold]Hoje (API):[/bold] {today} / {limits.daily_budget} "
        f"(restam {status.remaining_daily})\n"
        f"[bold]Últimos 7 dias (API):[/bold] {week}\n"
        f"[bold]Mês (API, 30d):[/bold] {month} / {limits.monthly_budget} "
        f"(restam {status.remaining_monthly})\n"
        f"[bold]Cache hits hoje:[/bold] {cached_today}\n"
        f"[bold]Estimativa/mês (ritmo 7d):[/bold] ~{pace} buscas",
        title="Consumo",
        border_style="blue",
    ))

    by_profile = count_budget_usage_by_profile(days=30, api_only=True)
    if by_profile:
        console.print("\n[bold]Perfis que mais consomem (30d)[/bold]")
        for name, cnt in list(by_profile.items())[:6]:
            console.print(f"  • {name or '(sem perfil)'}: {cnt}")

    by_card = count_budget_usage_by_card(days=30, api_only=True)
    if by_card:
        console.print("\n[bold]Cartas que mais consomem (30d)[/bold]")
        for card, cnt in list(by_card.items())[:6]:
            console.print(f"  • {card or '—'}: {cnt}")

    by_query = count_budget_usage_by_query(days=30, api_only=True)
    if by_query:
        console.print("\n[bold]Queries que mais consomem (30d)[/bold]")
        for query, cnt in list(by_query.items())[:6]:
            console.print(f"  • {query[:60]}: {cnt}")

    console.print("\n[bold]Recomendações[/bold]")
    for tip in build_budget_recommendations(
        daily_used=today,
        monthly_used=month,
        daily_limit=limits.daily_budget,
        monthly_limit=limits.monthly_budget,
        monthly_pace=pace,
        top_profiles=list(by_profile.items()) if by_profile else [],
    ):
        console.print(f"  • {tip}")
