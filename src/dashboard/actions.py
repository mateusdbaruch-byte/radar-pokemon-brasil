"""Ações interativas da dashboard (ex.: rodar radar manualmente)."""

from __future__ import annotations

import os
from typing import Any

from src.incremental_radar import run_daily_radar
from src.search_budget import BudgetMode

DEFAULT_RADAR_CARDS = ["Charizard", "Umbreon", "Mew"]
DEFAULT_DAILY_BUDGET = 20
DEFAULT_BUDGET_MODE = BudgetMode.ECONOMY


def serpapi_configured() -> bool:
    return bool(os.getenv("SERPAPI_KEY", "").strip())


def run_manual_daily_radar(
    *,
    cards: list[str] | None = None,
    daily_budget: int = DEFAULT_DAILY_BUDGET,
    budget_mode: BudgetMode = DEFAULT_BUDGET_MODE,
) -> dict[str, Any]:
    """Executa run-daily-radar sem subprocess — retorna dict amigável para a UI."""
    if not serpapi_configured():
        return {
            "ok": False,
            "error": (
                "SerpAPI não configurada. Adicione SERPAPI_KEY nos Secrets "
                "(Replit) ou no arquivo .env local."
            ),
        }

    card_list = cards or list(DEFAULT_RADAR_CARDS)
    try:
        result = run_daily_radar(
            card_list,
            daily_budget=daily_budget,
            budget_mode=budget_mode,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    message = result.message
    if not message:
        if result.budget_stopped:
            message = "Orçamento diário atingido — o scan parou com segurança."
        elif result.queries_executed == 0:
            message = "Nenhuma query executada (orçamento esgotado ou plano vazio)."
        else:
            message = "Scan concluído."

    return {
        "ok": True,
        "scan_run_id": result.scan_run_id,
        "queries_executed": result.queries_executed,
        "saved": result.saved,
        "merged": result.merged,
        "rejected": result.rejected,
        "timeouts": result.timeouts,
        "budget_stopped": result.budget_stopped,
        "message": message,
        "cards": card_list,
        "daily_budget": daily_budget,
        "budget_mode": budget_mode.value,
    }
