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
    negative_context_detected TEXT DEFAULT ''
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
    }
    for col, typedef in new_cols.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col} {typedef}")


def _conn(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        CREATE_OPPORTUNITIES_TABLE
        + CREATE_WISHLIST_TABLE
        + CREATE_REJECTED_TABLE
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
    conn.commit()
    conn.close()


@dataclass
class RejectedResult:
    id: str
    query: str
    title: str
    snippet: str
    url: str
    reason: str
    rejected_at: datetime

    @classmethod
    def create(
        cls,
        query: str,
        title: str,
        snippet: str,
        url: str,
        reason: str,
    ) -> RejectedResult:
        return cls(
            id=str(uuid.uuid4()),
            query=query,
            title=title,
            snippet=snippet,
            url=url,
            reason=reason,
            rejected_at=datetime.now(timezone.utc),
        )


def save_rejected_result(
    query: str,
    title: str,
    snippet: str,
    url: str,
    reason: str,
    db_path: Path | str = DEFAULT_DB,
) -> None:
    row = RejectedResult.create(query, title, snippet, url, reason)
    conn = _conn(db_path)
    conn.execute(
        """
        INSERT INTO rejected_results (id, query, title, snippet, url, reason, rejected_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.id,
            row.query,
            row.title,
            row.snippet,
            row.url,
            row.reason,
            row.rejected_at.isoformat(),
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
    results: list[RejectedResult] = []
    for r in rows:
        results.append(RejectedResult(
            id=r["id"],
            query=r["query"],
            title=r["title"] or "",
            snippet=r["snippet"] or "",
            url=r["url"] or "",
            reason=r["reason"],
            rejected_at=datetime.fromisoformat(r["rejected_at"]),
        ))
    return results


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
