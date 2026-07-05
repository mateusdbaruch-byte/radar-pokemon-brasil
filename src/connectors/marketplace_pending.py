"""Placeholders — marketplaces sem acesso autorizado no MVP."""

from __future__ import annotations

from src.opportunity_models import Opportunity


class PendingAccessMarketplaceConnector:
    """Base para marketplaces com PENDING_ACCESS."""

    def __init__(self, source: str, platform: str):
        self.source = source
        self.platform = platform

    def is_available(self) -> bool:
        return False

    def scan_cards(self, cards: list[str], limit: int = 10) -> list[Opportunity]:
        return []


def get_pending_marketplace(source: str) -> PendingAccessMarketplaceConnector:
    labels = {
        "olx": "olx",
        "shopee": "shopee",
        "bigdex": "bigdex",
        "liga_pokemon": "liga_pokemon",
        "myp_cards": "myp_cards",
    }
    return PendingAccessMarketplaceConnector(source, labels.get(source, source))
