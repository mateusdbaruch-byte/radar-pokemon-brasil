"""Autenticação Reddit — OAuth e verificação de credenciais."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

import requests

REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
DEFAULT_USER_AGENT = "RadarPokemonBrasil/1.0 (MVP; educational)"

REDDIT_ENV_FIELDS = (
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
    "REDDIT_USERNAME",
    "REDDIT_PASSWORD",
)


class RedditAuthStatus(str, Enum):
    """Resultado da autenticação Reddit."""

    LIVE = "live"
    AUTH_FAILED = "auth_failed"
    MISSING_CREDENTIALS = "missing_credentials"
    BLOCKED = "blocked"
    PUBLIC = "public"


@dataclass
class RedditAuthResult:
    """Resultado de tentativa de autenticação."""

    status: RedditAuthStatus
    auth_mode: str
    message: str
    http_status: int | None = None
    token_obtained: bool = False


@dataclass
class RedditEnvStatus:
    """Status dos campos do .env (sem revelar valores)."""

    env_loaded: bool
    env_path_exists: bool
    fields: dict[str, bool]


def get_user_agent() -> str:
    return os.getenv("REDDIT_USER_AGENT", DEFAULT_USER_AGENT).strip() or DEFAULT_USER_AGENT


def inspect_reddit_env() -> RedditEnvStatus:
    """Verifica quais campos Reddit estão preenchidos (sem expor valores)."""
    from src.paths import PROJECT_ROOT

    env_path = PROJECT_ROOT / ".env"
    fields = {name: bool(os.getenv(name, "").strip()) for name in REDDIT_ENV_FIELDS}
    return RedditEnvStatus(
        env_loaded=any(fields.values()),
        env_path_exists=env_path.exists(),
        fields=fields,
    )


def _has_oauth_credentials() -> bool:
    return bool(
        os.getenv("REDDIT_CLIENT_ID", "").strip()
        and os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    )


def _has_user_agent() -> bool:
    ua = os.getenv("REDDIT_USER_AGENT", "").strip()
    return bool(ua) and ua != DEFAULT_USER_AGENT


def credential_requirements_met() -> tuple[bool, str]:
    """
    OAuth exige CLIENT_ID, CLIENT_SECRET e USER_AGENT personalizado.
    USERNAME/PASSWORD são opcionais (password grant para apps script).
    """
    if not _has_oauth_credentials():
        return False, "Configure REDDIT_CLIENT_ID e REDDIT_CLIENT_SECRET no .env"
    if not os.getenv("REDDIT_USER_AGENT", "").strip():
        return False, "Configure REDDIT_USER_AGENT no .env (formato Reddit oficial)"
    return True, ""


def authenticate_reddit(session: requests.Session | None = None) -> RedditAuthResult:
    """
    Autentica no Reddit via OAuth.

    - Com USERNAME/PASSWORD: grant_type=password (app script)
    - Sem USERNAME/PASSWORD: grant_type=client_credentials (read-only)
    - Sem credenciais OAuth: modo public (sem token)
    """
    sess = session or requests.Session()
    user_agent = get_user_agent()

    if not _has_oauth_credentials():
        if not os.getenv("REDDIT_USER_AGENT", "").strip():
            return RedditAuthResult(
                status=RedditAuthStatus.MISSING_CREDENTIALS,
                auth_mode="none",
                message="Sem credenciais OAuth nem User-Agent configurado",
            )
        sess.headers.update({"User-Agent": user_agent})
        return RedditAuthResult(
            status=RedditAuthStatus.PUBLIC,
            auth_mode="public",
            message="Modo público — sem OAuth (configure CLIENT_ID/SECRET para OAuth)",
        )

    ok, reason = credential_requirements_met()
    if not ok:
        return RedditAuthResult(
            status=RedditAuthStatus.MISSING_CREDENTIALS,
            auth_mode="none",
            message=reason,
        )

    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    username = os.getenv("REDDIT_USERNAME", "").strip()
    password = os.getenv("REDDIT_PASSWORD", "").strip()

    headers = {"User-Agent": user_agent}
    data: dict[str, str]
    if username and password:
        data = {"grant_type": "password", "username": username, "password": password}
        auth_mode = "oauth_password"
    else:
        data = {"grant_type": "client_credentials"}
        auth_mode = "oauth_app"

    try:
        token_resp = sess.post(
            REDDIT_TOKEN_URL,
            auth=(client_id, client_secret),
            data=data,
            headers=headers,
            timeout=15,
        )
        if token_resp.status_code == 200:
            token = token_resp.json().get("access_token")
            if token:
                sess.headers.update({"User-Agent": user_agent, "Authorization": f"Bearer {token}"})
                return RedditAuthResult(
                    status=RedditAuthStatus.LIVE,
                    auth_mode=auth_mode,
                    message="Token OAuth obtido com sucesso",
                    http_status=200,
                    token_obtained=True,
                )
        return RedditAuthResult(
            status=RedditAuthStatus.AUTH_FAILED,
            auth_mode=auth_mode,
            message=f"OAuth falhou — HTTP {token_resp.status_code}",
            http_status=token_resp.status_code,
        )
    except requests.RequestException as exc:
        return RedditAuthResult(
            status=RedditAuthStatus.AUTH_FAILED,
            auth_mode=auth_mode,
            message=f"Erro de rede na autenticação: {exc}",
        )


def apply_reddit_auth(session: requests.Session) -> RedditAuthResult:
    """Aplica autenticação na sessão e retorna resultado."""
    result = authenticate_reddit(session)
    if result.status == RedditAuthStatus.PUBLIC and result.auth_mode == "public":
        session.headers.update({"User-Agent": get_user_agent()})
    return result


def auth_status_to_connector_mode(status: RedditAuthStatus) -> str:
    """Mapeia status de auth para data_mode em connector_health."""
    mapping = {
        RedditAuthStatus.LIVE: "live",
        RedditAuthStatus.PUBLIC: "live",
        RedditAuthStatus.AUTH_FAILED: "auth_failed",
        RedditAuthStatus.MISSING_CREDENTIALS: "missing_credentials",
        RedditAuthStatus.BLOCKED: "blocked",
    }
    return mapping.get(status, "unavailable")
