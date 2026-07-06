"""Classificação de intenção de compra/venda e pontuação."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from src.models import IntentType


# Palavras-chave padrão (usadas se keywords.yml não existir)
DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "buy_intent_pt": [
        "procuro", "compro", "comprando", "alguém vende", "alguém tem",
        "onde acho", "buscando", "preciso", "quero comprar", "pago",
        "pagando", "aceito propostas",
    ],
    "sell_intent_pt": [
        "vendo", "à venda", "a venda", "disponível", "disponivel",
        "tenho", "faço", "faco", "anuncio", "anúncio", "lote", "desapego",
    ],
    "buy_intent_en": [
        "wtb", "looking for", "buying", "need", "searching for",
        "anyone selling", "paying", "iso",
    ],
    "price_reference": [
        "preço", "preco", "valor", "r$", "reais", "price", "sold for",
        "vendido por",
    ],
}

# Termos de compra explícita (score 90-100)
EXPLICIT_BUY_TERMS = {
    "compro", "procuro", "pago", "pagando", "wtb", "looking for",
    "buying", "quero comprar",
}

# Termos de compra provável (score 70-89)
PROBABLE_BUY_TERMS = {
    "alguém tem", "alguem tem", "onde acho", "buscando", "preciso",
    "need", "searching for", "anyone selling", "iso", "aceito propostas",
}

# Termos de venda explícita
EXPLICIT_SELL_TERMS = {
    "vendo", "à venda", "a venda", "disponível", "disponivel", "desapego",
}


def load_keywords(keywords_path: Path | None = None) -> dict[str, list[str]]:
    """Carrega palavras-chave do YAML ou usa padrões embutidos."""
    if keywords_path and keywords_path.exists():
        with open(keywords_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {k: [normalize_keyword(w) for w in v] for k, v in data.items()}
    return {
        k: [normalize_keyword(w) for w in v]
        for k, v in DEFAULT_KEYWORDS.items()
    }


def normalize_keyword(keyword: str) -> str:
    """Normaliza palavra-chave para comparação."""
    return keyword.lower().strip()


def _text_contains(text: str, keyword: str) -> bool:
    """Verifica se keyword aparece no texto (case-insensitive)."""
    text_lower = text.lower()
    # Termos curtos como "need" ou "iso" usam word boundary
    if len(keyword) <= 4:
        return bool(re.search(rf"\b{re.escape(keyword)}\b", text_lower))
    return keyword in text_lower


def _count_matches(text: str, keywords: list[str]) -> list[str]:
    """Retorna lista de keywords encontradas no texto."""
    return [kw for kw in keywords if _text_contains(text, kw)]


def classify_intent(
    text: str,
    keywords: dict[str, list[str]] | None = None,
    is_marketplace_listing: bool = False,
) -> tuple[IntentType, int]:
    """
    Classifica intenção e retorna (tipo, score 0-100).

    Anúncios de marketplace sem sinais de compra são PRICE_REFERENCE ou SELL_INTENT.
    """
    if keywords is None:
        keywords = load_keywords()

    text_lower = text.lower()

    buy_pt = _count_matches(text_lower, keywords.get("buy_intent_pt", []))
    buy_en = _count_matches(text_lower, keywords.get("buy_intent_en", []))
    sell_pt = _count_matches(text_lower, keywords.get("sell_intent_pt", []))
    price_kw = _count_matches(text_lower, keywords.get("price_reference", []))

    all_buy = buy_pt + buy_en
    all_sell = sell_pt

    # Compra explícita
    explicit_buy = [
        t for t in all_buy
        if any(e in t for e in EXPLICIT_BUY_TERMS) or t in EXPLICIT_BUY_TERMS
    ]
    if explicit_buy:
        return IntentType.BUY_INTENT, min(100, 90 + len(explicit_buy) * 3)

    # Compra provável
    probable_buy = [
        t for t in all_buy
        if any(p in t for p in PROBABLE_BUY_TERMS) or t in PROBABLE_BUY_TERMS
    ]
    if probable_buy or all_buy:
        base = 75 if probable_buy else 70
        return IntentType.BUY_INTENT, min(89, base + len(all_buy) * 2)

    # Venda explícita
    explicit_sell = [
        t for t in all_sell
        if any(e in t for e in EXPLICIT_SELL_TERMS) or t in EXPLICIT_SELL_TERMS
    ]
    if explicit_sell or (is_marketplace_listing and all_sell):
        score = 85 if explicit_sell else 75
        return IntentType.SELL_INTENT, min(100, score + len(all_sell) * 2)

    if is_marketplace_listing:
        # Anúncio de marketplace sem sinais claros = referência de preço
        return IntentType.PRICE_REFERENCE, 55

    if all_sell:
        return IntentType.SELL_INTENT, min(79, 65 + len(all_sell) * 3)

    if price_kw:
        return IntentType.PRICE_REFERENCE, min(69, 45 + len(price_kw) * 5)

    # Menção relevante sem intenção clara
    if len(text_lower.split()) >= 5:
        return IntentType.DISCUSSION, 35

    return IntentType.UNKNOWN, 15


def apply_scoring_to_result(
    text: str,
    is_marketplace_listing: bool = False,
    keywords_path: Path | None = None,
) -> tuple[IntentType, int]:
    """Atalho para classificar um texto com keywords do arquivo de config."""
    keywords = load_keywords(keywords_path)
    return classify_intent(text, keywords, is_marketplace_listing)


def extract_price_from_text(text: str) -> tuple[float | None, str]:
    """
    Tenta extrair preço do texto.

    Retorna (valor, moeda). Suporta R$ e USD básico.
    """
    # Padrão brasileiro: R$ 1.234,56 ou R$1234
    brl_match = re.search(
        r"R\$\s*([\d.]+(?:,\d{2})?)",
        text,
        re.IGNORECASE,
    )
    if brl_match:
        raw = brl_match.group(1).replace(".", "").replace(",", ".")
        try:
            return float(raw), "BRL"
        except ValueError:
            pass

    # Padrão USD: $50 or USD 50
    usd_match = re.search(
        r"(?:USD|\$)\s*([\d,]+(?:\.\d{2})?)",
        text,
        re.IGNORECASE,
    )
    if usd_match:
        raw = usd_match.group(1).replace(",", "")
        try:
            return float(raw), "USD"
        except ValueError:
            pass

    return None, "BRL"
