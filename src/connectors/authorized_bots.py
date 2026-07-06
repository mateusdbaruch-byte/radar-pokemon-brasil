"""Placeholders — bots autorizados (Discord, Telegram)."""

from __future__ import annotations

from src.opportunity_models import Opportunity


class AuthorizedDiscordBotConnector:
    """
    Placeholder para bot Discord em canais autorizados.

    O bot só lê canais onde foi adicionado com permissão explícita.
  """

    SOURCE = "discord_bot"

    def is_available(self) -> bool:
        return False

    def scan_cards(self, cards: list[str], limit: int = 10) -> list[Opportunity]:
        return []


class AuthorizedTelegramBotConnector:
    """
    Placeholder para bot Telegram em grupos/canais com opt-in.
  """

    SOURCE = "telegram_bot"

    def is_available(self) -> bool:
        return False

    def scan_cards(self, cards: list[str], limit: int = 10) -> list[Opportunity]:
        return []
