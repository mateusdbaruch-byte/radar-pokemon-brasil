"""Conversão de diagnósticos em registros de saúde."""

from __future__ import annotations

from src.connector_health import ConnectorDataMode, HealthCheckResult, HealthStatus
from src.connectors.mercado_livre import MLDiagnosticResult
from src.connectors.reddit import RedditDiagnosticResult


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
    if diag.status_code == 200 and diag.is_valid_json:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=diag.status_code,
            message=f"OK via {mode_label} — {diag.posts_count or 0} post(s)",
            next_action="search --live-only",
            raw_response_snippet=snippet,
        )
    if diag.status_code == 403:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=403,
            message=f"Bloqueado ({mode_label})",
            next_action="REDDIT_USER_AGENT ou OAuth no .env",
            raw_response_snippet=snippet,
        )
    return HealthCheckResult(
        source="reddit",
        status=HealthStatus.ERROR,
        data_mode=ConnectorDataMode.UNAVAILABLE,
        http_status=diag.status_code,
        message=diag.error_message or f"Falha ({mode_label})",
        next_action=diag.suggestions[0] if diag.suggestions else "Rode doctor",
        raw_response_snippet=snippet,
    )


def _is_forbidden_json(diag: MLDiagnosticResult) -> bool:
    return getattr(diag, "is_forbidden", False)
