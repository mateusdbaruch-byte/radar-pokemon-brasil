"""Filtros de qualidade e precisão do Opportunity Radar."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

from src.opportunity_models import Opportunity, OpportunityType
from src.paths import CONFIG_DIR

BLOCKED_DOMAINS_PATH = CONFIG_DIR / "blocked_domains.yml"
PRIORITY_DOMAINS_PATH = CONFIG_DIR / "priority_domains.yml"

STRICT_MIN_CONFIDENCE = 65

POKEMON_CONTEXT_TERMS = (
    "pokémon", "pokemon", "pokémon tcg", "pokemon tcg", "tcg", "carta", "card",
    "copag", "ligapokemon", "liga pokemon", "myp cards", "mypcards", "coleção",
    "colecao", "booster", "deck", "psa", "graded", "holo", "full art",
)

BUY_INTENT_TERMS = (
    "procuro", "compro", "pago", "pagando", "quero comprar", "alguém vende",
    "alguem vende", "buscando", "looking for", "wtb", "iso", "need",
)

SELL_INTENT_TERMS = (
    "vendo", "à venda", "a venda", "desapego", "abaixo da liga", "abaixo da liga",
    "preciso fazer caixa", "faço caixa", "faco caixa", "disponível", "disponivel",
    "anúncio", "anuncio",
)

URGENT_SALE_TERMS = ("desapego", "abaixo da liga", "preciso fazer caixa", "faço caixa", "faco caixa")

GENERIC_CONTENT_TERMS = (
    "dicionário", "dicionario", "definição", "definicao", "significado", "sinônimo",
    "sinonimo", "letra da música", "letra de", "lyrics", "notícia esportiva",
    "campeonato", "futebol", "gol ", "placar", "reclamação", "reclamacao",
)

SOCIAL_DOMAINS = frozenset({
    "facebook.com", "instagram.com", "tiktok.com", "youtube.com",
})

BUYER_ONLY_TYPES = frozenset({
    OpportunityType.BUYER_DEMAND,
    OpportunityType.HIGH_INTENT_LEAD,
    OpportunityType.DISCUSSION_SIGNAL,
})

SELLER_ONLY_TYPES = frozenset({
    OpportunityType.SELLER_SUPPLY,
    OpportunityType.URGENT_SALE,
    OpportunityType.UNDERPRICED_LISTING,
})


@dataclass
class QualityFilterConfig:
    strict: bool = False
    buyer_only: bool = False
    seller_only: bool = False
    min_confidence: int = STRICT_MIN_CONFIDENCE


@dataclass
class QualityEvaluation:
    accepted: bool
    reason: str = ""
    why_saved: str = ""
    domain: str = ""
    pokemon_terms: list[str] = field(default_factory=list)
    intent_terms: list[str] = field(default_factory=list)
    refined_type: OpportunityType | None = None


def _load_domain_list(path: Path, key: str = "domains") -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if isinstance(data.get(key), list):
        return [d.lower().strip() for d in data[key]]
    marketplace = data.get("marketplace", []) or []
    community = data.get("community", []) or []
    return [d.lower().strip() for d in marketplace + community]


def load_blocked_domains() -> list[str]:
    return _load_domain_list(BLOCKED_DOMAINS_PATH)


def load_priority_domains() -> tuple[list[str], list[str]]:
    if not PRIORITY_DOMAINS_PATH.exists():
        return [], []
    with open(PRIORITY_DOMAINS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    marketplace = [d.lower().strip() for d in data.get("marketplace", []) or []]
    community = [d.lower().strip() for d in data.get("community", []) or []]
    return marketplace, community


def extract_domain(url: str) -> str:
    netloc = urlparse(url or "").netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def domain_matches(domain: str, patterns: list[str]) -> bool:
    if not domain:
        return False
    for pattern in patterns:
        if domain == pattern or domain.endswith("." + pattern):
            return True
    return False


def is_blocked_domain(url: str, blocked: list[str] | None = None) -> bool:
    blocked = blocked if blocked is not None else load_blocked_domains()
    return domain_matches(extract_domain(url), blocked)


def is_marketplace_domain(url: str) -> bool:
    marketplace, _ = load_priority_domains()
    return domain_matches(extract_domain(url), marketplace)


def is_community_domain(url: str) -> bool:
    _, community = load_priority_domains()
    return domain_matches(extract_domain(url), community)


def is_priority_domain(url: str) -> bool:
    marketplace, community = load_priority_domains()
    domain = extract_domain(url)
    return domain_matches(domain, marketplace) or domain_matches(domain, community)


def is_social_domain(url: str) -> bool:
    return domain_matches(extract_domain(url), list(SOCIAL_DOMAINS))


def _find_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    text_lower = text.lower()
    found: list[str] = []
    for term in terms:
        if term in text_lower:
            found.append(term)
    return found


def mentions_card(text: str, card_name: str) -> bool:
    if not card_name:
        return False
    return card_name.lower() in text.lower()


def has_pokemon_context(text: str) -> tuple[bool, list[str]]:
    terms = _find_terms(text, POKEMON_CONTEXT_TERMS)
    return bool(terms), terms


def has_buy_intent(text: str) -> tuple[bool, list[str]]:
    terms = _find_terms(text, BUY_INTENT_TERMS)
    return bool(terms), terms


def has_sell_intent(text: str) -> tuple[bool, list[str]]:
    terms = _find_terms(text, SELL_INTENT_TERMS)
    return bool(terms), terms


def is_generic_content(text: str, url: str) -> bool:
    combined = f"{text} {url}".lower()
    if _find_terms(combined, GENERIC_CONTENT_TERMS):
        return True
    domain = extract_domain(url)
    generic_paths = ("/procuro", "/significado", "/sinonimo", "/letras/", "/wiki/")
    return any(p in urlparse(url).path.lower() for p in generic_paths)


def has_clear_intent(text: str) -> tuple[bool, list[str]]:
    buy, buy_terms = has_buy_intent(text)
    sell, sell_terms = has_sell_intent(text)
    return buy or sell, buy_terms + sell_terms


def social_has_relevant_evidence(text: str, card_name: str) -> bool:
    if not mentions_card(text, card_name):
        return False
    has_ctx, _ = has_pokemon_context(text)
    if not has_ctx:
        return False
    has_intent, _ = has_clear_intent(text)
    return has_intent


def classify_refined_type(
    opp: Opportunity,
    text: str,
    domain: str,
) -> OpportunityType:
    buy, buy_terms = has_buy_intent(text)
    sell, sell_terms = has_sell_intent(text)
    urgent = bool(_find_terms(text, URGENT_SALE_TERMS))

    if opp.opportunity_type == OpportunityType.WISHLIST_LEAD:
        return OpportunityType.HIGH_INTENT_LEAD

    if is_marketplace_domain(f"https://{domain}") or opp.opportunity_type == OpportunityType.MARKETPLACE_LISTING:
        if sell or opp.price:
            if urgent:
                return OpportunityType.URGENT_SALE
            if opp.price and opp.intent_score >= 50:
                return OpportunityType.UNDERPRICED_LISTING
            return OpportunityType.SELLER_SUPPLY

    if buy and opp.intent_score >= 85:
        return OpportunityType.BUYER_DEMAND
    if buy and opp.intent_score >= 70:
        return OpportunityType.HIGH_INTENT_LEAD
    if buy:
        return OpportunityType.BUYER_DEMAND

    if sell:
        if urgent:
            return OpportunityType.URGENT_SALE
        return OpportunityType.SELLER_SUPPLY

    if opp.opportunity_type == OpportunityType.DISCUSSION and buy:
        return OpportunityType.DISCUSSION_SIGNAL

    if opp.opportunity_type == OpportunityType.DISCUSSION:
        probable = any(
            t in text.lower()
            for t in ("procuro", "compro", "looking for", "wtb", "quero")
        )
        if probable and mentions_card(text, opp.card_name_detected):
            return OpportunityType.DISCUSSION_SIGNAL

    return opp.opportunity_type


def build_why_saved(
    card_name: str,
    pokemon_terms: list[str],
    intent_terms: list[str],
    domain: str,
    opp_type: OpportunityType,
) -> str:
    ctx = pokemon_terms[0] if pokemon_terms else "Pokémon TCG"
    intent = intent_terms[0] if intent_terms else opp_type.value.replace("_", " ")
    domain_note = f" em {domain}" if domain else ""
    return (
        f"Salvo porque menciona {card_name} + {ctx} + "
        f"intenção '{intent}'{domain_note}."
    )


def evaluate_hit(
    title: str,
    snippet: str,
    url: str,
    card_name: str,
    opp: Opportunity,
    config: QualityFilterConfig,
) -> QualityEvaluation:
    text = f"{title} {snippet}".strip()
    domain = extract_domain(url)
    pokemon_ok, pokemon_terms = has_pokemon_context(text)
    intent_ok, intent_terms = has_clear_intent(text)
    card_ok = mentions_card(text, card_name)

    if is_blocked_domain(url):
        return QualityEvaluation(False, f"domínio bloqueado: {domain}", domain=domain)

    if is_generic_content(text, url):
        return QualityEvaluation(False, "conteúdo genérico (dicionário/notícia/música)", domain=domain)

    if not card_ok:
        return QualityEvaluation(False, f"não menciona a carta monitorada ({card_name})", domain=domain)

    if intent_ok and not pokemon_ok:
        return QualityEvaluation(False, "intenção sem contexto Pokémon/TCG/carta", domain=domain)

    if not pokemon_ok and not is_priority_domain(url):
        return QualityEvaluation(False, "sem contexto Pokémon/TCG e fonte não priorizada", domain=domain)

    if is_social_domain(url) and not social_has_relevant_evidence(text, card_name):
        return QualityEvaluation(
            False,
            f"rede social ({domain}) sem evidência clara de Pokémon + carta + intenção",
            domain=domain,
        )

    relevant_source = intent_ok or is_priority_domain(url)
    if config.strict and not relevant_source:
        return QualityEvaluation(
            False,
            "modo strict: sem intenção clara nem fonte marketplace/comunidade",
            domain=domain,
        )

    if config.strict and opp.confidence_score < config.min_confidence:
        return QualityEvaluation(
            False,
            f"modo strict: confidence {opp.confidence_score} < {config.min_confidence}",
            domain=domain,
        )

    refined = classify_refined_type(opp, text, domain)

    if config.buyer_only and refined not in BUYER_ONLY_TYPES:
        return QualityEvaluation(
            False,
            f"buyer-only: tipo {refined.value} não é demanda de compra",
            domain=domain,
        )

    if config.seller_only and refined not in SELLER_ONLY_TYPES:
        return QualityEvaluation(
            False,
            f"seller-only: tipo {refined.value} não é oferta de venda",
            domain=domain,
        )

    if config.buyer_only and refined == OpportunityType.DISCUSSION_SIGNAL:
        strong = any(t in text.lower() for t in ("procuro", "compro", "wtb", "looking for", "quero comprar"))
        if not strong:
            return QualityEvaluation(
                False,
                "buyer-only: discussion_signal sem sinal forte de procura",
                domain=domain,
            )

    why = build_why_saved(card_name, pokemon_terms, intent_terms, domain, refined)
    return QualityEvaluation(
        True,
        why_saved=why,
        domain=domain,
        pokemon_terms=pokemon_terms,
        intent_terms=intent_terms,
        refined_type=refined,
    )
