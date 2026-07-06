"""Conversão de diagnósticos em registros de saúde."""

from __future__ import annotations

from src.connector_health import ConnectorDataMode, HealthCheckResult, HealthStatus
from src.connectors.mercado_livre import MLDiagnosticResult
from src.connectors.reddit import RedditDiagnosticResult
from src.reddit_policy import map_reddit_diagnostic_to_health


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
            status=HealthStatus.BLOCKED,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=diag.status_code or 403,
            message="Forbidden — não é dado real (modo diagnóstico)",
            next_action="Use import-prices; teste ML em rede residencial",
            raw_response_snippet=snippet,
        )
    return HealthCheckResult(
        source="mercado_livre",
        status=HealthStatus.WARNING,
        data_mode=ConnectorDataMode.UNAVAILABLE,
        http_status=diag.status_code,
        message=diag.error_message or "Falha na API",
        next_action=diag.suggestions[0] if diag.suggestions else "Rode doctor",
        raw_response_snippet=snippet,
    )


def reddit_to_health(diag: RedditDiagnosticResult) -> HealthCheckResult:
    """Converte diagnóstico Reddit em HealthCheckResult."""
    return map_reddit_diagnostic_to_health(
        status_code=diag.status_code,
        response_preview=diag.response_preview,
        auth_mode=getattr(diag, "auth_mode", "public"),
        auth_status=getattr(diag, "auth_status", ""),
        is_valid_json=diag.is_valid_json,
        posts_count=diag.posts_count,
        error_message=diag.error_message,
        suggestions=diag.suggestions,
    )
