"""Testes de data_mode e reset do banco."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.database import (
    count_by_data_mode,
    fetch_all,
    get_connection,
    reset_all_data,
    save_results,
)
from src.models import DataMode, RadarResult, tag_results


def _make_result(mode: DataMode = DataMode.LIVE) -> RadarResult:
    return RadarResult(
        source="reddit",
        platform="reddit",
        card_name_detected="Pikachu",
        normalized_card_name="Pikachu",
        url="https://example.com/pikachu",
        data_mode=mode,
        collected_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def temp_db(tmp_path):
  db = tmp_path / "test.db"
  csv = tmp_path / "test.csv"
  return db, csv


class TestDataModePersistence:
    def test_save_and_load_data_mode(self, temp_db):
        db, _ = temp_db
        results = [
            _make_result(DataMode.LIVE),
            tag_results([_make_result()], DataMode.MOCK)[0],
        ]
        save_results(results, db)
        loaded = fetch_all(db)
        modes = {r.data_mode for r in loaded}
        assert DataMode.LIVE in modes
        assert DataMode.MOCK in modes

    def test_count_by_data_mode(self, temp_db):
        db, _ = temp_db
        save_results(
            [
                _make_result(DataMode.LIVE),
                _make_result(DataMode.MOCK),
                _make_result(DataMode.MANUAL_IMPORT),
            ],
            db,
        )
        counts = count_by_data_mode(db_path=db)
        assert counts["live"] == 1
        assert counts["mock"] == 1
        assert counts["manual_import"] == 1

    def test_migration_adds_data_mode_column(self, temp_db):
        db, _ = temp_db
        conn = get_connection(db)
        conn.execute(
            """
            INSERT INTO radar_results (
                id, source, platform, card_name_detected, normalized_card_name,
                url, collected_at, intent_type, intent_score, data_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1", "reddit", "reddit", "Mew", "Mew",
                "https://example.com", datetime.now(timezone.utc).isoformat(),
                "DISCUSSION", 30, "live",
            ),
        )
        conn.commit()
        conn.close()
        row = fetch_all(db)[0]
        assert row.data_mode == DataMode.LIVE


class TestResetDatabase:
    def test_reset_clears_db_and_csv(self, temp_db):
        db, csv = temp_db
        save_results([_make_result()], db)
        reset_all_data(db, csv)
        assert len(fetch_all(db)) == 0
        assert csv.exists()
        content = csv.read_text(encoding="utf-8-sig")
        assert "data_mode" in content
        assert "Pikachu" not in content
