"""Reddit API — política, aprovação e status gated."""

from __future__ import annotations

from dataclasses import dataclass

from src.connector_health import (
    ConnectorDataMode,
    HealthCheckResult,
    HealthStatus,
    fetch_latest_by_source,
    save_health_check,
)
from src.reddit_auth import (
    RedditAuthStatus,
    credential_requirements_met,
    inspect_reddit_env,
)

REDDIT_PENDING_MESSAGE = (
    "Reddit API requires approval/configuration. "
    "This source is disabled until credentials and approval are available."
)

POLICY_KEYWORDS = (
    "responsible builder",
    "builder policy",
    "policy",
    "approval",
    "forbidden",
    "terms of use",
    "api access",
    "not authorized",
)


def is_reddit_policy_block(status_code: int | None, response_preview: str = "") -> bool:
    """Detecta bloqueio por política/aprovação (403 ou mensagem relacionada)."""
    if status_code == 403:
        return True
    preview = (response_preview or "").lower()
    return any(kw in preview for kw in POLICY_KEYWORDS)


def reddit_health_for_gated(
    http_status: int | None = 403,
    response_preview: str = "",
    auth_mode: str = "unknown",
) -> HealthCheckResult:
    """Registro de saúde para Reddit gated/pending approval."""
    return HealthCheckResult(
        source="reddit",
        status=HealthStatus.PENDING_APPROVAL,
        data_mode=ConnectorDataMode.UNAVAILABLE,
        http_status=http_status,
        message=REDDIT_PENDING_MESSAGE,
        next_action="Solicite aprovação Reddit API; use import-prices enquanto isso",
        raw_response_snippet=(response_preview or "")[:500],
    )


def reddit_health_requires_auth(message: str = "OAuth/User-Agent não configurado") -> HealthCheckResult:
    return HealthCheckResult(
        source="reddit",
        status=HealthStatus.REQUIRES_AUTH,
        data_mode=ConnectorDataMode.MISSING_CREDENTIALS,
        http_status=None,
        message=message,
        next_action="Rode setup-env e configure credenciais Reddit",
    )


def persist_reddit_gated(
    http_status: int | None = 403,
    response_preview: str = "",
    auth_mode: str = "unknown",
) -> HealthCheckResult:
    """Salva Reddit como PENDING_APPROVAL em connector_health."""
    health = reddit_health_for_gated(http_status, response_preview, auth_mode)
    save_health_check(health)
    return health


@dataclass
class RedditPolicyStatus:
    """Resumo para reddit-policy-status."""

    env_exists: bool
    oauth_configured: bool
    user_agent_configured: bool
    last_http_status: int | None
    last_health_status: str | None
    pending_approval: bool
    requires_auth: bool
    last_message: str
    next_action: str


def get_reddit_policy_status() -> RedditPolicyStatus:
    """Monta status de política/aprovação do Reddit."""
    env = inspect_reddit_env()
    oauth_ok, oauth_msg = credential_requirements_met()

    latest = None
    for row in fetch_latest_by_source():
        if row.get("source") == "reddit":
            latest = row
            break

    last_status = latest.get("status") if latest else None
    last_http = latest.get("http_status") if latest else None
    last_msg = latest.get("message") or "" if latest else ""
    next_action = latest.get("next_action") or "" if latest else ""

    pending = last_status == HealthStatus.PENDING_APPROVAL.value
    if not pending and last_http == 403:
        pending = True

    requires_auth = (
        last_status == HealthStatus.REQUIRES_AUTH.value
        or (
            not oauth_ok
            and not pending
            and last_status not in (HealthStatus.OK.value, HealthStatus.PENDING_APPROVAL.value)
        )
    )

    if pending:
        next_action = "Aguarde aprovação Reddit API; use import-prices / Mercado Livre"
    elif requires_auth:
        next_action = "Rode setup-env e configure OAuth no .env"
    elif last_status == HealthStatus.OK.value:
        next_action = "Fonte disponível — use search-reddit ou search --sources reddit"
    elif not next_action:
        next_action = "Rode test-reddit-auth ou doctor para atualizar status"

    return RedditPolicyStatus(
        env_exists=env.env_path_exists,
        oauth_configured=oauth_ok,
        user_agent_configured=env.fields.get("REDDIT_USER_AGENT", False),
        last_http_status=last_http,
        last_health_status=last_status,
        pending_approval=pending,
        requires_auth=requires_auth and not pending,
        last_message=last_msg or REDDIT_PENDING_MESSAGE if pending else last_msg,
        next_action=next_action,
    )


def is_reddit_pending_approval() -> bool:
    """True se último status conhecido indica fonte gated."""
    return get_reddit_policy_status().pending_approval


def map_reddit_diagnostic_to_health(
    status_code: int | None,
    response_preview: str,
    auth_mode: str,
    auth_status: str,
    is_valid_json: bool,
    posts_count: int | None,
    error_message: str | None,
    suggestions: list[str],
) -> HealthCheckResult:
    """Mapeia diagnóstico Reddit para HealthCheckResult com status gated."""
    snippet = (response_preview or "")[:500]

    if is_reddit_policy_block(status_code, response_preview):
        return reddit_health_for_gated(status_code, response_preview, auth_mode)

    if auth_status == RedditAuthStatus.MISSING_CREDENTIALS.value:
        return reddit_health_requires_auth("Credenciais OAuth/User-Agent ausentes")

    if auth_status == RedditAuthStatus.AUTH_FAILED.value:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.REQUIRES_AUTH,
            data_mode=ConnectorDataMode.AUTH_FAILED,
            http_status=status_code,
            message=f"OAuth falhou ({auth_mode})",
            next_action="Verifique app no Reddit Developer Portal e aprovação de API",
            raw_response_snippet=snippet,
        )

    if status_code == 200 and is_valid_json:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=status_code,
            message=f"OK via {auth_mode} — {posts_count or 0} post(s)",
            next_action="search-reddit ou search --sources reddit",
            raw_response_snippet=snippet,
        )

    if status_code == 401:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.REQUIRES_AUTH,
            data_mode=ConnectorDataMode.AUTH_FAILED,
            http_status=401,
            message="HTTP 401 — autenticação necessária",
            next_action="Configure OAuth e aguarde aprovação da API",
            raw_response_snippet=snippet,
        )

    return HealthCheckResult(
        source="reddit",
        status=HealthStatus.WARNING,
        data_mode=ConnectorDataMode.UNAVAILABLE,
        http_status=status_code,
        message=error_message or f"Indisponível ({auth_mode})",
        next_action=suggestions[0] if suggestions else "Rode reddit-policy-status",
        raw_response_snippet=snippet,
    )
