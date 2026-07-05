"""Persistência SQLite para resultados do radar."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.models import RadarResult
from src.paths import DEFAULT_DB, ensure_data_dir

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS radar_results (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    platform TEXT NOT NULL,
    card_name_detected TEXT NOT NULL,
    normalized_card_name TEXT NOT NULL,
    title TEXT,
    text_snippet TEXT,
    url TEXT NOT NULL,
    author_or_seller TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL,
    intent_type TEXT NOT NULL,
    intent_score INTEGER NOT NULL,
    price REAL,
    currency TEXT DEFAULT 'BRL',
    location TEXT,
    raw_data_json TEXT
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_intent_score ON radar_results(intent_score DESC);
CREATE INDEX IF NOT EXISTS idx_card_name ON radar_results(normalized_card_name);
CREATE INDEX IF NOT EXISTS idx_collected_at ON radar_results(collected_at DESC);
"""


def get_connection(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """Abre conexão SQLite, criando diretório e tabela se necessário."""
    path = Path(db_path)
    ensure_data_dir()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(CREATE_TABLE_SQL + CREATE_INDEX_SQL)
    conn.commit()
    return conn


def save_result(result: RadarResult, db_path: Path | str = DEFAULT_DB) -> None:
    """Insere ou atualiza um resultado no banco."""
    conn = get_connection(db_path)
    row = result.to_db_row()
    columns = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    sql = f"""
        INSERT OR REPLACE INTO radar_results ({columns})
        VALUES ({placeholders})
    """
    conn.execute(sql, list(row.values()))
    conn.commit()
    conn.close()


def save_results(
    results: list[RadarResult],
    db_path: Path | str = DEFAULT_DB,
) -> int:
    """Salva múltiplos resultados. Retorna quantidade salva."""
    conn = get_connection(db_path)
    count = 0
    for result in results:
        row = result.to_db_row()
        columns = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        sql = f"""
            INSERT OR REPLACE INTO radar_results ({columns})
            VALUES ({placeholders})
        """
        conn.execute(sql, list(row.values()))
        count += 1
    conn.commit()
    conn.close()
    return count


def fetch_all(
    db_path: Path | str = DEFAULT_DB,
    order_by_score: bool = True,
    limit: int | None = None,
) -> list[RadarResult]:
    """Busca todos os resultados do banco."""
    conn = get_connection(db_path)
    order = "intent_score DESC, collected_at DESC" if order_by_score else "collected_at DESC"
    sql = f"SELECT * FROM radar_results ORDER BY {order}"
    if limit:
        sql += f" LIMIT {limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [RadarResult.from_db_row(dict(row)) for row in rows]


def fetch_by_intent(
    intent_type: str,
    db_path: Path | str = DEFAULT_DB,
    limit: int = 50,
) -> list[RadarResult]:
    """Filtra resultados por tipo de intenção."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """
        SELECT * FROM radar_results
        WHERE intent_type = ?
        ORDER BY intent_score DESC
        LIMIT ?
        """,
        (intent_type, limit),
    ).fetchall()
    conn.close()
    return [RadarResult.from_db_row(dict(row)) for row in rows]


def count_results(db_path: Path | str = DEFAULT_DB) -> dict[str, Any]:
    """Retorna estatísticas resumidas do banco."""
    conn = get_connection(db_path)
    total = conn.execute("SELECT COUNT(*) FROM radar_results").fetchone()[0]
    by_intent = conn.execute(
        """
        SELECT intent_type, COUNT(*) as cnt
        FROM radar_results
        GROUP BY intent_type
        """
    ).fetchall()
    by_source = conn.execute(
        """
        SELECT source, COUNT(*) as cnt
        FROM radar_results
        GROUP BY source
        """
    ).fetchall()
    avg_score = conn.execute(
        "SELECT AVG(intent_score) FROM radar_results"
    ).fetchone()[0]
    conn.close()
    return {
        "total": total,
        "by_intent": {row["intent_type"]: row["cnt"] for row in by_intent},
        "by_source": {row["source"]: row["cnt"] for row in by_source},
        "avg_score": round(avg_score or 0, 1),
    }


def clear_results(db_path: Path | str = DEFAULT_DB) -> None:
    """Remove todos os resultados (útil para testes)."""
    conn = get_connection(db_path)
    conn.execute("DELETE FROM radar_results")
    conn.commit()
    conn.close()
