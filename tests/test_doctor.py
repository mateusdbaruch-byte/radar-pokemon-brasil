"""Testes do comando doctor (checks locais mockados)."""

from pathlib import Path
from unittest.mock import patch

from src.connector_health import ConnectorDataMode, HealthStatus
from src.doctor import (
    _check_config_file,
    _check_csv_write,
    _check_env,
    _check_sqlite,
    run_doctor_checks,
)


class TestDoctorLocalChecks:
    def test_sqlite_ok(self, tmp_path: Path):
        with patch("src.doctor.DEFAULT_DB", tmp_path / "radar.db"):
            result = _check_sqlite()
        assert result.status == HealthStatus.OK
        assert result.data_mode == ConnectorDataMode.LIVE

    def test_csv_write_ok(self, tmp_path: Path):
        with patch("src.doctor.DEFAULT_CSV", tmp_path / "out.csv"):
            result = _check_csv_write()
        assert result.status == HealthStatus.OK

    def test_env_missing(self, tmp_path: Path):
        with patch("src.doctor.PROJECT_ROOT", tmp_path):
            result = _check_env()
        assert result.status == HealthStatus.WARNING
        assert ".env não encontrado" in result.message

    def test_config_file_missing(self, tmp_path: Path):
        result = _check_config_file(tmp_path / "missing.yml", "config/missing.yml")
        assert result.status == HealthStatus.ERROR

    @patch("src.doctor._check_mercado_livre")
    @patch("src.doctor._check_reddit")
    def test_run_doctor_checks_count(self, mock_reddit, mock_ml):
        from src.connector_health import HealthCheckResult

        ok = HealthCheckResult(
            source="x",
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=200,
            message="ok",
            next_action="ok",
        )
        mock_ml.return_value = ok
        mock_reddit.return_value = ok

        results = run_doctor_checks()
        assert len(results) == 8
