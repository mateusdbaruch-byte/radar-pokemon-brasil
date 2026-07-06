"""Testes dos adaptadores de saúde ML/Reddit."""

from src.connector_health import ConnectorDataMode, HealthStatus
from src.connectors.mercado_livre import MLDiagnosticResult
from src.connectors.reddit import RedditDiagnosticResult
from src.health_adapters import mercado_livre_to_health, reddit_to_health


def _ml_diag(**kwargs) -> MLDiagnosticResult:
    defaults = dict(
        url="https://api.test",
        status_code=200,
        response_preview="{}",
        is_valid_json=True,
        json_top_level_keys=["results"],
        results_count=3,
        error_message=None,
        suggestions=[],
        is_forbidden=False,
    )
    defaults.update(kwargs)
    return MLDiagnosticResult(**defaults)


def _reddit_diag(**kwargs) -> RedditDiagnosticResult:
    defaults = dict(
        method="GET",
        url="https://reddit.test",
        user_agent="test",
        status_code=200,
        response_preview="{}",
        is_valid_json=True,
        posts_count=2,
        needs_oauth=False,
        oauth_message="",
        auth_mode="public",
        auth_status="live",
        error_message=None,
        suggestions=[],
    )
    defaults.update(kwargs)
    return RedditDiagnosticResult(**defaults)


class TestHealthAdapters:
    def test_ml_forbidden(self):
        health = mercado_livre_to_health(_ml_diag(status_code=403, is_forbidden=True))
        assert health.status == HealthStatus.BLOCKED
        assert health.data_mode == ConnectorDataMode.UNAVAILABLE

    def test_ml_ok(self):
        health = mercado_livre_to_health(_ml_diag())
        assert health.status == HealthStatus.OK
        assert health.data_mode == ConnectorDataMode.LIVE

    def test_reddit_oauth_ok(self):
        health = reddit_to_health(_reddit_diag(auth_mode="oauth"))
        assert "oauth" in health.message

    def test_reddit_forbidden_pending(self):
        health = reddit_to_health(
            _reddit_diag(status_code=403, is_valid_json=False, auth_status="pending_approval")
        )
        assert health.status == HealthStatus.PENDING_APPROVAL
        assert health.http_status == 403
