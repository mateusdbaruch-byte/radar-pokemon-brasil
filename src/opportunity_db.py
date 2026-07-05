"""Persistência SQLite — opportunities e wishlist."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.opportunity_models import Opportunity, WishlistLead
from src.paths import DEFAULT_DB, ensure_data_dir

CREATE_OPPORTUNITIES_TABLE = """
CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    opportunity_type TEXT NOT NULL,
    source TEXT NOT NULL,
    platform TEXT NOT NULL,
    card_name_detected TEXT NOT NULL,
    normalized_card_name TEXT NOT NULL,
    evidence_text TEXT,
    url TEXT,
    author_or_seller TEXT,
    price REAL,
    currency TEXT DEFAULT 'BRL',
    intent_score INTEGER NOT NULL DEFAULT 0,
    urgency_score INTEGER NOT NULL DEFAULT 0,
    opportunity_score INTEGER NOT NULL DEFAULT 0,
    confidence_score INTEGER NOT NULL DEFAULT 0,
    data_mode TEXT NOT NULL DEFAULT 'live',
    status TEXT NOT NULL DEFAULT 'new',
    collected_at TEXT NOT NULL,
    raw_data_json TEXT,
    recommended_action TEXT
);
"""

CREATE_WISHLIST_TABLE = """
CREATE TABLE IF NOT EXISTS wishlist_leads (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    contact TEXT,
    card_name TEXT NOT NULL,
    collection TEXT,
    language TEXT DEFAULT 'pt-BR',
    condition TEXT,
    max_price REAL,
    urgency TEXT DEFAULT 'media',
    notes TEXT,
    source TEXT DEFAULT 'manual',
    created_at TEXT NOT NULL
);
"""

CREATE_OPP_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_opp_score ON opportunities(opportunity_score DESC);
CREATE INDEX IF NOT EXISTS idx_opp_card ON opportunities(normalized_card_name);
CREATE INDEX IF NOT EXISTS idx_opp_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_wishlist_card ON wishlist_leads(card_name);
"""


def _conn(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        CREATE_OPPORTUNITIES_TABLE + CREATE_WISHLIST_TABLE + CREATE_OPP_INDEXES
    )
    conn.commit()
    return conn


def save_opportunity(opp: Opportunity, db_path: Path | str = DEFAULT_DB) -> None:
    conn = _conn(db_path)
    row = opp.to_db_row()
    cols = ", ".join(row.keys())
    ph = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT OR REPLACE INTO opportunities ({cols}) VALUES ({ph})",
        list(row.values()),
    )
    conn.commit()
    conn.close()


def save_opportunities(
    opps: list[Opportunity],
    db_path: Path | str = DEFAULT_DB,
) -> int:
    for opp in opps:
        save_opportunity(opp, db_path)
    return len(opps)


def fetch_opportunities(
    db_path: Path | str = DEFAULT_DB,
    limit: int | None = None,
    status: str | None = None,
) -> list[Opportunity]:
    conn = _conn(db_path)
    sql = "SELECT * FROM opportunities"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY opportunity_score DESC, collected_at DESC"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [Opportunity.from_db_row(dict(r)) for r in rows]


def count_opportunities_by_source(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT source, COUNT(*) as cnt FROM opportunities GROUP BY source"
    ).fetchall()
    conn.close()
    return {r["source"]: r["cnt"] for r in rows}


def save_wishlist_lead(lead: WishlistLead, db_path: Path | str = DEFAULT_DB) -> None:
    conn = _conn(db_path)
    row = lead.to_db_row()
    cols = ", ".join(row.keys())
    ph = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT OR REPLACE INTO wishlist_leads ({cols}) VALUES ({ph})",
        list(row.values()),
    )
    conn.commit()
    conn.close()


def save_wishlist_leads(
    leads: list[WishlistLead],
    db_path: Path | str = DEFAULT_DB,
) -> int:
    for lead in leads:
        save_wishlist_lead(lead, db_path)
    return len(leads)


def fetch_wishlist_leads(db_path: Path | str = DEFAULT_DB) -> list[WishlistLead]:
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT * FROM wishlist_leads ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [WishlistLead.from_db_row(dict(r)) for r in rows]


def clear_opportunity_data(db_path: Path | str = DEFAULT_DB) -> None:
    conn = _conn(db_path)
    conn.execute("DELETE FROM opportunities")
    conn.execute("DELETE FROM wishlist_leads")
    conn.commit()
    conn.close()
