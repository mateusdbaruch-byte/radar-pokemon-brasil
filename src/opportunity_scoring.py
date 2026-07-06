"""Pontuação de oportunidades."""

from __future__ import annotations

from src.models import DataMode, IntentType
from src.opportunity_models import Opportunity, OpportunityType, WishlistLead
from src.opportunity_quality import (
    classify_refined_type,
    extract_domain,
    has_buy_intent,
    has_pokemon_context,
    has_sell_intent,
    is_community_domain,
    is_marketplace_domain,
    is_social_domain,
)
from src.scoring import apply_scoring_to_result, extract_price_from_text


URGENCY_MAP = {"alta": 90, "high": 90, "media": 60, "medium": 60, "baixa": 30, "low": 30}

EXPLICIT_BUY_BOOST = ("procuro", "compro", "pago", "alguém vende", "alguem vende")
EXPLICIT_SELL_BOOST = ("vendo", "desapego", "abaixo da liga", "preciso fazer caixa")


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
    buyer_types = {
        OpportunityType.BUYER_INTENT,
        OpportunityType.BUYER_DEMAND,
        OpportunityType.HIGH_INTENT_LEAD,
        OpportunityType.DISCUSSION_SIGNAL,
        OpportunityType.WISHLIST_LEAD,
    }
    seller_types = {
        OpportunityType.SELLER_INTENT,
        OpportunityType.SELLER_SUPPLY,
        OpportunityType.URGENT_SALE,
        OpportunityType.UNDERPRICED_LISTING,
        OpportunityType.MARKETPLACE_LISTING,
    }
    if opp_type in buyer_types:
        if intent_score >= 85:
            return "Contatar comprador — alta intenção de compra"
        return "Monitorar — possível comprador"
    if opp_type in seller_types:
        return "Avaliar oferta — vendedor identificado"
    if opp_type == OpportunityType.WISHLIST_LEAD:
        return "Contatar lead opt-in da wishlist"
    return "Revisar sinal público"


def _confidence_adjustments(
    evidence: str,
    card_name: str,
    url: str,
    intent_score: int,
    price: float | None,
) -> int:
    confidence = min(100, 40 + intent_score // 2)
    text = evidence.lower()
    domain = extract_domain(url)

    if url.startswith("http"):
        confidence = min(100, confidence + 10)

    has_card = card_name.lower() in text
    has_ctx, _ = has_pokemon_context(evidence)
    buy, _ = has_buy_intent(evidence)
    sell, _ = has_sell_intent(evidence)

    if has_card and has_ctx and (buy or sell):
        confidence = min(100, confidence + 20)
    elif has_card and has_ctx:
        confidence = min(100, confidence + 10)

    if is_marketplace_domain(url):
        confidence = min(100, confidence + 12)
    elif is_community_domain(url) and not is_social_domain(url):
        confidence = min(100, confidence + 8)

    if any(t in text for t in EXPLICIT_BUY_BOOST + EXPLICIT_SELL_BOOST):
        confidence = min(100, confidence + 8)

    if price:
        confidence = min(100, confidence + 10)

    if is_social_domain(url) and not (has_card and has_ctx and (buy or sell)):
        confidence = max(0, confidence - 25)

    if len(evidence.strip()) < 40:
        confidence = max(0, confidence - 15)

    if not buy and not sell and not is_marketplace_domain(url):
        confidence = max(0, confidence - 10)

    ambiguous = ("troco", "negocio", "negócio", "interessado")
    if any(a in text for a in ambiguous) and not (buy or sell):
        confidence = max(0, confidence - 8)

    return confidence


def _opportunity_score_adjustments(
    intent_score: int,
    urgency_hint: int,
    confidence: int,
    evidence: str,
    url: str,
    price: float | None,
) -> int:
    score = min(100, int(intent_score * 0.5 + urgency_hint * 0.3 + confidence * 0.2))
    text = evidence.lower()

    if any(t in text for t in EXPLICIT_BUY_BOOST):
        score = min(100, score + 8)
    if any(t in text for t in EXPLICIT_SELL_BOOST):
        score = min(100, score + 8)
    if is_marketplace_domain(url) or is_community_domain(url):
        score = min(100, score + 5)
    if price:
        score = min(100, score + 5)
    if is_social_domain(url) and len(text) < 60:
        score = max(0, score - 12)
    if not has_buy_intent(evidence)[0] and not has_sell_intent(evidence)[0]:
        score = max(0, score - 8)

    return score


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
        evidence, is_marketplace_listing=is_marketplace or is_marketplace_domain(url)
    )
    price, currency = extract_price_from_text(evidence)
    opp_type = intent_to_opportunity_type(intent_type)

    confidence = _confidence_adjustments(evidence, card_name, url, intent_score, price)
    if author:
        confidence = min(100, confidence + 5)

    opportunity_score = _opportunity_score_adjustments(
        intent_score, urgency_hint, confidence, evidence, url, price
    )

    from src.normalizer import normalize_card_name

    opp = Opportunity(
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

    domain = extract_domain(url)
    opp.opportunity_type = classify_refined_type(opp, evidence, domain)
    opp.recommended_action = recommended_action_for(opp.opportunity_type, intent_score)
    return opp


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
    opp.opportunity_type = OpportunityType.HIGH_INTENT_LEAD
    opp.opportunity_score = min(100, opp.opportunity_score + 15)
    opp.confidence_score = min(100, opp.confidence_score + 15)
    opp.data_mode = DataMode.OPT_IN
    opp.why_saved = (
        f"Salvo porque lead opt-in procura {lead.card_name}"
        f"{f' até R${lead.max_price:.2f}' if lead.max_price else ''}."
    )
    opp.recommended_action = recommended_action_for(
        OpportunityType.HIGH_INTENT_LEAD, opp.intent_score
    )
    opp.set_raw_data(lead.to_db_row())
    return opp
