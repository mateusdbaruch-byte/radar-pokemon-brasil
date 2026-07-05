"""Conector Reddit — OAuth oficial ou endpoint JSON público."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from src.models import DataMode, RadarResult, tag_results
from src.normalizer import build_search_query, normalize_card_name
from src.reddit_auth import (
    RedditAuthResult,
    RedditAuthStatus,
    apply_reddit_auth,
    authenticate_reddit,
    credential_requirements_met,
    get_user_agent,
)
from src.reddit_policy import (
    REDDIT_PENDING_MESSAGE,
    is_reddit_policy_block,
    persist_reddit_gated,
)

logger = logging.getLogger(__name__)

REDDIT_SEARCH_URL = "https://www.reddit.com/search.json"
DEFAULT_USER_AGENT = "RadarPokemonBrasil/1.0 (MVP; educational)"


@dataclass
class RedditDiagnosticResult:
    """Resultado de diagnóstico do Reddit (não persiste dados)."""

    method: str
    url: str
    user_agent: str
    status_code: int | None
    response_preview: str
    is_valid_json: bool
    posts_count: int | None
    needs_oauth: bool
    oauth_message: str
    auth_mode: str
    auth_status: str
    error_message: str | None
    suggestions: list[str]


@dataclass
class RedditSearchResult:
    """Resultado de busca Reddit com metadados de autenticação."""

    posts: list[dict[str, Any]]
    auth_result: RedditAuthResult
    status_code: int | None
    error_message: str | None = None


def diagnose_search(
    query: str,
    subreddit: str | None = None,
    limit: int = 5,
    user_agent: str | None = None,
) -> RedditDiagnosticResult:
    """Executa requisição de teste ao Reddit."""
    ua = user_agent or get_user_agent()
    session = requests.Session()
    auth_result = apply_reddit_auth(session)

    params: dict[str, Any] = {
        "q": query,
        "limit": min(limit, 25),
        "sort": "new",
        "restrict_sr": "on" if subreddit else "off",
        "type": "link",
    }
    base_url = REDDIT_SEARCH_URL
    if subreddit:
        base_url = f"https://www.reddit.com/r/{subreddit}/search.json"

    prepared = session.prepare_request(requests.Request("GET", base_url, params=params))
    full_url = prepared.url or base_url
    method = prepared.method or "GET"

    try:
        response = session.send(prepared, timeout=15)
        preview = response.text[:500]
        is_valid_json = False
        posts_count: int | None = None

        try:
            data = response.json()
            is_valid_json = True
            if isinstance(data, dict):
                children = data.get("data", {}).get("children", [])
                if isinstance(children, list):
                    posts_count = len(children)
        except (json.JSONDecodeError, ValueError):
            is_valid_json = False

        auth_status = auth_result.status.value
        if is_reddit_policy_block(response.status_code, preview):
            auth_status = RedditAuthStatus.PENDING_APPROVAL.value

        needs_oauth, oauth_message = _assess_oauth_need(
            status_code=response.status_code,
            is_valid_json=is_valid_json,
            response_preview=preview,
            posts_count=posts_count,
            user_agent=ua,
            auth_result=auth_result,
        )
        suggestions = _build_reddit_suggestions(
            status_code=response.status_code,
            is_valid_json=is_valid_json,
            needs_oauth=needs_oauth,
            error_message=None,
            auth_result=auth_result,
        )

        return RedditDiagnosticResult(
            method=method,
            url=full_url,
            user_agent=ua,
            status_code=response.status_code,
            response_preview=preview,
            is_valid_json=is_valid_json,
            posts_count=posts_count,
            needs_oauth=needs_oauth,
            oauth_message=oauth_message,
            auth_mode=auth_result.auth_mode,
            auth_status=auth_status,
            error_message=None,
            suggestions=suggestions,
        )
    except requests.RequestException as exc:
        needs_oauth, oauth_message = _assess_oauth_need(
            status_code=None,
            is_valid_json=False,
            response_preview="",
            posts_count=None,
            user_agent=ua,
            auth_result=auth_result,
        )
        suggestions = _build_reddit_suggestions(
            status_code=None,
            is_valid_json=False,
            needs_oauth=needs_oauth,
            error_message=str(exc),
            auth_result=auth_result,
        )
        return RedditDiagnosticResult(
            method=method,
            url=full_url,
            user_agent=ua,
            status_code=None,
            response_preview="",
            is_valid_json=False,
            posts_count=None,
            needs_oauth=needs_oauth,
            oauth_message=oauth_message,
            auth_mode=auth_result.auth_mode,
            auth_status=auth_result.status.value,
            error_message=str(exc),
            suggestions=suggestions,
        )


def test_reddit_auth_and_search(query: str = "pokemon tcg brasil", limit: int = 5) -> RedditSearchResult:
    """
    Testa autenticação e faz busca simples.

    Não salva em radar_results.
    """
    session = requests.Session()
    auth_result = authenticate_reddit(session)

    if auth_result.status in (
        RedditAuthStatus.MISSING_CREDENTIALS,
        RedditAuthStatus.AUTH_FAILED,
    ):
        return RedditSearchResult(
            posts=[],
            auth_result=auth_result,
            status_code=auth_result.http_status,
            error_message=auth_result.message,
        )

    params = {"q": query, "limit": min(limit, 25), "sort": "new", "type": "link"}
    try:
        response = session.get(REDDIT_SEARCH_URL, params=params, timeout=15)
        if is_reddit_policy_block(response.status_code, response.text[:500]):
            auth_result = RedditAuthResult(
                status=RedditAuthStatus.PENDING_APPROVAL,
                auth_mode=auth_result.auth_mode,
                message=REDDIT_PENDING_MESSAGE,
                http_status=403,
            )
            persist_reddit_gated(403, response.text[:500], auth_result.auth_mode)
            return RedditSearchResult(posts=[], auth_result=auth_result, status_code=403)

        if response.status_code != 200:
            return RedditSearchResult(
                posts=[],
                auth_result=auth_result,
                status_code=response.status_code,
                error_message=f"HTTP {response.status_code}",
            )

        data = response.json()
        children = data.get("data", {}).get("children", [])
        posts = [c.get("data", {}) for c in children if c.get("data")]
        return RedditSearchResult(
            posts=posts,
            auth_result=auth_result,
            status_code=200,
        )
    except requests.RequestException as exc:
        return RedditSearchResult(
            posts=[],
            auth_result=auth_result,
            status_code=None,
            error_message=str(exc),
        )


def _assess_oauth_need(
    status_code: int | None,
    is_valid_json: bool,
    response_preview: str,
    posts_count: int | None,
    user_agent: str,
    auth_result: RedditAuthResult | None = None,
) -> tuple[bool, str]:
    preview_lower = response_preview.lower()

    if status_code == 403:
        return False, "HTTP 403 — bloqueio de IP/rede (comum em datacenter)"

    if status_code == 401:
        return True, "HTTP 401 — autenticação OAuth necessária"

    if status_code == 200 and is_valid_json:
        mode = auth_result.auth_mode if auth_result else "public"
        return False, f"Endpoint OK via {mode} — {posts_count or 0} post(s) sem OAuth obrigatório"

    if auth_result and auth_result.status == RedditAuthStatus.MISSING_CREDENTIALS:
        return True, "Configure REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET e REDDIT_USER_AGENT no .env"

    if auth_result and auth_result.status == RedditAuthStatus.AUTH_FAILED:
        return True, f"OAuth falhou: {auth_result.message}"

    if "oauth" in preview_lower or "unauthorized" in preview_lower:
        return True, "Resposta indica necessidade de OAuth"

    if status_code == 429:
        return False, "HTTP 429 — rate limit; aguarde e tente novamente"

    return False, "Verifique credenciais e User-Agent no .env"


def _build_reddit_suggestions(
    status_code: int | None,
    is_valid_json: bool,
    needs_oauth: bool,
    error_message: str | None,
    auth_result: RedditAuthResult | None = None,
) -> list[str]:
    tips: list[str] = []

    if auth_result:
        if auth_result.status == RedditAuthStatus.MISSING_CREDENTIALS:
            tips.append("Rode setup-env e preencha REDDIT_CLIENT_ID, SECRET e USER_AGENT")
        elif auth_result.status == RedditAuthStatus.AUTH_FAILED:
            tips.append("Verifique CLIENT_ID/SECRET e tipo de app no Reddit Developer Portal")

    if error_message:
        if "timeout" in error_message.lower():
            tips.append("Timeout — verifique sua conexão.")
        elif "connection" in error_message.lower():
            tips.append("Falha de conexão — firewall ou DNS.")
        else:
            tips.append(f"Erro: {error_message}")

    if status_code == 200 and is_valid_json:
        tips.append("Reddit acessível — use search-reddit para coletar dados live")
        return tips

    if status_code == 403:
        tips.extend([
            "HTTP 403 — bloqueio (comum em datacenter).",
            "Configure OAuth + User-Agent e teste em rede residencial.",
        ])
    elif status_code == 429:
        tips.append("HTTP 429 — aguarde alguns minutos.")

    if needs_oauth and status_code not in (403, 429):
        tips.append("Registre app em https://www.reddit.com/prefs/apps")

    if not tips:
        tips.append("Rode test-reddit-auth após configurar .env")

    return tips


class RedditConnector:
    """Coleta posts do Reddit via OAuth ou endpoint público."""

    def __init__(
        self,
        user_agent: str | None = None,
        subreddits: list[str] | None = None,
        query_suffix: str = "pokemon card",
        request_delay: float = 1.5,
        require_oauth: bool = False,
    ):
        self.user_agent = user_agent or get_user_agent()
        self.subreddits = subreddits or ["PokemonTCG", "pkmntcg"]
        self.query_suffix = query_suffix
        self.request_delay = request_delay
        self.require_oauth = require_oauth
        self.session = requests.Session()
        self.auth_result = apply_reddit_auth(self.session)
        self.auth_mode = self.auth_result.auth_mode
        self._gated = False

    @property
    def is_gated(self) -> bool:
        return self._gated or self.auth_result.status == RedditAuthStatus.PENDING_APPROVAL

    @property
    def uses_oauth(self) -> bool:
        return self.auth_result.token_obtained

    @property
    def auth_ok(self) -> bool:
        if self.require_oauth:
            return self.auth_result.status == RedditAuthStatus.LIVE
        return self.auth_result.status in (
            RedditAuthStatus.LIVE,
            RedditAuthStatus.PUBLIC,
        )

    def _search(
        self,
        query: str,
        limit: int = 10,
        subreddit: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_gated:
            return []

        if not self.auth_ok:
            logger.warning(
                "Reddit auth não OK (%s) — busca ignorada",
                self.auth_result.status.value,
            )
            return []

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
                logger.warning("Reddit rate limit (429); aguardando 5s...")
                time.sleep(5)
                response = self.session.get(url, params=params, timeout=15)
            if is_reddit_policy_block(response.status_code, response.text[:500]):
                self._gated = True
                self.auth_result = RedditAuthResult(
                    status=RedditAuthStatus.PENDING_APPROVAL,
                    auth_mode=self.auth_mode,
                    message=REDDIT_PENDING_MESSAGE,
                    http_status=403,
                )
                persist_reddit_gated(403, response.text[:500], self.auth_mode)
                logger.warning(REDDIT_PENDING_MESSAGE)
                return []
            if response.status_code != 200:
                logger.error("Reddit HTTP %s — busca ignorada", response.status_code)
                return []
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

    def search_query(
        self,
        query: str,
        limit: int = 10,
        card_name: str = "",
    ) -> list[RadarResult]:
        """Busca por query livre (não limitada a lista de cartas)."""
        if not self.auth_ok:
            return []

        results: list[RadarResult] = []
        seen_urls: set[str] = set()
        detected_card = card_name or "Geral"

        posts = self._search(query, limit=limit)
        for post in posts:
            url = post.get("permalink", post.get("url", ""))
            if url in seen_urls:
                continue
            seen_urls.add(url)
            result = self._post_to_result(post, detected_card)
            if result:
                if not card_name:
                    from src.normalizer import detect_card

                    detected = detect_card(result.title + " " + result.text_snippet)
                    if detected:
                        result.card_name_detected = detected
                        result.normalized_card_name = normalize_card_name(detected)
                results.append(result)

        return results[:limit]

    def search_card(self, card_name: str, limit: int = 10) -> list[RadarResult]:
        if self.is_gated:
            return []

        query = build_search_query(card_name, self.query_suffix)
        results: list[RadarResult] = []
        seen_urls: set[str] = set()

        for subreddit in self.subreddits:
            if self.is_gated:
                break
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

        if len(results) < limit // 2 and not self.is_gated:
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
        all_results: list[RadarResult] = []
        for card in cards:
            if self.is_gated:
                logger.warning("Reddit gated — interrompendo buscas restantes")
                break
            logger.info("Reddit: buscando %s...", card)
            card_results = self.search_card(card, limit=limit_per_card)
            all_results.extend(card_results)
            if self.is_gated:
                break
            time.sleep(self.request_delay)
        return all_results


def get_mock_results(card_name: str) -> list[RadarResult]:
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
