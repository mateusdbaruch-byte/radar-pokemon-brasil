"""Conversão de diagnósticos em registros de saúde."""

from __future__ import annotations

from src.connector_health import ConnectorDataMode, HealthCheckResult, HealthStatus
from src.connectors.mercado_livre import MLDiagnosticResult
from src.connectors.reddit import RedditDiagnosticResult
from src.reddit_auth import RedditAuthStatus, auth_status_to_connector_mode


def mercado_livre_to_health(diag: MLDiagnosticResult) -> HealthCheckResult:
    """Converte diagnóstico ML em HealthCheckResult."""
    snippet = (diag.response_preview or "")[:500]
    if diag.status_code == 200 and diag.is_valid_json and diag.results_count is not None:
        if diag.results_count > 0:
            return HealthCheckResult(
                source="mercado_livre",
                status=HealthStatus.OK,
                data_mode=ConnectorDataMode.LIVE,
                http_status=diag.status_code,
                message=f"{diag.results_count} anúncio(s) na resposta",
                next_action="search --live-only",
                raw_response_snippet=snippet,
            )
        return HealthCheckResult(
            source="mercado_livre",
            status=HealthStatus.WARNING,
            data_mode=ConnectorDataMode.LIVE,
            http_status=diag.status_code,
            message="API OK, sem anúncios na query",
            next_action="Ajuste a query de busca",
            raw_response_snippet=snippet,
        )
    if diag.status_code == 403 or getattr(diag, "is_forbidden", False):
        return HealthCheckResult(
            source="mercado_livre",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=diag.status_code or 403,
            message="Forbidden — não é dado real",
            next_action="Rede residencial ou credenciais oficiais ML",
            raw_response_snippet=snippet,
        )
    return HealthCheckResult(
        source="mercado_livre",
        status=HealthStatus.ERROR,
        data_mode=ConnectorDataMode.UNAVAILABLE,
        http_status=diag.status_code,
        message=diag.error_message or "Falha na API",
        next_action=diag.suggestions[0] if diag.suggestions else "Rode doctor",
        raw_response_snippet=snippet,
    )


def reddit_to_health(diag: RedditDiagnosticResult) -> HealthCheckResult:
    """Converte diagnóstico Reddit em HealthCheckResult."""
    snippet = (diag.response_preview or "")[:500]
    mode_label = getattr(diag, "auth_mode", "public")
    auth_status = getattr(diag, "auth_status", None)

    if auth_status == RedditAuthStatus.MISSING_CREDENTIALS.value:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.MISSING_CREDENTIALS,
            http_status=diag.status_code,
            message="Credenciais OAuth/User-Agent ausentes",
            next_action="Rode setup-env e edite .env",
            raw_response_snippet=snippet,
        )

    if auth_status == RedditAuthStatus.AUTH_FAILED.value:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.AUTH_FAILED,
            http_status=diag.status_code,
            message=f"OAuth falhou ({mode_label})",
            next_action="Verifique CLIENT_ID/SECRET no Reddit Developer Portal",
            raw_response_snippet=snippet,
        )

    if diag.status_code == 200 and diag.is_valid_json:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=diag.status_code,
            message=f"OK via {mode_label} — {diag.posts_count or 0} post(s)",
            next_action="search-reddit ou search --live-only",
            raw_response_snippet=snippet,
        )

    if diag.status_code == 403 or auth_status == RedditAuthStatus.BLOCKED.value:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.BLOCKED,
            http_status=403,
            message=f"Bloqueado ({mode_label})",
            next_action="OAuth + rede residencial",
            raw_response_snippet=snippet,
        )

    connector_mode = ConnectorDataMode.UNAVAILABLE
    if auth_status:
        try:
            connector_mode = ConnectorDataMode(auth_status_to_connector_mode(
                RedditAuthStatus(auth_status)
            ))
        except ValueError:
            pass

    return HealthCheckResult(
        source="reddit",
        status=HealthStatus.ERROR,
        data_mode=connector_mode,
        http_status=diag.status_code,
        message=diag.error_message or f"Falha ({mode_label})",
        next_action=diag.suggestions[0] if diag.suggestions else "Rode test-reddit-auth",
        raw_response_snippet=snippet,
    )


def _is_forbidden_json(diag: MLDiagnosticResult) -> bool:
    return getattr(diag, "is_forbidden", False)
