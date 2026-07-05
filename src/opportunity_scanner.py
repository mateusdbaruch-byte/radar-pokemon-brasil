"""Scanner de oportunidades — orquestra fontes automatizadas."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.connectors.mercado_livre import MercadoLivreConnector
from src.connectors.web_search import WebSearchConnector
from src.models import DataMode
from src.opportunity_db import fetch_wishlist_leads
from src.opportunity_models import Opportunity
from src.opportunity_scoring import score_opportunity, wishlist_lead_to_opportunity
from src.source_registry import SourceAccess, SourceInfo, get_source_registry, parse_source_list

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    opportunities: list[Opportunity] = field(default_factory=list)
    skipped_sources: list[str] = field(default_factory=list)
    live_sources: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def _should_skip(info: SourceInfo) -> bool:
    return info.access in (
        SourceAccess.PENDING_ACCESS,
        SourceAccess.PENDING_APPROVAL,
        SourceAccess.BLOCKED,
    )


def _scan_web_search(cards: list[str], limit: int) -> list[Opportunity]:
    connector = WebSearchConnector()
    if not connector.is_configured():
        return []
    per_query = max(1, limit // 7)
    return connector.scan_cards(cards, limit_per_query=per_query)


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


def scan_opportunities(
    cards: list[str],
    sources: str,
    limit: int = 20,
) -> ScanResult:
    """Executa scan nas fontes selecionadas."""
    result = ScanResult()
    registry = get_source_registry()
    selected = parse_source_list(sources)

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
            if source_name == "web_search":
                opps = _scan_web_search(cards, limit)
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
            else:
                result.messages.append(f"{info.label}: nenhum resultado nesta execução")

        except Exception as exc:
            logger.exception("Erro em %s", source_name)
            result.messages.append(f"{info.label}: erro — {exc}")

    result.opportunities.sort(key=lambda o: o.opportunity_score, reverse=True)
    if limit:
        result.opportunities = result.opportunities[: limit * len(selected)]
    return result
