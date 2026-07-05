"""Conector Mercado Livre — API pública de busca (sem chave obrigatória)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src.models import RadarResult
from src.normalizer import normalize_card_name
from src.scoring import apply_scoring_to_result

logger = logging.getLogger(__name__)

# API pública do Mercado Livre Brasil
ML_SEARCH_URL = "https://api.mercadolibre.com/sites/{site_id}/search"


class MercadoLivreConnector:
    """
    Coleta anúncios públicos do Mercado Livre via API oficial.

    Documentação: https://developers.mercadolivre.com.br/pt_br/itens-e-buscas
    Não requer autenticação para buscas públicas.
    """

    def __init__(
        self,
        site_id: str = "MLB",
        category: str = "",
        request_delay: float = 0.5,
    ):
        self.site_id = site_id
        self.category = category
        self.request_delay = request_delay
        self.session = requests.Session()
        # User-Agent descritivo ajuda a evitar bloqueios em alguns ambientes
        self.session.headers.update({
            "User-Agent": "RadarPokemonBrasil/1.0 (MVP; educational)",
            "Accept": "application/json",
        })

    def _search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Busca anúncios no Mercado Livre."""
        url = ML_SEARCH_URL.format(site_id=self.site_id)
        params: dict[str, Any] = {
            "q": query,
            "limit": min(limit, 50),
        }
        if self.category:
            params["category"] = self.category

        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])
        except requests.RequestException as exc:
            logger.error("Erro na busca Mercado Livre: %s", exc)
            return []

    def _item_to_result(
        self,
        item: dict[str, Any],
        card_name: str,
    ) -> RadarResult | None:
        """Converte um anúncio ML em RadarResult."""
        title = item.get("title", "")
        if not title:
            return None

        # Anúncios ML são listagens de venda por padrão
        condition = item.get("condition", "")
        combined = f"{title} {condition}"
        intent_type, intent_score = apply_scoring_to_result(
            combined, is_marketplace_listing=True
        )

        price = item.get("price")
        currency = item.get("currency_id", "BRL")

        location_parts = []
        if item.get("address", {}).get("city_name"):
            location_parts.append(item["address"]["city_name"])
        if item.get("address", {}).get("state_name"):
            location_parts.append(item["address"]["state_name"])
        location = ", ".join(location_parts)

        seller = item.get("seller", {})
        seller_nickname = seller.get("nickname", "") if isinstance(seller, dict) else ""

        result = RadarResult(
            source="mercado_livre",
            platform="mercado_livre",
            card_name_detected=card_name,
            normalized_card_name=normalize_card_name(card_name),
            title=title[:500],
            text_snippet=title[:1000],
            url=item.get("permalink", ""),
            author_or_seller=seller_nickname,
            published_at=None,  # ML não expõe data de publicação na busca
            intent_type=intent_type,
            intent_score=intent_score,
            price=float(price) if price is not None else None,
            currency=currency,
            location=location,
        )
        result.set_raw_data(item)
        return result

    def search_card(self, card_name: str, limit: int = 20) -> list[RadarResult]:
        """Busca anúncios de uma carta Pokémon."""
        query = f"cartão pokemon {card_name} tcg"
        items = self._search(query, limit=limit)
        results = []
        for item in items:
            result = self._item_to_result(item, card_name)
            if result:
                results.append(result)
        return results

    def search_cards(
        self,
        cards: list[str],
        limit_per_card: int = 20,
    ) -> list[RadarResult]:
        """Busca múltiplas cartas."""
        all_results: list[RadarResult] = []
        for card in cards:
            logger.info("Mercado Livre: buscando %s...", card)
            card_results = self.search_card(card, limit=limit_per_card)
            all_results.extend(card_results)
            time.sleep(self.request_delay)
        return all_results


def get_mock_results(card_name: str) -> list[RadarResult]:
    """Resultados simulados para testes offline."""
    mock_item = {
        "title": f"Cartão Pokémon {card_name} TCG Original - À Venda",
        "price": 149.90,
        "currency_id": "BRL",
        "permalink": f"https://produto.mercadolivre.com.br/mock-{card_name.lower()}",
        "condition": "new",
        "seller": {"nickname": "vendedor_mock"},
        "address": {"city_name": "São Paulo", "state_name": "SP"},
    }
    connector = MercadoLivreConnector()
    result = connector._item_to_result(mock_item, card_name)
    return [result] if result else []
