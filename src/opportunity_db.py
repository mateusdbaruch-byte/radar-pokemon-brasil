"""Persistência SQLite — opportunities e wishlist."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from src.opportunity_models import Opportunity, WishlistLead
from src.opportunity_quality import extract_domain
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
    recommended_action TEXT,
    why_saved TEXT DEFAULT '',
    collection_detected TEXT DEFAULT '',
    rarity_detected TEXT DEFAULT '',
    condition_detected TEXT DEFAULT '',
    grading_detected TEXT DEFAULT '',
    language_detected TEXT DEFAULT '',
    market_jargon_detected TEXT DEFAULT '',
    negative_context_detected TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    human_review TEXT DEFAULT '',
    human_review_notes TEXT DEFAULT '',
    reviewed_at TEXT,
    profile TEXT DEFAULT '',
    freshness_status TEXT DEFAULT 'unknown',
    detected_date TEXT,
    age_days INTEGER
);
"""

CREATE_SCAN_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL DEFAULT 'daily_radar',
    profiles TEXT NOT NULL DEFAULT '',
    cards TEXT NOT NULL DEFAULT '',
    budget_mode TEXT NOT NULL DEFAULT 'economy',
    query_budget INTEGER NOT NULL DEFAULT 0,
    queries_planned INTEGER NOT NULL DEFAULT 0,
    queries_executed INTEGER NOT NULL DEFAULT 0,
    opportunities_saved INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    timeout_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);
"""

CREATE_REJECTED_TABLE = """
CREATE TABLE IF NOT EXISTS rejected_results (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    url TEXT,
    reason TEXT NOT NULL,
    rejected_at TEXT NOT NULL
);
"""

CREATE_QUERY_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS query_runs (
    id TEXT PRIMARY KEY,
    profile TEXT NOT NULL DEFAULT '',
    card TEXT NOT NULL,
    query TEXT NOT NULL,
    total_results INTEGER NOT NULL DEFAULT 0,
    saved_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    timeout_count INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    executed_at TEXT NOT NULL,
    domains_found TEXT DEFAULT ''
);
"""

CREATE_SEARCH_BUDGET_TABLE = """
CREATE TABLE IF NOT EXISTS search_budget_usage (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    profile TEXT DEFAULT '',
    card TEXT DEFAULT '',
    query TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    results_count INTEGER NOT NULL DEFAULT 0,
    cached INTEGER NOT NULL DEFAULT 0,
    cost_unit INTEGER NOT NULL DEFAULT 1
);
"""

CREATE_QUERY_CACHE_TABLE = """
CREATE TABLE IF NOT EXISTS query_cache (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    result_limit INTEGER NOT NULL DEFAULT 5,
    hits_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
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
CREATE INDEX IF NOT EXISTS idx_rejected_at ON rejected_results(rejected_at DESC);
CREATE INDEX IF NOT EXISTS idx_rejected_reason ON rejected_results(reason);
CREATE INDEX IF NOT EXISTS idx_query_runs_profile ON query_runs(profile);
CREATE INDEX IF NOT EXISTS idx_query_runs_executed ON query_runs(executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_budget_executed ON search_budget_usage(executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_budget_provider ON search_budget_usage(provider);
CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at DESC);
"""


@dataclass
class SaveOpportunitiesResult:
    saved: int = 0
    merged: int = 0
    skipped_empty_url: int = 0
    urls_deduplicated: int = 0
    by_data_mode: dict[str, int] = field(default_factory=dict)


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(opportunities)")}
    new_cols = {
        "why_saved": "TEXT DEFAULT ''",
        "collection_detected": "TEXT DEFAULT ''",
        "rarity_detected": "TEXT DEFAULT ''",
        "condition_detected": "TEXT DEFAULT ''",
        "grading_detected": "TEXT DEFAULT ''",
        "language_detected": "TEXT DEFAULT ''",
        "market_jargon_detected": "TEXT DEFAULT ''",
        "negative_context_detected": "TEXT DEFAULT ''",
        "domain": "TEXT DEFAULT ''",
        "human_review": "TEXT DEFAULT ''",
        "human_review_notes": "TEXT DEFAULT ''",
        "reviewed_at": "TEXT",
        "profile": "TEXT DEFAULT ''",
        "freshness_status": "TEXT DEFAULT 'unknown'",
        "detected_date": "TEXT",
        "age_days": "INTEGER",
    }
    for col, typedef in new_cols.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col} {typedef}")

    if "profile" in {row[1] for row in conn.execute("PRAGMA table_info(opportunities)")}:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_opp_profile ON opportunities(profile)"
        )

    rej_cols = {row[1] for row in conn.execute("PRAGMA table_info(rejected_results)")}
    rej_new_cols = {
        "reason_category": "TEXT DEFAULT ''",
        "profile": "TEXT DEFAULT ''",
        "card": "TEXT DEFAULT ''",
        "human_review": "TEXT DEFAULT ''",
        "human_review_notes": "TEXT DEFAULT ''",
        "reviewed_at": "TEXT",
    }
    for col, typedef in rej_new_cols.items():
        if col not in rej_cols:
            conn.execute(f"ALTER TABLE rejected_results ADD COLUMN {col} {typedef}")


def _conn(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        CREATE_OPPORTUNITIES_TABLE
        + CREATE_WISHLIST_TABLE
        + CREATE_REJECTED_TABLE
        + CREATE_QUERY_RUNS_TABLE
        + CREATE_SEARCH_BUDGET_TABLE
        + CREATE_QUERY_CACHE_TABLE
        + CREATE_SCAN_RUNS_TABLE
        + CREATE_OPP_INDEXES
    )
    _migrate(conn)
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


def _ensure_domain(opp: Opportunity) -> Opportunity:
    if not opp.domain and opp.url:
        opp.domain = extract_domain(opp.url)
    return opp


def save_opportunity(
    opp: Opportunity,
    db_path: Path | str = DEFAULT_DB,
    *,
    deduplicate_urls: bool = True,
) -> str:
    """Salva oportunidade. Retorna 'saved', 'merged' ou 'skipped'."""
    opp = _ensure_domain(opp)
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
    *,
    card: str | None = None,
    profile: str | None = None,
) -> list[Opportunity]:
    conn = _conn(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if card:
        clauses.append("normalized_card_name = ?")
        params.append(card)
    if profile:
        clauses.append("profile = ?")
        params.append(profile)
    sql = "SELECT * FROM opportunities"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY opportunity_score DESC, collected_at DESC"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [Opportunity.from_db_row(dict(r)) for r in rows]


def fetch_opportunities_by_card(
    card: str,
    db_path: Path | str = DEFAULT_DB,
) -> list[Opportunity]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT * FROM opportunities
        WHERE normalized_card_name = ? OR card_name_detected = ?
        ORDER BY opportunity_score DESC, collected_at DESC
        """,
        (card, card),
    ).fetchall()
    conn.close()
    return [Opportunity.from_db_row(dict(r)) for r in rows]


def fetch_distinct_opportunity_cards(db_path: Path | str = DEFAULT_DB) -> list[str]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT DISTINCT normalized_card_name
        FROM opportunities
        ORDER BY normalized_card_name
        """
    ).fetchall()
    conn.close()
    return [r["normalized_card_name"] for r in rows if r["normalized_card_name"]]


def count_rejected_by_profile(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT profile, COUNT(*) as cnt
        FROM rejected_results
        WHERE profile IS NOT NULL AND profile != ''
        GROUP BY profile
        ORDER BY cnt DESC
        """
    ).fetchall()
    conn.close()
    return {r["profile"]: r["cnt"] for r in rows}


def fetch_rejected_by_profile(
    profile: str,
    db_path: Path | str = DEFAULT_DB,
    limit: int | None = None,
) -> list[RejectedResult]:
    conn = _conn(db_path)
    sql = (
        "SELECT * FROM rejected_results WHERE profile = ? "
        "ORDER BY rejected_at DESC"
    )
    params: list[Any] = [profile]
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_rejected_from_row(r) for r in rows]


def fetch_opportunity_by_id(
    opp_id: str,
    db_path: Path | str = DEFAULT_DB,
) -> Opportunity | None:
    conn = _conn(db_path)
    row = conn.execute(
        "SELECT * FROM opportunities WHERE id = ?",
        (opp_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return Opportunity.from_db_row(dict(row))


def resolve_opportunity_index(
    index: int,
    db_path: Path | str = DEFAULT_DB,
) -> Opportunity | None:
    """Resolve índice 1-based na lista ordenada por score (como opportunity-inbox)."""
    if index < 1:
        return None
    opps = fetch_opportunities(db_path)
    if index > len(opps):
        return None
    return opps[index - 1]


def mark_opportunity_review(
    opp_id: str,
    review: str,
    notes: str = "",
    db_path: Path | str = DEFAULT_DB,
) -> bool:
    conn = _conn(db_path)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        UPDATE opportunities
        SET human_review = ?, human_review_notes = ?, reviewed_at = ?, status = 'reviewed'
        WHERE id = ?
        """,
        (review, notes, now, opp_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def count_human_reviews(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT human_review, COUNT(*) as cnt
        FROM opportunities
        WHERE human_review IS NOT NULL AND human_review != ''
        GROUP BY human_review
        """
    ).fetchall()
    conn.close()
    return {r["human_review"]: r["cnt"] for r in rows}


def count_unreviewed_opportunities(db_path: Path | str = DEFAULT_DB) -> int:
    conn = _conn(db_path)
    row = conn.execute(
        """
        SELECT COUNT(*) as cnt FROM opportunities
        WHERE human_review IS NULL OR human_review = ''
        """
    ).fetchone()
    conn.close()
    return int(row["cnt"]) if row else 0


def fetch_reviewed_opportunities(
    db_path: Path | str = DEFAULT_DB,
) -> list[Opportunity]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT * FROM opportunities
        WHERE human_review IS NOT NULL AND human_review != ''
        ORDER BY reviewed_at DESC
        """
    ).fetchall()
    conn.close()
    return [Opportunity.from_db_row(dict(r)) for r in rows]


def count_domains_by_review(
    review: str,
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT domain, url FROM opportunities
        WHERE human_review = ?
        """,
        (review,),
    ).fetchall()
    conn.close()
    counts: dict[str, int] = {}
    for row in rows:
        domain = row["domain"] or extract_domain(row["url"] or "")
        if domain:
            counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def count_types_by_review(
    review: str,
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT opportunity_type, COUNT(*) as cnt
        FROM opportunities
        WHERE human_review = ?
        GROUP BY opportunity_type
        ORDER BY cnt DESC
        """,
        (review,),
    ).fetchall()
    conn.close()
    return {r["opportunity_type"]: r["cnt"] for r in rows}


def fetch_false_positives(
    limit: int = 5,
    db_path: Path | str = DEFAULT_DB,
) -> list[Opportunity]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT * FROM opportunities
        WHERE human_review = 'irrelevant'
        ORDER BY opportunity_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [Opportunity.from_db_row(dict(r)) for r in rows]


def export_review_csv(
    output_path: Path | str,
    db_path: Path | str = DEFAULT_DB,
) -> int:
    import csv

    opps = fetch_opportunities(db_path)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "id",
        "card",
        "opportunity_type",
        "score",
        "confidence",
        "source",
        "domain",
        "evidence_text",
        "url",
        "why_saved",
        "human_review",
        "human_review_notes",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, opp in enumerate(opps, 1):
            writer.writerow({
                "id": i,
                "card": opp.normalized_card_name,
                "opportunity_type": opp.opportunity_type.value,
                "score": opp.opportunity_score,
                "confidence": opp.confidence_score,
                "source": opp.source,
                "domain": opp.domain or extract_domain(opp.url),
                "evidence_text": opp.evidence_text,
                "url": opp.url,
                "why_saved": opp.why_saved,
                "human_review": opp.human_review,
                "human_review_notes": opp.human_review_notes,
            })
    return len(opps)


def count_saved_domains(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT domain, url FROM opportunities WHERE url IS NOT NULL AND url != ''"
    ).fetchall()
    conn.close()
    counts: dict[str, int] = {}
    for row in rows:
        domain = row["domain"] or extract_domain(row["url"])
        if domain:
            counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


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
    conn.execute("DELETE FROM rejected_results")
    conn.execute("DELETE FROM query_runs")
    conn.commit()
    conn.close()


@dataclass
class QueryRun:
    id: str
    profile: str
    card: str
    query: str
    total_results: int
    saved_count: int
    rejected_count: int
    timeout_count: int
    duration_seconds: float
    executed_at: datetime
    domains_found: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> QueryRun:
        data = dict(row)
        return cls(
            id=data["id"],
            profile=data.get("profile") or "",
            card=data["card"],
            query=data["query"],
            total_results=int(data.get("total_results") or 0),
            saved_count=int(data.get("saved_count") or 0),
            rejected_count=int(data.get("rejected_count") or 0),
            timeout_count=int(data.get("timeout_count") or 0),
            duration_seconds=float(data.get("duration_seconds") or 0),
            executed_at=datetime.fromisoformat(data["executed_at"]),
            domains_found=data.get("domains_found") or "",
        )


def save_query_run(
    profile: str,
    card: str,
    query: str,
    *,
    total_results: int = 0,
    saved_count: int = 0,
    rejected_count: int = 0,
    timeout_count: int = 0,
    duration_seconds: float = 0.0,
    domains_found: list[str] | None = None,
    db_path: Path | str = DEFAULT_DB,
) -> str:
    run_id = str(uuid.uuid4())
    domains_str = ",".join(domains_found or [])
    conn = _conn(db_path)
    conn.execute(
        """
        INSERT INTO query_runs (
            id, profile, card, query, total_results, saved_count,
            rejected_count, timeout_count, duration_seconds, executed_at, domains_found
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            profile,
            card,
            query,
            total_results,
            saved_count,
            rejected_count,
            timeout_count,
            duration_seconds,
            datetime.now(timezone.utc).isoformat(),
            domains_str,
        ),
    )
    conn.commit()
    conn.close()
    return run_id


def fetch_query_runs(
    db_path: Path | str = DEFAULT_DB,
    profile: str | None = None,
    limit: int | None = None,
) -> list[QueryRun]:
    conn = _conn(db_path)
    sql = "SELECT * FROM query_runs"
    params: list[Any] = []
    if profile:
        sql += " WHERE profile = ?"
        params.append(profile)
    sql += " ORDER BY executed_at DESC"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [QueryRun.from_row(r) for r in rows]


def count_rejected_human_reviews(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT human_review, COUNT(*) as cnt
        FROM rejected_results
        WHERE human_review IS NOT NULL AND human_review != ''
        GROUP BY human_review
        """
    ).fetchall()
    conn.close()
    return {r["human_review"]: r["cnt"] for r in rows}


def fetch_false_negative_rejections(
    limit: int = 5,
    db_path: Path | str = DEFAULT_DB,
) -> list["RejectedResult"]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT * FROM rejected_results
        WHERE human_review = 'false_negative'
        ORDER BY rejected_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [_rejected_from_row(r) for r in rows]


def count_rejected_domains_by_review(
    review: str,
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT url FROM rejected_results WHERE human_review = ?",
        (review,),
    ).fetchall()
    conn.close()
    counts: dict[str, int] = {}
    for row in rows:
        domain = extract_domain(row["url"] or "")
        if domain:
            counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def count_rejected_by_reason_category(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT reason_category, COUNT(*) as cnt
        FROM rejected_results
        WHERE reason_category IS NOT NULL AND reason_category != ''
        GROUP BY reason_category
        ORDER BY cnt DESC
        """
    ).fetchall()
    conn.close()
    return {r["reason_category"]: r["cnt"] for r in rows}


def fetch_queries_with_false_negatives(
    limit: int = 5,
    db_path: Path | str = DEFAULT_DB,
) -> list[str]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT query, COUNT(*) as cnt
        FROM rejected_results
        WHERE human_review = 'false_negative'
        GROUP BY query
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [r["query"] for r in rows]


@dataclass
class RejectedResult:
    id: str
    query: str
    title: str
    snippet: str
    url: str
    reason: str
    rejected_at: datetime
    reason_category: str = ""
    profile: str = ""
    card: str = ""
    human_review: str = ""
    human_review_notes: str = ""
    reviewed_at: datetime | None = None

    @classmethod
    def create(
        cls,
        query: str,
        title: str,
        snippet: str,
        url: str,
        reason: str,
        *,
        reason_category: str = "",
        profile: str = "",
        card: str = "",
    ) -> RejectedResult:
        return cls(
            id=str(uuid.uuid4()),
            query=query,
            title=title,
            snippet=snippet,
            url=url,
            reason=reason,
            rejected_at=datetime.now(timezone.utc),
            reason_category=reason_category,
            profile=profile,
            card=card,
        )


def _rejected_from_row(r: sqlite3.Row) -> RejectedResult:
    reviewed = r["reviewed_at"] if "reviewed_at" in r.keys() else None
    return RejectedResult(
        id=r["id"],
        query=r["query"],
        title=r["title"] or "",
        snippet=r["snippet"] or "",
        url=r["url"] or "",
        reason=r["reason"],
        rejected_at=datetime.fromisoformat(r["rejected_at"]),
        reason_category=(r["reason_category"] if "reason_category" in r.keys() else "") or "",
        profile=(r["profile"] if "profile" in r.keys() else "") or "",
        card=(r["card"] if "card" in r.keys() else "") or "",
        human_review=(r["human_review"] if "human_review" in r.keys() else "") or "",
        human_review_notes=(r["human_review_notes"] if "human_review_notes" in r.keys() else "") or "",
        reviewed_at=datetime.fromisoformat(reviewed) if reviewed else None,
    )


def save_rejected_result(
    query: str,
    title: str,
    snippet: str,
    url: str,
    reason: str,
    db_path: Path | str = DEFAULT_DB,
    *,
    reason_category: str = "",
    profile: str = "",
    card: str = "",
) -> None:
    row = RejectedResult.create(
        query, title, snippet, url, reason,
        reason_category=reason_category,
        profile=profile,
        card=card,
    )
    conn = _conn(db_path)
    conn.execute(
        """
        INSERT INTO rejected_results (
            id, query, title, snippet, url, reason, rejected_at,
            reason_category, profile, card
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.query,
            row.title,
            row.snippet,
            row.url,
            row.reason,
            row.rejected_at.isoformat(),
            row.reason_category,
            row.profile,
            row.card,
        ),
    )
    conn.commit()
    conn.close()


def fetch_rejected_results(
    db_path: Path | str = DEFAULT_DB,
    limit: int | None = None,
) -> list[RejectedResult]:
    conn = _conn(db_path)
    sql = "SELECT * FROM rejected_results ORDER BY rejected_at DESC"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [_rejected_from_row(r) for r in rows]


def resolve_rejected_index(
    index: int,
    db_path: Path | str = DEFAULT_DB,
) -> RejectedResult | None:
    if index < 1:
        return None
    rows = fetch_rejected_results(db_path)
    if index > len(rows):
        return None
    return rows[index - 1]


def mark_rejected_review(
    rejected_id: str,
    review: str,
    notes: str = "",
    db_path: Path | str = DEFAULT_DB,
) -> bool:
    conn = _conn(db_path)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        UPDATE rejected_results
        SET human_review = ?, human_review_notes = ?, reviewed_at = ?
        WHERE id = ?
        """,
        (review, notes, now, rejected_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def count_rejected_results(db_path: Path | str = DEFAULT_DB) -> int:
    conn = _conn(db_path)
    row = conn.execute("SELECT COUNT(*) as cnt FROM rejected_results").fetchone()
    conn.close()
    return int(row["cnt"]) if row else 0


def count_rejected_by_reason(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        "SELECT reason, COUNT(*) as cnt FROM rejected_results GROUP BY reason ORDER BY cnt DESC"
    ).fetchall()
    conn.close()
    return {r["reason"]: r["cnt"] for r in rows}


def count_rejected_domains(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute("SELECT url FROM rejected_results WHERE url IS NOT NULL AND url != ''").fetchall()
    conn.close()
    counts: dict[str, int] = {}
    for row in rows:
        domain = extract_domain(row["url"])
        if domain:
            counts[domain] = counts.get(domain, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def _budget_since(days: int) -> str:
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return since.isoformat()


def _resolve_db(db_path: Path | str | None) -> Path | str:
    return db_path if db_path is not None else DEFAULT_DB


def record_budget_usage(
    provider: str,
    query: str,
    *,
    profile: str = "",
    card: str = "",
    success: bool = False,
    results_count: int = 0,
    cached: bool = False,
    cost_unit: int = 1,
    db_path: Path | str | None = None,
) -> str:
    db_path = _resolve_db(db_path)
    row_id = str(uuid.uuid4())
    conn = _conn(db_path)
    conn.execute(
        """
        INSERT INTO search_budget_usage (
            id, provider, profile, card, query, executed_at,
            success, results_count, cached, cost_unit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row_id,
            provider,
            profile,
            card,
            query,
            datetime.now(timezone.utc).isoformat(),
            1 if success else 0,
            results_count,
            1 if cached else 0,
            cost_unit,
        ),
    )
    conn.commit()
    conn.close()
    return row_id


def count_budget_usage(
    days: int = 1,
    *,
    api_only: bool = False,
    cached_only: bool = False,
    db_path: Path | str | None = None,
) -> int:
    db_path = _resolve_db(db_path)
    conn = _conn(db_path)
    if cached_only:
        sql = "SELECT COUNT(*) as cnt FROM search_budget_usage WHERE executed_at >= ? AND cached = 1"
    else:
        sql = "SELECT COALESCE(SUM(cost_unit), 0) as cnt FROM search_budget_usage WHERE executed_at >= ?"
        if api_only:
            sql += " AND cached = 0 AND cost_unit > 0"
    params: list[Any] = [_budget_since(days)]
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return int(row["cnt"]) if row else 0


def _budget_group_count(
    column: str,
    days: int = 30,
    *,
    api_only: bool = True,
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, int]:
    conn = _conn(db_path)
    sql = f"""
        SELECT {column}, SUM(cost_unit) as cnt
        FROM search_budget_usage
        WHERE executed_at >= ?
    """
    params: list[Any] = [_budget_since(days)]
    if api_only:
        sql += " AND cached = 0 AND cost_unit > 0"
    sql += f" GROUP BY {column} ORDER BY cnt DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return {r[column] or "": int(r["cnt"]) for r in rows}


def count_budget_usage_by_profile(
    days: int = 30,
    *,
    api_only: bool = True,
    db_path: Path | str | None = None,
) -> dict[str, int]:
    db_path = _resolve_db(db_path)
    return _budget_group_count("profile", days, api_only=api_only, db_path=db_path)


def count_budget_usage_by_card(
    days: int = 30,
    *,
    api_only: bool = True,
    db_path: Path | str | None = None,
) -> dict[str, int]:
    db_path = _resolve_db(db_path)
    return _budget_group_count("card", days, api_only=api_only, db_path=db_path)


def count_budget_usage_by_query(
    days: int = 30,
    *,
    api_only: bool = True,
    db_path: Path | str | None = None,
) -> dict[str, int]:
    db_path = _resolve_db(db_path)
    return _budget_group_count("query", days, api_only=api_only, db_path=db_path)


def top_consuming_profiles(
    days: int = 30,
    db_path: Path | str | None = None,
) -> list[tuple[str, int]]:
    db_path = _resolve_db(db_path)
    return list(count_budget_usage_by_profile(days, db_path=db_path).items())


def get_last_profile_usage_today(
    *,
    api_only: bool = True,
    db_path: Path | str | None = None,
) -> str | None:
    db_path = _resolve_db(db_path)
    conn = _conn(db_path)
    sql = """
        SELECT profile FROM search_budget_usage
        WHERE executed_at >= ? AND profile IS NOT NULL AND profile != ''
    """
    params: list[Any] = [_budget_since(1)]
    if api_only:
        sql += " AND cached = 0 AND cost_unit > 0"
    sql += " ORDER BY executed_at DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row["profile"] if row else None


def save_query_cache(
    provider: str,
    query: str,
    result_limit: int,
    hits: list[dict],
    db_path: Path | str | None = None,
) -> None:
    db_path = _resolve_db(db_path)
    conn = _conn(db_path)
    conn.execute(
        "DELETE FROM query_cache WHERE provider = ? AND query = ? AND result_limit = ?",
        (provider, query, result_limit),
    )
    conn.execute(
        """
        INSERT INTO query_cache (id, provider, query, result_limit, hits_json, cached_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            provider,
            query,
            result_limit,
            json.dumps(hits, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def fetch_cached_query(
    provider: str,
    query: str,
    result_limit: int,
    *,
    ttl_hours: float = 24.0,
    db_path: Path | str | None = None,
) -> list[dict] | None:
    db_path = _resolve_db(db_path)
    from datetime import timedelta
    conn = _conn(db_path)
    row = conn.execute(
        """
        SELECT hits_json, cached_at FROM query_cache
        WHERE provider = ? AND query = ? AND result_limit = ?
        ORDER BY cached_at DESC LIMIT 1
        """,
        (provider, query, result_limit),
    ).fetchone()
    conn.close()
    if not row:
        return None
    cached_at = datetime.fromisoformat(row["cached_at"])
    if datetime.now(timezone.utc) - cached_at > timedelta(hours=ttl_hours):
        return None
    try:
        return json.loads(row["hits_json"])
    except json.JSONDecodeError:
        return None


@dataclass
class ScanRun:
    id: str
    run_type: str
    profiles: str
    cards: str
    budget_mode: str
    query_budget: int
    queries_planned: int
    queries_executed: int
    opportunities_saved: int
    rejected_count: int
    timeout_count: int
    started_at: datetime
    finished_at: datetime | None
    status: str

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict[str, Any]) -> ScanRun:
        data = dict(row)
        finished = data.get("finished_at")
        return cls(
            id=data["id"],
            run_type=data.get("run_type") or "daily_radar",
            profiles=data.get("profiles") or "",
            cards=data.get("cards") or "",
            budget_mode=data.get("budget_mode") or "",
            query_budget=int(data.get("query_budget") or 0),
            queries_planned=int(data.get("queries_planned") or 0),
            queries_executed=int(data.get("queries_executed") or 0),
            opportunities_saved=int(data.get("opportunities_saved") or 0),
            rejected_count=int(data.get("rejected_count") or 0),
            timeout_count=int(data.get("timeout_count") or 0),
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(finished) if finished else None,
            status=data.get("status") or "running",
        )


def create_scan_run(
    *,
    run_type: str = "daily_radar",
    profiles: list[str],
    cards: list[str],
    budget_mode: str,
    query_budget: int,
    queries_planned: int = 0,
    db_path: Path | str | None = None,
) -> str:
    db_path = _resolve_db(db_path)
    run_id = str(uuid.uuid4())
    conn = _conn(db_path)
    conn.execute(
        """
        INSERT INTO scan_runs (
            id, run_type, profiles, cards, budget_mode, query_budget,
            queries_planned, queries_executed, opportunities_saved,
            rejected_count, timeout_count, started_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 'running')
        """,
        (
            run_id,
            run_type,
            ",".join(profiles),
            ",".join(cards),
            budget_mode,
            query_budget,
            queries_planned,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    return run_id


def finish_scan_run(
    run_id: str,
    *,
    queries_executed: int,
    opportunities_saved: int,
    rejected_count: int,
    timeout_count: int = 0,
    status: str = "completed",
    db_path: Path | str | None = None,
) -> None:
    db_path = _resolve_db(db_path)
    conn = _conn(db_path)
    conn.execute(
        """
        UPDATE scan_runs
        SET queries_executed = ?, opportunities_saved = ?, rejected_count = ?,
            timeout_count = ?, finished_at = ?, status = ?
        WHERE id = ?
        """,
        (
            queries_executed,
            opportunities_saved,
            rejected_count,
            timeout_count,
            datetime.now(timezone.utc).isoformat(),
            status,
            run_id,
        ),
    )
    conn.commit()
    conn.close()


def fetch_scan_runs(
    limit: int | None = 10,
    db_path: Path | str | None = None,
) -> list[ScanRun]:
    db_path = _resolve_db(db_path)
    conn = _conn(db_path)
    sql = "SELECT * FROM scan_runs ORDER BY started_at DESC"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [ScanRun.from_row(r) for r in rows]


def fetch_opportunities_since(
    days: float,
    db_path: Path | str = DEFAULT_DB,
) -> list[Opportunity]:
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT * FROM opportunities
        WHERE collected_at >= ?
        ORDER BY collected_at DESC
        """,
        (since.isoformat(),),
    ).fetchall()
    conn.close()
    return [Opportunity.from_db_row(dict(r)) for r in rows]


def count_opportunities_by_profile(
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, int]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT profile, COUNT(*) as cnt
        FROM opportunities
        WHERE profile IS NOT NULL AND profile != ''
        GROUP BY profile
        ORDER BY cnt DESC
        """
    ).fetchall()
    conn.close()
    return {r["profile"]: r["cnt"] for r in rows}


def fetch_stale_opportunities(
    *,
    min_age_days: int = 30,
    db_path: Path | str = DEFAULT_DB,
) -> list[Opportunity]:
    conn = _conn(db_path)
    rows = conn.execute(
        """
        SELECT * FROM opportunities
        WHERE freshness_status IN ('old', 'unknown')
           OR (age_days IS NOT NULL AND age_days >= ?)
        ORDER BY collected_at ASC
        """,
        (min_age_days,),
    ).fetchall()
    conn.close()
    return [Opportunity.from_db_row(dict(r)) for r in rows]

