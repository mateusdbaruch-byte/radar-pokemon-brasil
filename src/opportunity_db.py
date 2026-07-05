"""Persistência SQLite — opportunities e wishlist."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

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
CREATE INDEX IF NOT EXISTS idx_opp_url ON opportunities(url);
CREATE INDEX IF NOT EXISTS idx_wishlist_card ON wishlist_leads(card_name);
"""


@dataclass
class SaveOpportunitiesResult:
    saved: int = 0
    merged: int = 0
    skipped_empty_url: int = 0
    urls_deduplicated: int = 0
    by_data_mode: dict[str, int] = field(default_factory=dict)


def _conn(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        CREATE_OPPORTUNITIES_TABLE + CREATE_WISHLIST_TABLE + CREATE_OPP_INDEXES
    )
    conn.commit()
    return conn


def normalize_url(url: str) -> str:
    """Normaliza URL para deduplicação (sem fragmento, sem barra final)."""
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, parsed.params, parsed.query, ""))


def fetch_opportunity_by_url(
    url: str,
    db_path: Path | str = DEFAULT_DB,
) -> Opportunity | None:
    norm = normalize_url(url)
    if not norm:
        return None
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE url IS NOT NULL AND url != ''"
    ).fetchall()
    conn.close()
    for row in rows:
        if normalize_url(row["url"]) == norm:
            return Opportunity.from_db_row(dict(row))
    return None


def _merge_opportunity(existing: Opportunity, incoming: Opportunity) -> Opportunity:
    """Mescla oportunidade duplicada por URL, preservando a de maior score."""
    base, extra = (
        (existing, incoming)
        if existing.opportunity_score >= incoming.opportunity_score
        else (incoming, existing)
    )

    try:
        raw = json.loads(base.raw_data_json or "{}")
    except json.JSONDecodeError:
        raw = {}

    try:
        extra_raw = json.loads(extra.raw_data_json or "{}")
    except json.JSONDecodeError:
        extra_raw = {}

    related = set(raw.get("related_cards", []))
    related.add(base.card_name_detected)
    related.add(extra.card_name_detected)
    for card in extra_raw.get("related_cards", []):
        related.add(card)
    raw["related_cards"] = sorted(c for c in related if c)

    evidence_extra = raw.setdefault("related_evidence", [])
    for item in extra_raw.get("related_evidence", []):
        if item not in evidence_extra:
            evidence_extra.append(item)
    snippet = f"[{extra.card_name_detected}] {extra.evidence_text[:200]}"
    if snippet not in evidence_extra:
        evidence_extra.append(snippet)

    if extra.card_name_detected.lower() not in base.evidence_text.lower():
        base.evidence_text = (
            f"{base.evidence_text}\n[{extra.card_name_detected}] "
            f"{extra.evidence_text[:300]}"
        ).strip()[:2000]

    base.set_raw_data(raw)
    return base


def save_opportunity(
    opp: Opportunity,
    db_path: Path | str = DEFAULT_DB,
    *,
    deduplicate_urls: bool = True,
) -> str:
    """Salva oportunidade. Retorna 'saved', 'merged' ou 'skipped'."""
    if deduplicate_urls and opp.url:
        existing = fetch_opportunity_by_url(opp.url, db_path)
        if existing:
            merged = _merge_opportunity(existing, opp)
            conn = _conn(db_path)
            row = merged.to_db_row()
            cols = ", ".join(row.keys())
            ph = ", ".join("?" for _ in row)
            conn.execute(
                f"INSERT OR REPLACE INTO opportunities ({cols}) VALUES ({ph})",
                list(row.values()),
            )
            conn.commit()
            conn.close()
            return "merged"

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
    return "saved"


def save_opportunities(
    opps: list[Opportunity],
    db_path: Path | str = DEFAULT_DB,
    *,
    deduplicate_urls: bool = True,
) -> SaveOpportunitiesResult:
    result = SaveOpportunitiesResult()
    seen_urls: set[str] = set()

    for opp in opps:
        mode_key = opp.data_mode.value if hasattr(opp.data_mode, "value") else str(opp.data_mode)
        norm = normalize_url(opp.url) if opp.url else ""

        if norm and norm in seen_urls:
            result.urls_deduplicated += 1
            continue

        action = save_opportunity(opp, db_path, deduplicate_urls=deduplicate_urls)
        if action == "merged":
            result.merged += 1
            if norm:
                seen_urls.add(norm)
        elif action == "saved":
            result.saved += 1
            if norm:
                seen_urls.add(norm)
        else:
            result.skipped_empty_url += 1

        result.by_data_mode[mode_key] = result.by_data_mode.get(mode_key, 0) + 1

    return result


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


def count_opportunities_by_data_mode(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT data_mode, COUNT(*) as cnt FROM opportunities GROUP BY data_mode"
    ).fetchall()
    conn.close()
    return {r["data_mode"]: r["cnt"] for r in rows}


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
