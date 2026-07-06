"""Testes da persistência de saúde dos conectores."""

from pathlib import Path

from src.connector_health import (
    ConnectorDataMode,
    HealthCheckResult,
    HealthStatus,
    fetch_latest_by_source,
    save_health_check,
    save_search_run_log,
    fetch_latest_search_log,
)


def _make_result(source: str, message: str) -> HealthCheckResult:
    return HealthCheckResult(
        source=source,
        status=HealthStatus.OK,
        data_mode=ConnectorDataMode.LIVE,
        http_status=200,
        message=message,
        next_action="ok",
        raw_response_snippet='{"ok": true}',
    )


class TestConnectorHealth:
    def test_save_and_fetch_latest(self, tmp_path: Path):
        db = tmp_path / "test.db"
        save_health_check(_make_result("reddit", "primeiro"), db)
        save_health_check(_make_result("reddit", "segundo"), db)
        save_health_check(_make_result("mercado_livre", "ml ok"), db)

        rows = fetch_latest_by_source(db)
        by_source = {r["source"]: r for r in rows}

        assert len(by_source) == 2
        assert by_source["reddit"]["message"] == "segundo"
        assert by_source["mercado_livre"]["http_status"] == 200

    def test_search_run_log(self, tmp_path: Path):
        db = tmp_path / "test.db"
        save_search_run_log("live-only", 10, 0, 0, 2, db)
        log = fetch_latest_search_log(db)

        assert log is not None
        assert log["search_mode"] == "live-only"
        assert log["live_count"] == 10
        assert log["source_errors"] == 2
