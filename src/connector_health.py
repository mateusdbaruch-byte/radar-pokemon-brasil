"""Saúde dos conectores — persistência e utilitários de diagnóstico."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.paths import DEFAULT_DB, ensure_data_dir

CREATE_HEALTH_TABLE = """
CREATE TABLE IF NOT EXISTS connector_health (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    data_mode TEXT NOT NULL,
    http_status INTEGER,
    message TEXT,
    tested_at TEXT NOT NULL,
    raw_response_snippet TEXT,
    next_action TEXT
);
"""

CREATE_SEARCH_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS search_run_log (
    id TEXT PRIMARY KEY,
    run_at TEXT NOT NULL,
    search_mode TEXT NOT NULL,
    live_count INTEGER NOT NULL DEFAULT 0,
    mock_count INTEGER NOT NULL DEFAULT 0,
    manual_count INTEGER NOT NULL DEFAULT 0,
    source_errors INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_HEALTH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_health_source_tested
ON connector_health(source, tested_at DESC);
"""


class HealthStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REQUIRES_AUTH = "REQUIRES_AUTH"
    PENDING_ACCESS = "PENDING_ACCESS"


class ConnectorDataMode(str, Enum):
    LIVE = "live"
    MOCK = "mock"
    UNAVAILABLE = "unavailable"
    AUTH_FAILED = "auth_failed"
    MISSING_CREDENTIALS = "missing_credentials"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"


@dataclass
class HealthCheckResult:
    """Resultado de um check de saúde (exibido no doctor e salvo no banco)."""

    source: str
    status: HealthStatus
    data_mode: ConnectorDataMode
    http_status: int | None
    message: str
    next_action: str
    raw_response_snippet: str = ""

    def to_db_row(self) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "source": self.source,
            "status": self.status.value,
            "data_mode": self.data_mode.value,
            "http_status": self.http_status,
            "message": self.message,
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "raw_response_snippet": (self.raw_response_snippet or "")[:500],
            "next_action": self.next_action,
        }


def _get_conn(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(CREATE_HEALTH_TABLE + CREATE_SEARCH_LOG_TABLE + CREATE_HEALTH_INDEX)
    conn.commit()
    return conn


def save_health_check(result: HealthCheckResult, db_path: Path | str = DEFAULT_DB) -> None:
    """Persiste um registro de saúde do conector."""
    conn = _get_conn(db_path)
    row = result.to_db_row()
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO connector_health ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )
    conn.commit()
    conn.close()


def save_health_checks(
    results: list[HealthCheckResult],
    db_path: Path | str = DEFAULT_DB,
) -> None:
    """Persiste múltiplos registros de saúde."""
    for result in results:
        save_health_check(result, db_path)


def fetch_latest_by_source(db_path: Path | str = DEFAULT_DB) -> list[dict[str, Any]]:
    """Último status conhecido de cada fonte."""
    conn = _get_conn(db_path)
    rows = conn.execute(
        """
        SELECT h.*
        FROM connector_health h
        INNER JOIN (
            SELECT source, MAX(tested_at) AS max_tested
            FROM connector_health
            GROUP BY source
        ) latest ON h.source = latest.source AND h.tested_at = latest.max_tested
        ORDER BY h.source
        """
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_search_run_log(
    search_mode: str,
    live_count: int,
    mock_count: int,
    manual_count: int,
    source_errors: int,
    db_path: Path | str = DEFAULT_DB,
) -> None:
    """Registra resumo da última execução de search."""
    conn = _get_conn(db_path)
    conn.execute(
        """
        INSERT INTO search_run_log (
            id, run_at, search_mode, live_count, mock_count, manual_count, source_errors
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            datetime.now(timezone.utc).isoformat(),
            search_mode,
            live_count,
            mock_count,
            manual_count,
            source_errors,
        ),
    )
    conn.commit()
    conn.close()


def fetch_latest_for_source(
    source: str,
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, Any] | None:
    """Último registro de saúde de uma fonte específica."""
    for row in fetch_latest_by_source(db_path):
        if row.get("source") == source:
            return row
    return None


def fetch_latest_search_log(db_path: Path | str = DEFAULT_DB) -> dict[str, Any] | None:
    """Retorna o registro mais recente de execução de search."""
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT * FROM search_run_log ORDER BY run_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None
