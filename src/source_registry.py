"""Registro de fontes — acesso permitido, pendente ou bloqueado."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from src.connector_health import HealthStatus


class SourceAccess(str, Enum):
    LIVE = "live"
    REQUIRES_AUTH = "requires_auth"
    PENDING_ACCESS = "pending_access"
    PENDING_APPROVAL = "pending_approval"
    BLOCKED = "blocked"


@dataclass
class SourceInfo:
    name: str
    label: str
    access: SourceAccess
    message: str
    next_action: str


def _web_search_access() -> SourceAccess:
    provider = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
    if not provider:
        return SourceAccess.REQUIRES_AUTH
    keys = {
        "bing": os.getenv("BING_SEARCH_API_KEY", "").strip(),
        "google": os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
        and os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip(),
        "serpapi": os.getenv("SERPAPI_KEY", "").strip(),
    }
    if provider in keys and keys[provider]:
        return SourceAccess.LIVE
    return SourceAccess.REQUIRES_AUTH


def get_source_registry() -> dict[str, SourceInfo]:
    """Status de todas as fontes planejadas."""
    ml_token = (
        os.getenv("MERCADOLIVRE_ACCESS_TOKEN", "").strip()
        or os.getenv("ML_ACCESS_TOKEN", "").strip()
    )
    reddit_oauth = bool(
        os.getenv("REDDIT_CLIENT_ID", "").strip()
        and os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    )

    return {
        "web_search": SourceInfo(
            name="web_search",
            label="Busca web (API oficial)",
            access=_web_search_access(),
            message="Bing / Google / SerpAPI via .env",
            next_action="Configure WEB_SEARCH_PROVIDER e chave no .env",
        ),
        "wishlist": SourceInfo(
            name="wishlist",
            label="Lista de desejos (opt-in)",
            access=SourceAccess.LIVE,
            message="Leads autorizados importados ou cadastrados",
            next_action="add-wishlist-lead ou import-wishlist",
        ),
        "mercado_livre": SourceInfo(
            name="mercado_livre",
            label="Mercado Livre API",
            access=SourceAccess.LIVE,
            message="API oficial — pode retornar 403 em datacenter",
            next_action="Teste em rede residencial ou MERCADOLIVRE_ACCESS_TOKEN",
        ),
        "reddit": SourceInfo(
            name="reddit",
            label="Reddit API",
            access=(
                SourceAccess.PENDING_APPROVAL
                if not reddit_oauth
                else SourceAccess.LIVE
            ),
            message="Exige OAuth e aprovação Responsible Builder Policy",
            next_action="reddit-policy-status",
        ),
        "olx": SourceInfo(
            name="olx",
            label="OLX",
            access=SourceAccess.PENDING_ACCESS,
            message="Sem API pública autorizada no MVP",
            next_action="Aguardar parceria ou API oficial",
        ),
        "shopee": SourceInfo(
            name="shopee",
            label="Shopee",
            access=SourceAccess.PENDING_ACCESS,
            message="Requer API/parceria oficial",
            next_action="Aguardar integração autorizada",
        ),
        "bigdex": SourceInfo(
            name="bigdex",
            label="BigDex",
            access=SourceAccess.PENDING_ACCESS,
            message="Requer acesso permitido ou parceria",
            next_action="Aguardar conector futuro",
        ),
        "liga_pokemon": SourceInfo(
            name="liga_pokemon",
            label="LigaPokemon",
            access=SourceAccess.PENDING_ACCESS,
            message="Sem scraping — apenas API/parceria futura",
            next_action="Aguardar acesso autorizado",
        ),
        "myp_cards": SourceInfo(
            name="myp_cards",
            label="MYP Cards",
            access=SourceAccess.PENDING_ACCESS,
            message="Sem scraping — apenas API/parceria futura",
            next_action="Aguardar acesso autorizado",
        ),
        "discord_bot": SourceInfo(
            name="discord_bot",
            label="Discord bot autorizado",
            access=SourceAccess.PENDING_ACCESS,
            message="Bot deve ser adicionado ao canal com permissão",
            next_action="Configure bot e canais autorizados (futuro)",
        ),
        "telegram_bot": SourceInfo(
            name="telegram_bot",
            label="Telegram bot autorizado",
            access=SourceAccess.PENDING_ACCESS,
            message="Bot em grupos/canais com opt-in",
            next_action="Configure bot Telegram (futuro)",
        ),
        "instagram_pro": SourceInfo(
            name="instagram_pro",
            label="Instagram profissional próprio",
            access=SourceAccess.PENDING_ACCESS,
            message="Apenas conta própria via Meta API autorizada",
            next_action="Meta Business API com permissão",
        ),
        "facebook_page": SourceInfo(
            name="facebook_page",
            label="Facebook Page própria",
            access=SourceAccess.PENDING_ACCESS,
            message="Apenas página própria via Meta API",
            next_action="Meta Graph API com permissão",
        ),
    }


def access_to_health_status(access: SourceAccess) -> HealthStatus:
    mapping = {
        SourceAccess.LIVE: HealthStatus.OK,
        SourceAccess.REQUIRES_AUTH: HealthStatus.REQUIRES_AUTH,
        SourceAccess.PENDING_ACCESS: HealthStatus.PENDING_ACCESS,
        SourceAccess.PENDING_APPROVAL: HealthStatus.PENDING_APPROVAL,
        SourceAccess.BLOCKED: HealthStatus.BLOCKED,
    }
    return mapping.get(access, HealthStatus.WARNING)


def parse_source_list(sources: str) -> list[str]:
    return [s.strip().lower() for s in sources.split(",") if s.strip()]
