"""Informações de configuração exibidas na dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from src.paths import DEFAULT_WATCHLIST, PROJECT_ROOT
from src.query_template_perf import ALL_PROFILES
from src.search_budget import BudgetLimits
from src.watchlist_loader import load_watchlist_entries

PROFILE_LABELS = {
    "demand_leads": "Compradores procurando cartas",
    "supply_deals": "Vendedores e desapegos",
    "market_reference": "Referência de preço em marketplaces",
}


def _load_profile_descriptions() -> dict[str, str]:
    path = PROJECT_ROOT / "config" / "search_profiles.yml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: dict[str, str] = {}
    for name in ALL_PROFILES:
        section = data.get(name) or {}
        out[name] = str(section.get("description", PROFILE_LABELS.get(name, name)))
    return out


def app_config_summary() -> dict[str, Any]:
    limits = BudgetLimits.from_env()
    watched = load_watchlist_entries(DEFAULT_WATCHLIST)
    descriptions = _load_profile_descriptions()
    provider = (os.getenv("WEB_SEARCH_PROVIDER") or "serpapi").strip().lower()

    return {
        "serpapi_configured": bool(os.getenv("SERPAPI_KEY", "").strip()),
        "web_search_provider": provider,
        "daily_budget": limits.daily_budget,
        "monthly_budget": limits.monthly_budget,
        "stop_when_reached": limits.stop_when_reached,
        "watched_cards": watched,
        "profiles": [
            {
                "id": name,
                "label": PROFILE_LABELS.get(name, name),
                "description": descriptions.get(name, ""),
            }
            for name in ALL_PROFILES
        ],
        "watchlist_path": str(Path(DEFAULT_WATCHLIST)),
    }
