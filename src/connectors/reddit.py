"""Conector Reddit — usa endpoint JSON público (sem login)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src.models import DataMode, RadarResult, tag_results
from src.normalizer import build_search_query, normalize_card_name
from src.scoring import apply_scoring_to_result, extract_price_from_text

logger = logging.getLogger(__name__)

# Endpoint público do Reddit (leitura sem OAuth)
REDDIT_SEARCH_URL = "https://www.reddit.com/search.json"
DEFAULT_USER_AGENT = "RadarPokemonBrasil/1.0 (MVP; educational)"


class RedditConnector:
    """
    Coleta posts públicos do Reddit via API JSON.

    Não requer autenticação para buscas limitadas.
    Respeita rate limits com pausa entre requisições.
  """

    def __init__(
        self,
        user_agent: str | None = None,
        subreddits: list[str] | None = None,
        query_suffix: str = "pokemon card",
        request_delay: float = 1.5,
    ):
        self.user_agent = user_agent or os.getenv(
            "REDDIT_USER_AGENT", DEFAULT_USER_AGENT
        )
        self.subreddits = subreddits or ["PokemonTCG", "pkmntcg"]
        self.query_suffix = query_suffix
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def _search(
        self,
        query: str,
        limit: int = 10,
        subreddit: str | None = None,
    ) -> list[dict[str, Any]]:
        """Executa busca no Reddit e retorna lista de posts."""
        params: dict[str, Any] = {
            "q": query,
            "limit": min(limit, 25),
            "sort": "new",
            "restrict_sr": "on" if subreddit else "off",
            "type": "link",
        }
        url = REDDIT_SEARCH_URL
        if subreddit:
            url = f"https://www.reddit.com/r/{subreddit}/search.json"

        try:
            response = self.session.get(url, params=params, timeout=15)
            if response.status_code == 429:
                logger.warning("Reddit rate limit atingido; aguardando...")
                time.sleep(5)
                response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            children = data.get("data", {}).get("children", [])
            return [c.get("data", {}) for c in children if c.get("data")]
        except requests.RequestException as exc:
            logger.error("Erro na busca Reddit: %s", exc)
            return []

    def _post_to_result(
        self,
        post: dict[str, Any],
        card_name: str,
    ) -> RadarResult | None:
        """Converte um post Reddit em RadarResult."""
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        combined = f"{title} {selftext}".strip()
        if not combined:
            return None

        intent_type, intent_score = apply_scoring_to_result(combined)
        price, currency = extract_price_from_text(combined)

        created_utc = post.get("created_utc")
        published_at = None
        if created_utc:
            published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)

        permalink = post.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else post.get("url", "")

        result = RadarResult(
            source="reddit",
            platform="reddit",
            card_name_detected=card_name,
            normalized_card_name=normalize_card_name(card_name),
            title=title[:500],
            text_snippet=combined[:1000],
            url=url,
            author_or_seller=post.get("author", ""),
            published_at=published_at,
            intent_type=intent_type,
            intent_score=intent_score,
            price=price,
            currency=currency,
            location=post.get("subreddit_name_prefixed", ""),
        )
        result.set_raw_data(post)
        return result

    def search_card(self, card_name: str, limit: int = 10) -> list[RadarResult]:
        """Busca menções de uma carta em subreddits configurados."""
        query = build_search_query(card_name, self.query_suffix)
        results: list[RadarResult] = []
        seen_urls: set[str] = set()

        for subreddit in self.subreddits:
            posts = self._search(query, limit=limit, subreddit=subreddit)
            for post in posts:
                url = post.get("permalink", post.get("url", ""))
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                result = self._post_to_result(post, card_name)
                if result:
                    results.append(result)
            time.sleep(self.request_delay)

        # Busca global se poucos resultados
        if len(results) < limit // 2:
            posts = self._search(query, limit=limit)
            for post in posts:
                url = post.get("permalink", post.get("url", ""))
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                result = self._post_to_result(post, card_name)
                if result:
                    results.append(result)

        return results[:limit]

    def search_cards(
        self,
        cards: list[str],
        limit_per_card: int = 10,
    ) -> list[RadarResult]:
        """Busca múltiplas cartas com pausa entre cada uma."""
        all_results: list[RadarResult] = []
        for card in cards:
            logger.info("Reddit: buscando %s...", card)
            card_results = self.search_card(card, limit=limit_per_card)
            all_results.extend(card_results)
            time.sleep(self.request_delay)
        return all_results


def get_mock_results(card_name: str) -> list[RadarResult]:
    """
    Retorna resultados simulados para testes quando a API está indisponível.

    Útil em ambientes CI ou quando o Reddit bloqueia requisições.
    """
    mock_posts = [
        {
            "title": f"WTB {card_name} VMAX - paying well",
            "selftext": "Looking for mint condition, anyone selling?",
            "author": "mock_buyer",
            "subreddit_name_prefixed": "r/PokemonTCG",
            "permalink": f"/r/PokemonTCG/comments/mock1/wtb_{card_name.lower()}",
            "created_utc": time.time(),
        },
        {
            "title": f"Discussion about {card_name} meta",
            "selftext": "What do you think about this card in the current format?",
            "author": "mock_user",
            "subreddit_name_prefixed": "r/pkmntcg",
            "permalink": f"/r/pkmntcg/comments/mock2/discuss_{card_name.lower()}",
            "created_utc": time.time() - 3600,
        },
    ]
    connector = RedditConnector()
    results = [
        r
        for post in mock_posts
        if (r := connector._post_to_result(post, card_name))
    ]
    return tag_results(results, DataMode.MOCK)
