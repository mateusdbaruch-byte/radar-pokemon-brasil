"""
Placeholder para integração futura com Discord.

IMPORTANTE — Conformidade:
- NÃO automatizar scraping de servidores privados.
- Integração futura deve usar:
  1. Bot autorizado com permissões explícitas do administrador do servidor, OU
  2. Importação manual de exportações (JSON/CSV) fornecidas pelo usuário.

Este módulo define a interface para quando a integração for implementada.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.models import DataMode, RadarResult
from src.normalizer import normalize_card_name
from src.scoring import apply_scoring_to_result

logger = logging.getLogger(__name__)


class DiscordPlaceholderConnector:
    """
    Conector placeholder para Discord.

    Métodos disponíveis:
    - import_from_json(): importa mensagens exportadas manualmente
    - search_cards(): retorna vazio (não implementado)
    """

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def is_available(self) -> bool:
        return False

    def search_card(self, card_name: str, limit: int = 10) -> list[RadarResult]:
        """Não implementado — retorna lista vazia."""
        logger.info(
            "Discord: conector não implementado. "
            "Use import_from_json() para dados manuais."
        )
        return []

    def search_cards(
        self,
        cards: list[str],
        limit_per_card: int = 10,
    ) -> list[RadarResult]:
        return []

    def import_from_json(
        self,
        file_path: Path | str,
        card_name: str,
    ) -> list[RadarResult]:
        """
        Importa mensagens de um arquivo JSON exportado manualmente.

        Formato esperado:
        [
          {
            "content": "Procuro Charizard VMAX",
            "author": "usuario#1234",
            "timestamp": "2024-01-15T10:00:00Z",
            "url": "https://discord.com/channels/..."
          }
        ]
        """
        path = Path(file_path)
        if not path.exists():
            logger.error("Arquivo não encontrado: %s", path)
            return []

        with open(path, encoding="utf-8") as f:
            messages: list[dict[str, Any]] = json.load(f)

        results: list[RadarResult] = []
        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue
            intent_type, intent_score = apply_scoring_to_result(content)
            result = RadarResult(
                source="discord",
                platform="discord",
                card_name_detected=card_name,
                normalized_card_name=normalize_card_name(card_name),
                title=content[:100],
                text_snippet=content[:1000],
                url=msg.get("url", ""),
                author_or_seller=msg.get("author", ""),
                intent_type=intent_type,
                intent_score=intent_score,
                data_mode=DataMode.MANUAL_IMPORT,
            )
            result.set_raw_data(msg)
            results.append(result)

        return results
