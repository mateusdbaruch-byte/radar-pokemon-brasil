"""Pontuação de oportunidades."""

from __future__ import annotations

from src.models import DataMode, IntentType
from src.opportunity_models import Opportunity, OpportunityType, WishlistLead
from src.scoring import apply_scoring_to_result, extract_price_from_text


URGENCY_MAP = {"alta": 90, "high": 90, "media": 60, "medium": 60, "baixa": 30, "low": 30}


def urgency_from_label(label: str) -> int:
    return URGENCY_MAP.get((label or "media").lower().strip(), 50)


def intent_to_opportunity_type(intent: IntentType) -> OpportunityType:
    mapping = {
        IntentType.BUY_INTENT: OpportunityType.BUYER_INTENT,
        IntentType.SELL_INTENT: OpportunityType.SELLER_INTENT,
        IntentType.PRICE_REFERENCE: OpportunityType.MARKETPLACE_LISTING,
        IntentType.DISCUSSION: OpportunityType.DISCUSSION,
        IntentType.UNKNOWN: OpportunityType.WEB_SIGNAL,
    }
    return mapping.get(intent, OpportunityType.WEB_SIGNAL)


def recommended_action_for(opp_type: OpportunityType, intent_score: int) -> str:
    if opp_type == OpportunityType.BUYER_INTENT:
        if intent_score >= 85:
            return "Contatar comprador — alta intenção de compra"
        return "Monitorar — possível comprador"
    if opp_type == OpportunityType.SELLER_INTENT:
        return "Avaliar oferta — vendedor identificado"
    if opp_type == OpportunityType.WISHLIST_LEAD:
        return "Contatar lead opt-in da wishlist"
    if opp_type == OpportunityType.MARKETPLACE_LISTING:
        return "Comparar preço com mercado"
    return "Revisar sinal público"


def score_opportunity(
    evidence: str,
    card_name: str,
    source: str,
    platform: str,
    url: str = "",
    author: str = "",
    is_marketplace: bool = False,
    urgency_hint: int = 50,
) -> Opportunity:
    """Classifica e pontua uma evidência de oportunidade."""
    intent_type, intent_score = apply_scoring_to_result(
        evidence, is_marketplace_listing=is_marketplace
    )
    price, currency = extract_price_from_text(evidence)
    opp_type = intent_to_opportunity_type(intent_type)

    confidence = min(100, 40 + intent_score // 2)
    if url.startswith("http"):
        confidence = min(100, confidence + 10)
    if author:
        confidence = min(100, confidence + 5)

    opportunity_score = min(
        100,
        int(intent_score * 0.5 + urgency_hint * 0.3 + confidence * 0.2),
    )

    from src.normalizer import normalize_card_name

    return Opportunity(
        opportunity_type=opp_type,
        source=source,
        platform=platform,
        card_name_detected=card_name,
        normalized_card_name=normalize_card_name(card_name),
        evidence_text=evidence[:2000],
        url=url,
        author_or_seller=author,
        price=price,
        currency=currency,
        intent_score=intent_score,
        urgency_score=urgency_hint,
        opportunity_score=opportunity_score,
        confidence_score=confidence,
        recommended_action=recommended_action_for(opp_type, intent_score),
    )


def wishlist_lead_to_opportunity(lead: WishlistLead) -> Opportunity:
    """Converte lead opt-in em oportunidade de comprador."""
    evidence = (
        f"{lead.name} procura {lead.card_name}"
        f"{f' ({lead.collection})' if lead.collection else ''}"
        f"{f' até R${lead.max_price:.2f}' if lead.max_price else ''}"
        f" — {lead.notes}"
    ).strip()
    urgency = urgency_from_label(lead.urgency)
    opp = score_opportunity(
        evidence=evidence,
        card_name=lead.card_name,
        source="wishlist",
        platform=lead.source,
        url="",
        author=lead.name,
        urgency_hint=urgency,
    )
    opp.opportunity_type = OpportunityType.WISHLIST_LEAD
    opp.opportunity_score = min(100, opp.opportunity_score + 15)
    opp.data_mode = DataMode.OPT_IN
    opp.recommended_action = recommended_action_for(
        OpportunityType.WISHLIST_LEAD, opp.intent_score
    )
    opp.set_raw_data(lead.to_db_row())
    return opp
