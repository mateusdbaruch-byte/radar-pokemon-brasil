"""Conector Mercado Livre — API pública de busca (sem chave obrigatória)."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from src.models import DataMode, RadarResult, tag_results
from src.normalizer import normalize_card_name
from src.scoring import apply_scoring_to_result

logger = logging.getLogger(__name__)

# API pública do Mercado Livre Brasil
ML_SEARCH_URL = "https://api.mercadolibre.com/sites/{site_id}/search"


@dataclass
class MLDiagnosticResult:
    """Resultado de diagnóstico da API do Mercado Livre (não persiste dados)."""

    url: str
    status_code: int | None
    response_preview: str
    is_valid_json: bool
    json_top_level_keys: list[str] | None
    results_count: int | None
    error_message: str | None
    suggestions: list[str]
    is_forbidden: bool = False


def _response_is_forbidden(status_code: int | None, data: dict | None, preview: str) -> bool:
    """Detecta resposta forbidden da API (não deve ser tratada como dado real)."""
    if status_code == 403:
        return True
    if data and isinstance(data, dict):
        if data.get("message") == "forbidden" or data.get("error") == "forbidden":
            return True
    return "forbidden" in preview.lower() and '"message"' in preview.lower()


def diagnose_search(
    query: str,
    site_id: str = "MLB",
    limit: int = 5,
) -> MLDiagnosticResult:
    """
    Executa uma requisição de teste à API de busca do Mercado Livre.

    Não salva dados — apenas inspeciona URL, status e corpo da resposta.
    """
    connector = MercadoLivreConnector(site_id=site_id)
    base_url = ML_SEARCH_URL.format(site_id=site_id)
    params: dict[str, Any] = {"q": query, "limit": min(limit, 50)}

    prepared = connector.session.prepare_request(
        requests.Request("GET", base_url, params=params)
    )
    full_url = prepared.url or base_url

    try:
        response = connector.session.send(prepared, timeout=15)
        preview = response.text[:500]
        is_valid_json = False
        json_keys: list[str] | None = None
        results_count: int | None = None

        try:
            data = response.json()
            is_valid_json = True
            if isinstance(data, dict):
                json_keys = list(data.keys())
                results = data.get("results")
                if isinstance(results, list):
                    results_count = len(results)
        except (json.JSONDecodeError, ValueError):
            is_valid_json = False
            data = None

        forbidden = _response_is_forbidden(response.status_code, data if is_valid_json else None, preview)
        suggestions = _build_suggestions(
            status_code=response.status_code,
            is_valid_json=is_valid_json,
            error_message=None,
            is_forbidden=forbidden,
        )

        return MLDiagnosticResult(
            url=full_url,
            status_code=response.status_code,
            response_preview=preview,
            is_valid_json=is_valid_json,
            json_top_level_keys=json_keys,
            results_count=results_count,
            error_message=None,
            suggestions=suggestions,
            is_forbidden=forbidden,
        )
    except requests.RequestException as exc:
        suggestions = _build_suggestions(
            status_code=None,
            is_valid_json=False,
            error_message=str(exc),
            is_forbidden=False,
        )
        return MLDiagnosticResult(
            url=full_url,
            status_code=None,
            response_preview="",
            is_valid_json=False,
            json_top_level_keys=None,
            results_count=None,
            error_message=str(exc),
            suggestions=suggestions,
            is_forbidden=False,
        )


def _build_suggestions(
    status_code: int | None,
    is_valid_json: bool,
    error_message: str | None,
    is_forbidden: bool = False,
) -> list[str]:
    """Gera sugestões amigáveis com base no status HTTP e no corpo."""
    tips: list[str] = []

    if error_message:
        if "timeout" in error_message.lower():
            tips.append("Timeout de rede — verifique sua conexão com a internet.")
        elif "connection" in error_message.lower():
            tips.append("Falha de conexão — firewall, proxy ou DNS podem estar bloqueando.")
        else:
            tips.append(f"Erro de requisição: {error_message}")

    if status_code == 200 and is_valid_json:
        tips.append("API respondeu com JSON válido — o conector deve funcionar neste ambiente.")
        return tips

    if status_code == 403 or is_forbidden:
        tips.extend([
            "HTTP 403 / forbidden — acesso negado pela API do Mercado Livre.",
            "Não salve estes resultados como dados reais (data_mode deve permanecer unavailable).",
            "Teste em rede residencial; configure ML_ACCESS_TOKEN se tiver app oficial.",
        ])
    elif status_code == 429:
        tips.extend([
            "HTTP 429 — muitas requisições em pouco tempo.",
            "Aguarde alguns minutos e tente novamente.",
        ])
    elif status_code and status_code >= 500:
        tips.extend([
            f"HTTP {status_code} — instabilidade no servidor do Mercado Livre.",
            "Tente novamente mais tarde.",
        ])
    elif status_code == 200 and not is_valid_json:
        tips.append("HTTP 200, mas o corpo não é JSON — resposta inesperada ou página de bloqueio.")

    if not tips:
        tips.append("Verifique internet, query de busca e configuração em config/sources.yml.")

    return tips


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
        headers = {
            "User-Agent": "RadarPokemonBrasil/1.0 (+https://github.com; MVP educacional)",
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        token = os.getenv("ML_ACCESS_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.session.headers.update(headers)

    def _search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Busca anúncios no Mercado Livre via API oficial."""
        url = ML_SEARCH_URL.format(site_id=self.site_id)
        params: dict[str, Any] = {
            "q": query,
            "limit": min(limit, 50),
        }
        if self.category:
            params["category"] = self.category

        try:
            response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 429:
                logger.warning("Mercado Livre rate limit (429); aguardando 3s...")
                time.sleep(3)
                response = self.session.get(url, params=params, timeout=15)

            if response.status_code == 403:
                logger.warning(
                    "Mercado Livre 403 forbidden — resposta não será salva como dado real. "
                    "Teste em rede residencial."
                )
                return []

            if response.status_code != 200:
                logger.error("Mercado Livre HTTP %s — busca ignorada", response.status_code)
                return []

            data = response.json()
            if _response_is_forbidden(response.status_code, data, response.text[:200]):
                logger.warning("Mercado Livre retornou forbidden no JSON — ignorando resultados")
                return []

            return data.get("results", [])
        except requests.Timeout:
            logger.error("Mercado Livre: timeout de rede (15s)")
            return []
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
    if not result:
        return []
    return tag_results([result], DataMode.MOCK)
