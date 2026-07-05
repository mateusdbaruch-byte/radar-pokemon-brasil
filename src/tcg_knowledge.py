"""TCG Knowledge Layer — vocabulário e detecção do mercado Pokémon TCG Brasil."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.opportunity_models import Opportunity
from src.paths import CONFIG_DIR

VOCAB_PATH = CONFIG_DIR / "tcg_vocabulary.yml"
COLLECTION_PATH = CONFIG_DIR / "collection_aliases.yml"
RARITY_PATH = CONFIG_DIR / "rarity_terms.yml"
CONDITION_PATH = CONFIG_DIR / "condition_terms.yml"
GRADING_PATH = CONFIG_DIR / "grading_terms.yml"
JARGON_PATH = CONFIG_DIR / "market_jargon.yml"
NEGATIVE_PATH = CONFIG_DIR / "negative_terms.yml"
QUERY_TEMPLATES_PATH = CONFIG_DIR / "query_templates.yml"


@dataclass
class TCGKnowledge:
    core_terms: list[str] = field(default_factory=list)
    card_type_terms: list[str] = field(default_factory=list)
    language_terms: list[str] = field(default_factory=list)
    collections: dict[str, list[str]] = field(default_factory=dict)
    rarity_terms: list[str] = field(default_factory=list)
    condition_terms: list[str] = field(default_factory=list)
    grading_terms: list[str] = field(default_factory=list)
    buyer_jargon: list[str] = field(default_factory=list)
    seller_jargon: list[str] = field(default_factory=list)
    collector_jargon: list[str] = field(default_factory=list)
    negative_terms: list[str] = field(default_factory=list)
    enable_tcg_pocket: bool = False
    query_templates: dict[str, list[str]] = field(default_factory=dict)

    @property
    def all_tcg_terms(self) -> list[str]:
        return (
            self.core_terms
            + self.card_type_terms
            + list(self.collections.keys())
            + self.rarity_terms
        )


@dataclass
class TextSignals:
    collection: str = ""
    rarity: list[str] = field(default_factory=list)
    condition: list[str] = field(default_factory=list)
    grading: list[str] = field(default_factory=list)
    language: list[str] = field(default_factory=list)
    buyer_jargon: list[str] = field(default_factory=list)
    seller_jargon: list[str] = field(default_factory=list)
    collector_jargon: list[str] = field(default_factory=list)
    negative_context: list[str] = field(default_factory=list)
    has_tcg_context: bool = False
    has_buy_intent: bool = False
    has_sell_intent: bool = False

    def has_qualifying_signal(self) -> bool:
        return bool(
            self.has_buy_intent
            or self.has_sell_intent
            or self.collection
            or self.rarity
            or self.condition
            or self.grading
        )


@dataclass
class TextClassification:
    text: str
    card_detected: str = ""
    card_alias: str = ""
    card_confidence: int = 0
    card_detection_reason: str = ""
    signals: TextSignals = field(default_factory=TextSignals)
    opportunity_type: str = ""
    intent_score: int = 0
    opportunity_score: int = 0
    confidence_score: int = 0
    probable_opportunity: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _find_terms(text: str, terms: list[str]) -> list[str]:
    text_norm = _normalize(text)
    found: list[str] = []
    sorted_terms = sorted(terms, key=len, reverse=True)
    for term in sorted_terms:
        term_norm = _normalize(term)
        if len(term_norm) <= 3:
            if re.search(rf"\b{re.escape(term_norm)}\b", text_norm):
                found.append(term)
        elif term_norm in text_norm:
            found.append(term)
    return found


@lru_cache(maxsize=1)
def load_tcg_knowledge() -> TCGKnowledge:
    """Carrega toda a camada de conhecimento TCG dos YAMLs."""
    vocab = _load_yaml(VOCAB_PATH)
    collections_raw = _load_yaml(COLLECTION_PATH).get("collections", {}) or {}
    rarity = _load_yaml(RARITY_PATH).get("rarity_terms", []) or []
    condition = _load_yaml(CONDITION_PATH).get("condition_terms", []) or []
    grading = _load_yaml(GRADING_PATH).get("grading_terms", []) or []
    jargon = _load_yaml(JARGON_PATH)
    negative = _load_yaml(NEGATIVE_PATH)
    templates = _load_yaml(QUERY_TEMPLATES_PATH)

    collections: dict[str, list[str]] = {}
    for canonical, data in collections_raw.items():
        aliases = data.get("aliases", []) if isinstance(data, dict) else []
        collections[canonical] = [canonical] + list(aliases)

    neg_terms = list(negative.get("blocked_contexts", []) or [])
    enable_pocket = negative.get("enable_tcg_pocket", False)
    if os.getenv("ENABLE_TCG_POCKET", "").lower() in ("1", "true", "yes"):
        enable_pocket = True
    if not enable_pocket:
        pass  # TCG Pocket stays in blocked list
    elif "TCG Pocket" in neg_terms:
        neg_terms = [t for t in neg_terms if t not in ("TCG Pocket", "Pokemon TCG Pocket")]

    return TCGKnowledge(
        core_terms=vocab.get("core_terms", []) or [],
        card_type_terms=vocab.get("card_type_terms", []) or [],
        language_terms=vocab.get("language_terms", []) or [],
        collections=collections,
        rarity_terms=rarity,
        condition_terms=condition,
        grading_terms=grading,
        buyer_jargon=jargon.get("buyer_jargon", []) or [],
        seller_jargon=jargon.get("seller_jargon", []) or [],
        collector_jargon=jargon.get("collector_jargon", []) or [],
        negative_terms=neg_terms,
        enable_tcg_pocket=enable_pocket,
        query_templates={
            k: v for k, v in templates.items() if isinstance(v, list)
        },
    )


def vocab_summary_counts() -> dict[str, int]:
    """Contagens para vocab-summary."""
    kb = load_tcg_knowledge()
    alias_count = sum(len(v) for v in kb.collections.values())
    return {
        "collections": len(kb.collections),
        "aliases": alias_count,
        "rarity": len(kb.rarity_terms),
        "condition": len(kb.condition_terms),
        "grading": len(kb.grading_terms),
        "buyer_jargon": len(kb.buyer_jargon),
        "seller_jargon": len(kb.seller_jargon),
        "collector_jargon": len(kb.collector_jargon),
        "negative": len(kb.negative_terms),
        "core_terms": len(kb.core_terms),
    }


def normalize_collection_name(text: str) -> str:
    """Retorna nome canônico da coleção se detectado no texto."""
    detected = detect_collection(text)
    return detected or ""


def detect_collection(text: str, kb: TCGKnowledge | None = None) -> str:
    kb = kb or load_tcg_knowledge()
    text_norm = _normalize(text)
    best_match = ""
    best_len = 0
    for canonical, aliases in kb.collections.items():
        for alias in aliases:
            alias_norm = _normalize(alias)
            if alias_norm in text_norm and len(alias_norm) > best_len:
                best_match = canonical
                best_len = len(alias_norm)
    return best_match


def detect_rarity(text: str, kb: TCGKnowledge | None = None) -> list[str]:
    kb = kb or load_tcg_knowledge()
    return _find_terms(text, kb.rarity_terms)


def detect_condition(text: str, kb: TCGKnowledge | None = None) -> list[str]:
    kb = kb or load_tcg_knowledge()
    return _find_terms(text, kb.condition_terms)


def detect_grading(text: str, kb: TCGKnowledge | None = None) -> list[str]:
    kb = kb or load_tcg_knowledge()
    return _find_terms(text, kb.grading_terms)


def detect_language(text: str, kb: TCGKnowledge | None = None) -> list[str]:
    kb = kb or load_tcg_knowledge()
    return _find_terms(text, kb.language_terms)


def detect_market_jargon(text: str, kb: TCGKnowledge | None = None) -> dict[str, list[str]]:
    kb = kb or load_tcg_knowledge()
    return {
        "buyer": _find_terms(text, kb.buyer_jargon),
        "seller": _find_terms(text, kb.seller_jargon),
        "collector": _find_terms(text, kb.collector_jargon),
    }


def is_negative_context(text: str, kb: TCGKnowledge | None = None) -> tuple[bool, list[str]]:
    kb = kb or load_tcg_knowledge()
    found = _find_terms(text, kb.negative_terms)
    return bool(found), found


def has_tcg_context(text: str, kb: TCGKnowledge | None = None) -> bool:
    kb = kb or load_tcg_knowledge()
    terms = kb.core_terms + kb.card_type_terms
    if _find_terms(text, terms):
        return True
    if detect_collection(text, kb):
        return True
    if detect_rarity(text, kb):
        return True
    if _find_terms(text, ["liga", "myp", "copag", "tcg", "booster", "carta"]):
        return True
    return False


def analyze_text(text: str, kb: TCGKnowledge | None = None) -> TextSignals:
    kb = kb or load_tcg_knowledge()
    jargon = detect_market_jargon(text, kb)
    neg, neg_terms = is_negative_context(text, kb)
    signals = TextSignals(
        collection=detect_collection(text, kb),
        rarity=detect_rarity(text, kb),
        condition=detect_condition(text, kb),
        grading=detect_grading(text, kb),
        language=detect_language(text, kb),
        buyer_jargon=jargon["buyer"],
        seller_jargon=jargon["seller"],
        collector_jargon=jargon["collector"],
        negative_context=neg_terms,
        has_tcg_context=has_tcg_context(text, kb),
        has_buy_intent=bool(jargon["buyer"]),
        has_sell_intent=bool(jargon["seller"]),
    )
    return signals


def build_why_saved_from_signals(
    card_name: str,
    signals: TextSignals,
    domain: str = "",
    marketplace: bool = False,
) -> str:
    parts = [f"menciona {card_name}"]
    if signals.has_tcg_context:
        parts.append("Pokémon TCG")
    if signals.has_buy_intent:
        intent = signals.buyer_jargon[0] if signals.buyer_jargon else "compra"
        parts.append(f"intenção de compra '{intent}'")
    elif signals.has_sell_intent:
        intent = signals.seller_jargon[0] if signals.seller_jargon else "venda"
        parts.append(f"intenção de venda '{intent}'")
    if signals.collection:
        parts.append(f"coleção {signals.collection}")
    if signals.language:
        parts.append(signals.language[0])
    if signals.rarity:
        parts.append(signals.rarity[0])
    if signals.condition:
        parts.append(signals.condition[0])
    if signals.grading:
        parts.append(" ".join(signals.grading[:2]))
    if marketplace and domain:
        parts.append(f"marketplace {domain}")
    elif domain:
        parts.append(domain)

    return "Salvo porque " + " + ".join(parts) + "."


def enrich_opportunity(opp: Opportunity, evidence: str | None = None) -> Opportunity:
    """Enriquece oportunidade com sinais da TCG Knowledge Layer."""
    text = evidence or opp.evidence_text
    signals = analyze_text(text)

    opp.collection_detected = signals.collection
    opp.rarity_detected = ", ".join(signals.rarity)
    opp.condition_detected = ", ".join(signals.condition)
    opp.grading_detected = ", ".join(signals.grading)
    opp.language_detected = ", ".join(signals.language)
    jargon_all = signals.buyer_jargon + signals.seller_jargon + signals.collector_jargon
    opp.market_jargon_detected = ", ".join(jargon_all)
    opp.negative_context_detected = ", ".join(signals.negative_context)

    if not opp.why_saved:
        from src.opportunity_quality import extract_domain, is_marketplace_domain
        domain = extract_domain(opp.url) if opp.url else ""
        opp.why_saved = build_why_saved_from_signals(
            opp.card_name_detected,
            signals,
            domain=domain,
            marketplace=is_marketplace_domain(opp.url) if opp.url else False,
        )

    try:
        raw = json.loads(opp.raw_data_json or "{}")
    except json.JSONDecodeError:
        raw = {}
    raw["tcg_signals"] = {
        "collection": signals.collection,
        "rarity": signals.rarity,
        "condition": signals.condition,
        "grading": signals.grading,
        "language": signals.language,
        "buyer_jargon": signals.buyer_jargon,
        "seller_jargon": signals.seller_jargon,
    }
    opp.set_raw_data(raw)
    return opp


def generate_enriched_queries(
    card_name: str,
    mode: str = "light",
    buyer_only: bool = False,
    seller_only: bool = False,
    kb: TCGKnowledge | None = None,
) -> list[str]:
    """Gera queries enriquecidas para web_search."""
    kb = kb or load_tcg_knowledge()
    mode_key = mode.value if hasattr(mode, "value") else str(mode)

    if buyer_only:
        templates = kb.query_templates.get("buyer_only", [])
    elif seller_only:
        templates = kb.query_templates.get("seller_only", [])
    elif mode_key == "deep":
        templates = kb.query_templates.get("deep", [])
    else:
        templates = kb.query_templates.get("light", [])

    if not templates:
        templates = kb.query_templates.get("light", [
            'procuro {card} Pokémon TCG',
            'compro {card} Copag',
        ])

    seen: set[str] = set()
    queries: list[str] = []
    for template in templates:
        query = template.format(card=card_name).strip()
        key = query.lower()
        if key not in seen:
            seen.add(key)
            queries.append(query)
    return queries


def detect_card_in_text(
    text: str,
    known_cards: list[str] | None = None,
    card_hint: str = "",
) -> str:
    """Detecta nome de carta no texto (delega para card_detection)."""
    from src.card_detection import detect_card_in_text as _detect

    return _detect(text, known_cards=known_cards, card_hint=card_hint)


def classify_text(
    text: str,
    card_hint: str = "",
    known_cards: list[str] | None = None,
) -> TextClassification:
    """Classifica texto livre com a TCG Knowledge Layer."""
    from src.card_detection import detect_card_match
    from src.opportunity_scoring import score_opportunity

    match = detect_card_match(text, known_cards=known_cards, card_hint=card_hint)
    card = match.card
    signals = analyze_text(text)

    opp = score_opportunity(
        evidence=text,
        card_name=card or "Desconhecida",
        source="classify-text",
        platform="tcg_knowledge",
    )
    opp = enrich_opportunity(opp, text)

    probable = "nenhuma"
    if signals.negative_context:
        probable = "rejeitar — contexto negativo"
    elif signals.has_buy_intent and signals.has_tcg_context:
        probable = "buyer_demand / high_intent_lead"
    elif signals.has_sell_intent and signals.has_tcg_context:
        probable = "seller_supply / urgent_sale"
    elif signals.collection or signals.grading:
        probable = "web_signal qualificado"

    return TextClassification(
        text=text,
        card_detected=card,
        card_alias=match.alias,
        card_confidence=match.confidence,
        card_detection_reason=match.reason,
        signals=signals,
        opportunity_type=opp.opportunity_type.value,
        intent_score=opp.intent_score,
        opportunity_score=opp.opportunity_score,
        confidence_score=opp.confidence_score,
        probable_opportunity=probable,
    )
