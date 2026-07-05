"""Carregamento da watchlist com prioridades de cartas."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.paths import DEFAULT_WATCHLIST

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
DEFAULT_PRIORITY = "medium"


def _parse_cards_section(cards_raw: list | dict) -> list[tuple[str, str]]:
    if isinstance(cards_raw, list):
        return [(str(name).strip(), DEFAULT_PRIORITY) for name in cards_raw if str(name).strip()]
    if isinstance(cards_raw, dict):
        items: list[tuple[str, str]] = []
        for name, cfg in cards_raw.items():
            priority = DEFAULT_PRIORITY
            if isinstance(cfg, dict):
                priority = str(cfg.get("priority", DEFAULT_PRIORITY)).lower()
            items.append((str(name).strip(), priority))
        return items
    return []


def load_watchlist_entries(path: Path | str = DEFAULT_WATCHLIST) -> list[tuple[str, str]]:
    """Retorna [(carta, prioridade), ...] ordenado por prioridade."""
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries = _parse_cards_section(data.get("cards", []))
    entries.sort(key=lambda item: PRIORITY_ORDER.get(item[1], 99))
    return entries


def load_watchlist_cards(path: Path | str = DEFAULT_WATCHLIST) -> list[str]:
    return [name for name, _ in load_watchlist_entries(path)]


def filter_cards_for_economy(
    cards: list[str],
    priorities: dict[str, str] | None = None,
    *,
    include_medium: bool = True,
) -> list[str]:
    """Modo economy: prioriza high; inclui medium; exclui low."""
    if not priorities:
        return cards
    filtered: list[str] = []
    for card in cards:
        prio = priorities.get(card, DEFAULT_PRIORITY)
        if prio == "high":
            filtered.append(card)
        elif include_medium and prio == "medium":
            filtered.append(card)
    return filtered or [c for c in cards if priorities.get(c, DEFAULT_PRIORITY) != "low"][:3]


def priorities_from_watchlist(path: Path | str = DEFAULT_WATCHLIST) -> dict[str, str]:
    return dict(load_watchlist_entries(path))
