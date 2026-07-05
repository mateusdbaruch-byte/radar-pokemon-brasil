"""Scanner de oportunidades — orquestra fontes automatizadas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from src.connectors.mercado_livre import MercadoLivreConnector
from src.connectors.web_search import (
    ProgressCallback,
    ScanMode,
    WebSearchConfig,
    WebSearchConnector,
    WebSearchScanStats,
)
from src.models import DataMode
from src.opportunity_db import fetch_wishlist_leads
from src.opportunity_models import Opportunity
from src.opportunity_quality import QualityFilterConfig
from src.opportunity_scoring import score_opportunity, wishlist_lead_to_opportunity
from src.search_profiles import SearchProfile, get_search_profile
from src.source_registry import SourceAccess, SourceInfo, get_source_registry, parse_source_list

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    opportunities: list[Opportunity] = field(default_factory=list)
    skipped_sources: list[str] = field(default_factory=list)
    live_sources: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    web_search_stats: WebSearchScanStats | None = None
    urls_deduplicated_in_scan: int = 0
    results_rejected: int = 0
    live_opportunities: int = 0
    opt_in_opportunities: int = 0


def _should_skip(info: SourceInfo) -> bool:
    return info.access in (
        SourceAccess.PENDING_ACCESS,
        SourceAccess.PENDING_APPROVAL,
        SourceAccess.BLOCKED,
    )


def _scan_web_search(
    cards: list[str],
    limit: int,
    mode: ScanMode,
    max_queries: int | None,
    on_progress: ProgressCallback | None,
    quality_config: QualityFilterConfig | None = None,
    profile: SearchProfile | None = None,
) -> tuple[list[Opportunity], WebSearchScanStats | None]:
    config = WebSearchConfig.from_env(mode)
    connector = WebSearchConnector(config=config)
    if not connector.is_configured():
        return [], None

    qcfg = quality_config or QualityFilterConfig()
    templates = profile.query_templates if profile else None
    per_query = max(1, limit // max(len(templates or [1]), 1))
    scan = connector.scan_cards(
        cards,
        limit_per_query=per_query,
        mode=mode,
        max_queries=max_queries,
        on_progress=on_progress,
        quality_config=qcfg,
        profile_name=profile.name if profile else "",
        query_templates=templates,
    )
    return scan.opportunities, scan.stats


def _card_matches_watchlist(lead_card: str, cards: list[str]) -> bool:
    lc = lead_card.lower()
    return any(c.lower() in lc or lc.startswith(c.lower()) for c in cards)


def _scan_wishlist(cards: list[str]) -> list[Opportunity]:
    leads = fetch_wishlist_leads()
    opps: list[Opportunity] = []
    for lead in leads:
        if _card_matches_watchlist(lead.card_name, cards):
            opps.append(wishlist_lead_to_opportunity(lead))
    return opps


def _scan_mercado_livre(cards: list[str], limit: int) -> list[Opportunity]:
    connector = MercadoLivreConnector()
    results = connector.search_cards(cards, limit_per_card=limit)
    opps: list[Opportunity] = []
    for r in results:
        evidence = f"{r.title} {r.text_snippet}".strip()
        opp = score_opportunity(
            evidence=evidence,
            card_name=r.card_name_detected,
            source="mercado_livre",
            platform="mercado_livre",
            url=r.url,
            author=r.author_or_seller,
            is_marketplace=True,
            urgency_hint=45,
        )
        opp.price = r.price
        opp.currency = r.currency
        opp.data_mode = DataMode.LIVE
        opp.set_raw_data(r.raw_data_json)
        opps.append(opp)
    return opps


def _count_by_data_mode(opps: list[Opportunity]) -> tuple[int, int]:
    live = sum(1 for o in opps if o.data_mode == DataMode.LIVE)
    opt_in = sum(1 for o in opps if o.data_mode == DataMode.OPT_IN)
    return live, opt_in


def scan_opportunities(
    cards: list[str],
    sources: str,
    limit: int = 20,
    mode: ScanMode = ScanMode.LIGHT,
    max_queries: int | None = None,
    on_web_search_progress: ProgressCallback | None = None,
    strict: bool = False,
    buyer_only: bool = False,
    seller_only: bool = False,
    profile: str | None = None,
) -> ScanResult:
    """Executa scan nas fontes selecionadas."""
    result = ScanResult()
    registry = get_source_registry()
    selected = parse_source_list(sources)

    search_profile = get_search_profile(profile) if profile else None
    if profile and not search_profile:
        result.messages.append(f"Perfil desconhecido: {profile}")
        return result

    if search_profile:
        quality_config = search_profile.to_quality_config()
        if strict:
            quality_config.strict = True
        if buyer_only:
            quality_config.buyer_only = True
        if seller_only:
            quality_config.seller_only = True
    else:
        quality_config = QualityFilterConfig(
            strict=strict,
            buyer_only=buyer_only,
            seller_only=seller_only,
        )

    for source_name in selected:
        info = registry.get(source_name)
        if not info:
            result.messages.append(f"Fonte desconhecida: {source_name}")
            continue

        if _should_skip(info):
            result.skipped_sources.append(source_name)
            result.messages.append(
                f"{info.label}: {info.access.value} — {info.message}"
            )
            continue

        if info.access == SourceAccess.REQUIRES_AUTH:
            result.skipped_sources.append(source_name)
            result.messages.append(f"{info.label}: configure credenciais — {info.next_action}")
            continue

        try:
            stats = None
            if source_name == "web_search":
                opps, stats = _scan_web_search(
                    cards,
                    limit,
                    mode,
                    max_queries,
                    on_web_search_progress,
                    quality_config,
                    profile=search_profile,
                )
                result.web_search_stats = stats
                if stats:
                    result.urls_deduplicated_in_scan = stats.urls_deduplicated
                    result.results_rejected = stats.results_rejected
            elif source_name == "wishlist":
                opps = _scan_wishlist(cards)
            elif source_name == "mercado_livre":
                opps = _scan_mercado_livre(cards, limit)
            else:
                result.skipped_sources.append(source_name)
                result.messages.append(f"{info.label}: conector não implementado ainda")
                continue

            if opps:
                result.live_sources.append(source_name)
                result.opportunities.extend(opps)
            elif source_name == "web_search" and stats and stats.queries_executed > 0:
                result.messages.append(
                    f"{info.label}: {stats.queries_success}/{stats.queries_executed} queries OK, "
                    f"{stats.results_rejected} rejeitados, "
                    f"{stats.opportunities_built} aceitos"
                )
            else:
                result.messages.append(f"{info.label}: nenhum resultado nesta execução")

        except Exception as exc:
            logger.exception("Erro em %s", source_name)
            result.messages.append(f"{info.label}: erro parcial — {exc}")

    result.opportunities.sort(key=lambda o: o.opportunity_score, reverse=True)
    if limit:
        result.opportunities = result.opportunities[: limit * len(selected)]
    result.live_opportunities, result.opt_in_opportunities = _count_by_data_mode(
        result.opportunities
    )
    return result
