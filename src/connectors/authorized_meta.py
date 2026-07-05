"""Placeholders — Meta autorizada (Instagram/Facebook próprios)."""

from __future__ import annotations

from src.opportunity_models import Opportunity


class AuthorizedInstagramConnector:
    """
    Placeholder — apenas conta Instagram profissional própria via Meta API.

    Não rastreia perfis de terceiros, DMs ou grupos.
  """

    SOURCE = "instagram_pro"

    def is_available(self) -> bool:
        return False

    def scan_cards(self, cards: list[str], limit: int = 10) -> list[Opportunity]:
        return []


class AuthorizedFacebookPageConnector:
    """
    Placeholder — apenas Facebook Page própria via Graph API autorizada.
  """

    SOURCE = "facebook_page"

    def is_available(self) -> bool:
        return False

    def scan_cards(self, cards: list[str], limit: int = 10) -> list[Opportunity]:
        return []
