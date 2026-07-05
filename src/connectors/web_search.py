"""Conector de busca web — APIs oficiais (Bing, Google, SerpAPI)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

from src.opportunity_scoring import score_opportunity
from src.opportunity_models import Opportunity

logger = logging.getLogger(__name__)

SEARCH_QUERY_TEMPLATES = [
    'procuro {card} "Pokémon TCG"',
    'compro {card} "Pokémon TCG"',
    '"alguém vende" {card} "Pokémon TCG"',
    '"desapego" {card} "Pokémon TCG"',
    '"abaixo da Liga" {card} "Pokémon TCG"',
    'pago {card} Pokémon',
    '"quero comprar" {card} "Pokémon TCG"',
]


@dataclass
class WebSearchHit:
    title: str
    snippet: str
    url: str


class WebSearchConnector:
    """
    Busca pública na web via API oficial configurável.

    Provedores: bing, google, serpapi (WEB_SEARCH_PROVIDER no .env).
    Não faz scraping de Google diretamente.
    """

    def __init__(self) -> None:
        self.provider = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "RadarPokemonBrasil/0.2 (Opportunity Radar; educational)",
        })

    def is_configured(self) -> bool:
        if self.provider == "bing":
            return bool(os.getenv("BING_SEARCH_API_KEY", "").strip())
        if self.provider == "google":
            return bool(
                os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
                and os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()
            )
        if self.provider == "serpapi":
            return bool(os.getenv("SERPAPI_KEY", "").strip())
        return False

    def _search_bing(self, query: str, limit: int) -> list[WebSearchHit]:
        key = os.getenv("BING_SEARCH_API_KEY", "").strip()
        resp = self.session.get(
            "https://api.bing.microsoft.com/v7.0/search",
            params={"q": query, "count": min(limit, 50), "mkt": "pt-BR"},
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Bing Search HTTP %s", resp.status_code)
            return []
        data = resp.json()
        hits: list[WebSearchHit] = []
        for item in data.get("webPages", {}).get("value", []):
            hits.append(WebSearchHit(
                title=item.get("name", ""),
                snippet=item.get("snippet", ""),
                url=item.get("url", ""),
            ))
        return hits

    def _search_google(self, query: str, limit: int) -> list[WebSearchHit]:
        resp = self.session.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": os.getenv("GOOGLE_SEARCH_API_KEY", "").strip(),
                "cx": os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip(),
                "q": query,
                "num": min(limit, 10),
                "lr": "lang_pt",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Google Search HTTP %s", resp.status_code)
            return []
        hits: list[WebSearchHit] = []
        for item in resp.json().get("items", []):
            hits.append(WebSearchHit(
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                url=item.get("link", ""),
            ))
        return hits

    def _search_serpapi(self, query: str, limit: int) -> list[WebSearchHit]:
        resp = self.session.get(
            "https://serpapi.com/search",
            params={
                "api_key": os.getenv("SERPAPI_KEY", "").strip(),
                "q": query,
                "engine": "google",
                "hl": "pt-br",
                "gl": "br",
                "num": min(limit, 20),
            },
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning("SerpAPI HTTP %s", resp.status_code)
            return []
        hits: list[WebSearchHit] = []
        for item in resp.json().get("organic_results", []):
            hits.append(WebSearchHit(
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                url=item.get("link", ""),
            ))
        return hits

    def search_query(self, query: str, limit: int = 10) -> list[WebSearchHit]:
        if not self.is_configured():
            return []
        if self.provider == "bing":
            return self._search_bing(query, limit)
        if self.provider == "google":
            return self._search_google(query, limit)
        if self.provider == "serpapi":
            return self._search_serpapi(query, limit)
        logger.error("WEB_SEARCH_PROVIDER inválido: %s", self.provider)
        return []

    def scan_cards(
        self,
        cards: list[str],
        limit_per_query: int = 5,
    ) -> list[Opportunity]:
        """Busca oportunidades para cada carta usando templates de intenção."""
        if not self.is_configured():
            return []

        opportunities: list[Opportunity] = []
        seen_urls: set[str] = set()

        for card in cards:
            for template in SEARCH_QUERY_TEMPLATES:
                query = template.format(card=card)
                hits = self.search_query(query, limit=limit_per_query)
                for hit in hits:
                    if hit.url in seen_urls:
                        continue
                    seen_urls.add(hit.url)
                    evidence = f"{hit.title} {hit.snippet}".strip()
                    opp = score_opportunity(
                        evidence=evidence,
                        card_name=card,
                        source="web_search",
                        platform=self.provider,
                        url=hit.url,
                        urgency_hint=55,
                    )
                    opp.set_raw_data({"query": query, "hit": hit.__dict__})
                    opportunities.append(opp)

        return opportunities
