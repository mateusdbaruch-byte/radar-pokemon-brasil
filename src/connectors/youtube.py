"""Conector YouTube — opcional, requer YOUTUBE_API_KEY."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

from src.models import RadarResult
from src.normalizer import build_search_query, normalize_card_name
from src.scoring import apply_scoring_to_result

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_COMMENTS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"


class YouTubeConnector:
    """
    Coleta comentários públicos de vídeos Pokémon via YouTube Data API v3.

    Requer chave de API (YOUTUBE_API_KEY no .env).
    Se não configurada, o conector retorna lista vazia com aviso.
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_comments_per_video: int = 20,
    ):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY", "")
        self.max_comments_per_video = max_comments_per_video
        self.enabled = bool(self.api_key)

    def is_available(self) -> bool:
        """Verifica se a API key está configurada."""
        return self.enabled

    def _search_videos(self, query: str, limit: int = 5) -> list[str]:
        """Busca IDs de vídeos relacionados à query."""
        if not self.enabled:
            return []
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": limit,
            "key": self.api_key,
            "relevanceLanguage": "pt",
        }
        try:
            response = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
            response.raise_for_status()
            items = response.json().get("items", [])
            return [
                item["id"]["videoId"]
                for item in items
                if item.get("id", {}).get("videoId")
            ]
        except requests.RequestException as exc:
            logger.error("Erro na busca YouTube: %s", exc)
            return []

    def _get_comments(self, video_id: str) -> list[dict[str, Any]]:
        """Obtém comentários de um vídeo."""
        if not self.enabled:
            return []
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": self.max_comments_per_video,
            "key": self.api_key,
            "textFormat": "plainText",
        }
        try:
            response = requests.get(YOUTUBE_COMMENTS_URL, params=params, timeout=15)
            response.raise_for_status()
            return response.json().get("items", [])
        except requests.RequestException as exc:
            logger.warning("Comentários indisponíveis para %s: %s", video_id, exc)
            return []

    def _comment_to_result(
        self,
        comment_item: dict[str, Any],
        card_name: str,
        video_id: str,
    ) -> RadarResult | None:
        """Converte comentário em RadarResult."""
        snippet = comment_item.get("snippet", {}).get("topLevelComment", {}).get(
            "snippet", {}
        )
        text = snippet.get("textDisplay", "")
        if not text:
            return None

        intent_type, intent_score = apply_scoring_to_result(text)
        published = snippet.get("publishedAt")
        published_at = None
        if published:
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))

        comment_id = comment_item.get("id", "")
        result = RadarResult(
            source="youtube",
            platform="youtube",
            card_name_detected=card_name,
            normalized_card_name=normalize_card_name(card_name),
            title=f"Comentário em vídeo {video_id}",
            text_snippet=text[:1000],
            url=f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}",
            author_or_seller=snippet.get("authorDisplayName", ""),
            published_at=published_at,
            intent_type=intent_type,
            intent_score=intent_score,
        )
        result.set_raw_data(comment_item)
        return result

    def search_card(self, card_name: str, limit: int = 10) -> list[RadarResult]:
        """Busca comentários em vídeos sobre uma carta."""
        if not self.enabled:
            logger.info(
                "YouTube desabilitado: configure YOUTUBE_API_KEY no .env"
            )
            return []

        query = build_search_query(card_name)
        video_ids = self._search_videos(query, limit=3)
        results: list[RadarResult] = []

        for video_id in video_ids:
            comments = self._get_comments(video_id)
            for comment in comments:
                result = self._comment_to_result(comment, card_name, video_id)
                if result:
                    results.append(result)
                if len(results) >= limit:
                    return results

        return results

    def search_cards(
        self,
        cards: list[str],
        limit_per_card: int = 10,
    ) -> list[RadarResult]:
        """Busca múltiplas cartas."""
        if not self.enabled:
            return []
        all_results: list[RadarResult] = []
        for card in cards:
            all_results.extend(self.search_card(card, limit=limit_per_card))
        return all_results
