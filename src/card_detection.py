"""Detecção inteligente de cartas em texto de mercado Pokémon TCG."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.paths import CONFIG_DIR, DEFAULT_WATCHLIST

CARD_ALIASES_PATH = CONFIG_DIR / "card_aliases.yml"
NON_CARD_TERMS_PATH = CONFIG_DIR / "non_card_terms.yml"

MIN_CONFIDENCE = 50


@dataclass
class CardCandidate:
    canonical_name: str
    matched_alias: str
    confidence: int
    reason: str


@dataclass
class CardDetectionResult:
    card: str = ""
    alias: str = ""
    confidence: int = 0
    reason: str = ""
    candidates: list[CardCandidate] = field(default_factory=list)


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """Remove acentos, lowercase, normaliza espaços; mantém &, /, -."""
    text = strip_accents(text.lower().strip())
    text = re.sub(r"\s+", " ", text)
    return text


@lru_cache(maxsize=1)
def _load_card_alias_map() -> list[tuple[str, str]]:
    """Retorna pares (alias, canonical) ordenados por tamanho do alias (desc)."""
    if not CARD_ALIASES_PATH.exists():
        return []
    with open(CARD_ALIASES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cards = data.get("cards", {}) or {}
    pairs: list[tuple[str, str]] = []
    for canonical, info in cards.items():
        aliases = info.get("aliases", []) if isinstance(info, dict) else []
        for alias in [canonical] + list(aliases):
            pairs.append((alias, canonical))
    pairs.sort(key=lambda p: len(normalize_text(p[0])), reverse=True)
    return pairs


@lru_cache(maxsize=1)
def _load_non_card_terms() -> frozenset[str]:
    if not NON_CARD_TERMS_PATH.exists():
        return frozenset()
    with open(NON_CARD_TERMS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    terms = data.get("non_card_terms", []) or []
    return frozenset(normalize_text(t) for t in terms)


@lru_cache(maxsize=1)
def _load_watchlist_cards() -> list[str]:
    if not DEFAULT_WATCHLIST.exists():
        return []
    with open(DEFAULT_WATCHLIST, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("cards", []) or [])


def _is_non_card_term(term: str) -> bool:
    norm = normalize_text(term)
    if norm in _load_non_card_terms():
        return True
    if norm in {normalize_text(c) for c in _load_watchlist_cards()}:
        return False
    return norm in _load_non_card_terms()


def _alias_matches_text(alias: str, text_norm: str) -> bool:
    alias_norm = normalize_text(alias)
    if not alias_norm:
        return False
    if len(alias_norm) <= 4 or alias_norm.isdigit():
        return bool(re.search(rf"\b{re.escape(alias_norm)}\b", text_norm))
    return alias_norm in text_norm


def _has_tcg_context_for_partial(text: str) -> bool:
    from src.tcg_knowledge import analyze_text

    signals = analyze_text(text)
    return bool(
        signals.has_tcg_context
        or signals.collection
        or signals.rarity
        or signals.grading
        or signals.has_buy_intent
        or signals.has_sell_intent
        or signals.language
        or signals.condition
    )


def _add_candidate(
    candidates: list[CardCandidate],
    seen: set[str],
    canonical: str,
    alias: str,
    confidence: int,
    reason: str,
) -> None:
    key = normalize_text(canonical)
    if key in seen:
        return
    if _is_non_card_term(canonical):
        return
    seen.add(key)
    candidates.append(CardCandidate(canonical, alias, confidence, reason))


def detect_card_candidates(
    text: str,
    card_hint: str = "",
    known_cards: list[str] | None = None,
) -> list[CardCandidate]:
    """Retorna candidatos a carta ordenados por confidence (desc)."""
    text_norm = normalize_text(text)
    candidates: list[CardCandidate] = []
    seen: set[str] = set()

    if card_hint.strip():
        hint = card_hint.strip()
        hint_norm = normalize_text(hint)
        matched_alias = hint
        for alias, canonical in _load_card_alias_map():
            if normalize_text(canonical) == hint_norm or normalize_text(alias) == hint_norm:
                matched_alias = alias
                hint = canonical
                break
        if _alias_matches_text(matched_alias, text_norm) or _alias_matches_text(hint, text_norm):
            _add_candidate(
                candidates, seen, hint, matched_alias, 98,
                "hint --card validado no texto",
            )
        else:
            _add_candidate(
                candidates, seen, hint, matched_alias, 75,
                "hint --card (não encontrado literalmente no texto)",
            )

    for alias, canonical in _load_card_alias_map():
        if _alias_matches_text(alias, text_norm):
            conf = 95 if normalize_text(alias) == normalize_text(canonical) else 93
            _add_candidate(
                candidates, seen, canonical, alias, conf,
                "alias exato em card_aliases.yml",
            )

    watchlist = known_cards if known_cards is not None else _load_watchlist_cards()
    for card in watchlist:
        if _alias_matches_text(card, text_norm):
            _add_candidate(
                candidates, seen, card, card, 90,
                "nome exato na watchlist",
            )

    for alias, canonical in _load_card_alias_map():
        if canonical in seen:
            continue
        alias_norm = normalize_text(alias)
        canon_norm = normalize_text(canonical)
        if len(alias_norm) < len(canon_norm) + 2:
            continue
        if alias_norm in text_norm and _has_tcg_context_for_partial(text):
            _add_candidate(
                candidates, seen, canonical, alias, 85,
                "alias com contexto TCG/coleção/intenção",
            )

    if _has_tcg_context_for_partial(text):
        for alias, canonical in _load_card_alias_map():
            if canonical in seen:
                continue
            canon_norm = normalize_text(canonical)
            words = [w for w in canon_norm.split() if len(w) > 2]
            if words and all(w in text_norm for w in words):
                _add_candidate(
                    candidates, seen, canonical, alias, 70,
                    "match parcial com contexto TCG forte",
                )

    capitalized = re.findall(
        r"\b[A-ZÀ-ÿ][a-zà-ÿ]+(?:\s+[A-ZÀ-ÿ][a-zà-ÿ]+)*(?:\s+(?:ex|EX|V|VMAX|VSTAR|GX))?\b",
        text,
    )
    for phrase in capitalized:
        if _is_non_card_term(phrase):
            continue
        if any(normalize_text(phrase) == normalize_text(c.matched_alias) for c in candidates):
            continue
        if len(normalize_text(phrase)) < 3:
            continue
        _add_candidate(
            candidates, seen, phrase.strip(), phrase.strip(), 45,
            "fallback termo capitalizado (baixa confiança)",
        )

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


def detect_card_in_text(
    text: str,
    known_cards: list[str] | None = None,
    card_hint: str = "",
) -> str:
    """Detecta a carta com maior confidence no texto."""
    result = detect_card_match(text, known_cards=known_cards, card_hint=card_hint)
    return result.card


def detect_card_match(
    text: str,
    known_cards: list[str] | None = None,
    card_hint: str = "",
) -> CardDetectionResult:
    """Detecta carta e retorna metadados completos."""
    candidates = detect_card_candidates(text, card_hint=card_hint, known_cards=known_cards)
    if not candidates:
        return CardDetectionResult(candidates=[])
    best = candidates[0]
    if best.confidence < MIN_CONFIDENCE:
        return CardDetectionResult(candidates=candidates)
    return CardDetectionResult(
        card=best.canonical_name,
        alias=best.matched_alias,
        confidence=best.confidence,
        reason=best.reason,
        candidates=candidates,
    )
