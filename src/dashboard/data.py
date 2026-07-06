"""Camada de dados read-only da dashboard — SQLite → pandas."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.connector_health import fetch_latest_by_source
from src.opportunity_quality import extract_domain
from src.opportunity_reporting import (
    BUYER_DEMAND_TYPES,
    MARKET_REFERENCE_TYPES,
    SELLER_SUPPLY_TYPES,
    build_card_unified_stats,
)
from src.opportunity_db import (
    count_budget_usage,
    count_budget_usage_by_card,
    count_budget_usage_by_profile,
    count_budget_usage_by_query,
)
from src.paths import DEFAULT_DB, ensure_data_dir
from src.search_budget import BudgetLimits

BUYER_TYPE_VALUES = {t.value for t in BUYER_DEMAND_TYPES}
SELLER_TYPE_VALUES = {t.value for t in SELLER_SUPPLY_TYPES}
REFERENCE_TYPE_VALUES = {t.value for t in MARKET_REFERENCE_TYPES}


def db_path(path: Path | str | None = None) -> Path:
    return Path(path) if path else DEFAULT_DB


def database_exists(path: Path | str | None = None) -> bool:
    return db_path(path).exists()


def _connect(path: Path | str | None = None) -> sqlite3.Connection:
    ensure_data_dir()
    p = db_path(path)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(table: str, path: Path | str | None = None) -> bool:
    if not database_exists(path):
        return False
    conn = _connect(path)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    conn.close()
    return row is not None


def read_table(table: str, path: Path | str | None = None) -> pd.DataFrame:
    if not table_exists(table, path):
        return pd.DataFrame()
    conn = _connect(path)
    try:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def has_any_data(path: Path | str | None = None) -> bool:
    if not database_exists(path):
        return False
    for table in (
        "opportunities",
        "rejected_results",
        "query_runs",
        "scan_runs",
        "search_budget_usage",
    ):
        df = read_table(table, path)
        if not df.empty:
            return True
    return False


def load_opportunities(path: Path | str | None = None) -> pd.DataFrame:
    df = read_table("opportunities", path)
    if df.empty:
        return df
    if "domain" not in df.columns or df["domain"].isna().all():
        df["domain"] = df.get("url", pd.Series(dtype=str)).apply(
            lambda u: extract_domain(str(u)) if u else ""
        )
    df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce", utc=True)
    df = df.sort_values("opportunity_score", ascending=False)
    df.insert(0, "display_id", range(1, len(df) + 1))
    return df


def load_rejected(path: Path | str | None = None) -> pd.DataFrame:
    df = read_table("rejected_results", path)
    if df.empty:
        return df
    df["domain"] = df.get("url", pd.Series(dtype=str)).apply(
        lambda u: extract_domain(str(u)) if u else ""
    )
    df["rejected_at"] = pd.to_datetime(df["rejected_at"], errors="coerce", utc=True)
    return df


def load_query_runs(path: Path | str | None = None) -> pd.DataFrame:
    df = read_table("query_runs", path)
    if df.empty:
        return df
    df["executed_at"] = pd.to_datetime(df["executed_at"], errors="coerce", utc=True)
    total = df["saved_count"].fillna(0) + df["rejected_count"].fillna(0)
    df["success_rate"] = (df["saved_count"].fillna(0) / total.replace(0, pd.NA) * 100).round(1)
    return df.sort_values("executed_at", ascending=False)


def load_scan_runs(path: Path | str | None = None) -> pd.DataFrame:
    df = read_table("scan_runs", path)
    if df.empty:
        return df
    df["started_at"] = pd.to_datetime(df["started_at"], errors="coerce", utc=True)
    if "finished_at" in df.columns:
        df["finished_at"] = pd.to_datetime(df["finished_at"], errors="coerce", utc=True)
    return df.sort_values("started_at", ascending=False)


def load_budget_usage(path: Path | str | None = None) -> pd.DataFrame:
    return read_table("search_budget_usage", path)


def load_connector_health(path: Path | str | None = None) -> pd.DataFrame:
    rows = fetch_latest_by_source(db_path(path))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["tested_at"] = pd.to_datetime(df["tested_at"], errors="coerce", utc=True)
    return df


def overview_metrics(path: Path | str | None = None) -> dict[str, Any]:
    opps = load_opportunities(path)
    limits = BudgetLimits.from_env()
    today_api = count_budget_usage(1, api_only=True, db_path=db_path(path))
    month_api = count_budget_usage(30, api_only=True, db_path=db_path(path))

    if opps.empty:
        return {
            "total": 0,
            "new_status": 0,
            "buyer_demand": 0,
            "seller_supply": 0,
            "price_reference": 0,
            "urgent_sale": 0,
            "live": 0,
            "opt_in": 0,
            "last_7_days": 0,
            "budget_today": today_api,
            "budget_month": month_api,
            "budget_daily_limit": limits.daily_budget,
            "budget_monthly_limit": limits.monthly_budget,
        }

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    types = opps["opportunity_type"].fillna("")

    return {
        "total": len(opps),
        "new_status": int((opps["status"] == "new").sum()) if "status" in opps.columns else 0,
        "buyer_demand": int(types.isin(BUYER_TYPE_VALUES).sum()),
        "seller_supply": int(types.isin(SELLER_TYPE_VALUES).sum()),
        "price_reference": int(types.isin(REFERENCE_TYPE_VALUES).sum()),
        "urgent_sale": int((types == "urgent_sale").sum()),
        "live": int((opps["data_mode"] == "live").sum()) if "data_mode" in opps.columns else 0,
        "opt_in": int((opps["data_mode"] == "opt_in").sum()) if "data_mode" in opps.columns else 0,
        "last_7_days": int((opps["collected_at"] >= week_ago).sum()),
        "budget_today": today_api,
        "budget_month": month_api,
        "budget_daily_limit": limits.daily_budget,
        "budget_monthly_limit": limits.monthly_budget,
    }


def opportunities_by_day(path: Path | str | None = None) -> pd.DataFrame:
    opps = load_opportunities(path)
    if opps.empty or opps["collected_at"].isna().all():
        return pd.DataFrame(columns=["date", "count"])
    daily = (
        opps.dropna(subset=["collected_at"])
        .assign(date=lambda d: d["collected_at"].dt.date)
        .groupby("date")
        .size()
        .reset_index(name="count")
        .sort_values("date")
    )
    return daily


def count_series(
    opps: pd.DataFrame,
    column: str,
    top_n: int = 10,
) -> pd.DataFrame:
    if opps.empty or column not in opps.columns:
        return pd.DataFrame(columns=[column, "count"])
    counts = (
        opps[column].fillna("—")
        .replace("", "—")
        .value_counts()
        .head(top_n)
        .reset_index()
    )
    counts.columns = [column, "count"]
    return counts


def card_radar_summary(card: str, path: Path | str | None = None) -> dict[str, Any]:
    from src.opportunity_db import fetch_opportunities_by_card

    model_opps = fetch_opportunities_by_card(card, db_path(path))
    if not model_opps:
        return {"card": card, "found": False}

    stats = build_card_unified_stats(card, model_opps)
    card_opps = load_opportunities(path)
    card_opps = card_opps[
        (card_opps["normalized_card_name"] == card) | (card_opps["card_name_detected"] == card)
    ] if not card_opps.empty else card_opps

    return {
        "card": card,
        "found": True,
        "buyer_demand_count": stats.buyer_demand_count,
        "seller_supply_count": stats.seller_supply_count,
        "market_reference_count": stats.market_reference_count,
        "urgent_sale_count": stats.urgent_sale_count,
        "market_opportunity_score": stats.market_opportunity_score,
        "strategic_reading": stats.strategic_reading,
        "top_domains": stats.top_domains,
        "top_opportunities": card_opps.head(10),
    }


def budget_summary(path: Path | str | None = None) -> dict[str, Any]:
    limits = BudgetLimits.from_env()
    p = db_path(path)
    week = count_budget_usage(7, api_only=True, db_path=p)
    month = count_budget_usage(30, api_only=True, db_path=p)
    today = count_budget_usage(1, api_only=True, db_path=p)
    cached_today = count_budget_usage(1, cached_only=True, db_path=p)
    pace = int(round(week / 7.0 * 30)) if week else today * 30
    return {
        "today": today,
        "week": week,
        "month": month,
        "cached_today": cached_today,
        "daily_limit": limits.daily_budget,
        "monthly_limit": limits.monthly_budget,
        "monthly_pace": pace,
        "by_profile": count_budget_usage_by_profile(30, api_only=True, db_path=p),
        "by_card": count_budget_usage_by_card(30, api_only=True, db_path=p),
        "by_query": count_budget_usage_by_query(30, api_only=True, db_path=p),
    }


def distinct_cards(path: Path | str | None = None) -> list[str]:
    opps = load_opportunities(path)
    if opps.empty:
        return []
    cards = sorted(
        set(opps["normalized_card_name"].dropna().tolist())
        | set(opps["card_name_detected"].dropna().tolist())
    )
    return [c for c in cards if c]
