"""Normalização de nomes de cartas Pokémon."""

from __future__ import annotations

import re
import unicodedata


# Mapeamento de variações comuns para nome canônico
CARD_ALIASES: dict[str, str] = {
    "charizard": "Charizard",
    "charmander evolução": "Charizard",
    "umbreon": "Umbreon",
    "pikachu": "Pikachu",
    "mew": "Mew",
    "gengar": "Gengar",
    "lugia": "Lugia",
    "rayquaza": "Rayquaza",
    "giratina": "Giratina",
    "greninja": "Greninja",
    "eevee": "Eevee",
    "evoli": "Eevee",
}


def strip_accents(text: str) -> str:
    """Remove acentos para comparação flexível."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_text(text: str) -> str:
    """Normaliza texto para busca e comparação."""
    text = strip_accents(text.lower().strip())
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_card_name(card_name: str) -> str:
    """
    Retorna o nome canônico da carta.

    Usa aliases conhecidos; caso contrário, capitaliza a primeira letra.
    """
    key = normalize_text(card_name)
    if key in CARD_ALIASES:
        return CARD_ALIASES[key]
    # Capitaliza cada palavra para nomes compostos
    return " ".join(word.capitalize() for word in card_name.split())


def detect_card_in_text(text: str, known_cards: list[str]) -> str | None:
    """
    Detecta qual carta da lista aparece no texto.

    Retorna o nome canônico ou None se nenhuma carta for encontrada.
    """
    from src.card_detection import detect_card_in_text as detect

    result = detect(text, known_cards=known_cards)
    return result or None


def build_search_query(card_name: str, suffix: str = "") -> str:
    """Monta query de busca combinando carta e sufixo opcional."""
    parts = [card_name, "pokemon", "tcg"]
    if suffix:
        parts.append(suffix)
    return " ".join(parts)
