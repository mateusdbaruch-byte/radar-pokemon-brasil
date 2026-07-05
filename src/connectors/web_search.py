"""Conector de busca web — APIs oficiais (Bing, Google, SerpAPI)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import requests

from src.models import DataMode
from src.opportunity_models import Opportunity
from src.opportunity_scoring import score_opportunity

logger = logging.getLogger(__name__)

LIGHT_QUERY_TEMPLATES = [
    'procuro {card} "Pokémon TCG"',
    'compro {card} "Pokémon TCG"',
    '"alguém vende" {card} "Pokémon"',
    'vendo {card} "Pokémon TCG"',
]

DEEP_QUERY_TEMPLATES = LIGHT_QUERY_TEMPLATES + [
    '"desapego" {card} "Pokémon TCG"',
    '"abaixo da Liga" {card} "Pokémon TCG"',
    'pago {card} Pokémon',
    '"quero comprar" {card} "Pokémon TCG"',
    'troco {card} "Pokémon TCG"',
    'negocio {card} carta pokemon',
]

# Compatibilidade com imports antigos
SEARCH_QUERY_TEMPLATES = DEEP_QUERY_TEMPLATES


class ScanMode(str, Enum):
    LIGHT = "light"
    DEEP = "deep"


@dataclass
class WebSearchConfig:
    timeout_seconds: float = 20.0
    delay_seconds: float = 2.0
    max_retries: int = 2
    max_queries_per_run: int = 20

    @classmethod
    def from_env(cls, mode: ScanMode = ScanMode.LIGHT) -> WebSearchConfig:
        timeout = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "20"))
        delay = float(os.getenv("WEB_SEARCH_DELAY_SECONDS", "2"))
        retries = int(os.getenv("WEB_SEARCH_MAX_RETRIES", "2"))
        max_queries = int(os.getenv("WEB_SEARCH_MAX_QUERIES_PER_RUN", "20"))
        if mode == ScanMode.DEEP:
            delay *= 2.0
        return cls(
            timeout_seconds=timeout,
            delay_seconds=delay,
            max_retries=retries,
            max_queries_per_run=max_queries,
        )


@dataclass
class WebSearchHit:
    title: str
    snippet: str
    url: str


@dataclass
class WebSearchQueryResult:
    query: str
    hits: list[WebSearchHit] = field(default_factory=list)
    success: bool = False
    timed_out: bool = False
    retries: int = 0
    elapsed_seconds: float = 0.0
    error: str = ""


@dataclass
class WebSearchScanStats:
    queries_planned: int = 0
    queries_executed: int = 0
    queries_success: int = 0
    queries_timeout: int = 0
    queries_retried: int = 0
    hits_found: int = 0
    opportunities_built: int = 0
    urls_deduplicated: int = 0
    elapsed_seconds: float = 0.0


ProgressCallback = Callable[[WebSearchQueryResult, int, int], None]


@dataclass
class WebSearchScanResult:
    opportunities: list[Opportunity] = field(default_factory=list)
    stats: WebSearchScanStats = field(default_factory=WebSearchScanStats)


class WebSearchConnector:
    """
    Busca pública na web via API oficial configurável.

    Provedores: bing, google, serpapi (WEB_SEARCH_PROVIDER no .env).
    Não faz scraping de Google diretamente.
    """

    def __init__(self, config: WebSearchConfig | None = None) -> None:
        self.provider = os.getenv("WEB_SEARCH_PROVIDER", "").strip().lower()
        self.config = config or WebSearchConfig.from_env()
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

    def templates_for_mode(self, mode: ScanMode) -> list[str]:
        if mode == ScanMode.DEEP:
            return list(DEEP_QUERY_TEMPLATES)
        return list(LIGHT_QUERY_TEMPLATES)

    def _provider_request(
        self,
        query: str,
        limit: int,
        timeout: float,
    ) -> tuple[int, dict]:
        if self.provider == "bing":
            key = os.getenv("BING_SEARCH_API_KEY", "").strip()
            resp = self.session.get(
                "https://api.bing.microsoft.com/v7.0/search",
                params={"q": query, "count": min(limit, 50), "mkt": "pt-BR"},
                headers={"Ocp-Apim-Subscription-Key": key},
                timeout=timeout,
            )
            return resp.status_code, resp.json() if resp.status_code == 200 else {}

        if self.provider == "google":
            resp = self.session.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": os.getenv("GOOGLE_SEARCH_API_KEY", "").strip(),
                    "cx": os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip(),
                    "q": query,
                    "num": min(limit, 10),
                    "lr": "lang_pt",
                },
                timeout=timeout,
            )
            return resp.status_code, resp.json() if resp.status_code == 200 else {}

        if self.provider == "serpapi":
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
                timeout=timeout,
            )
            return resp.status_code, resp.json() if resp.status_code == 200 else {}

        return 0, {}

    def _parse_hits(self, data: dict, limit: int) -> list[WebSearchHit]:
        hits: list[WebSearchHit] = []
        if self.provider == "bing":
            for item in data.get("webPages", {}).get("value", []):
                hits.append(WebSearchHit(
                    title=item.get("name", ""),
                    snippet=item.get("snippet", ""),
                    url=item.get("url", ""),
                ))
        elif self.provider == "google":
            for item in data.get("items", []):
                hits.append(WebSearchHit(
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    url=item.get("link", ""),
                ))
        elif self.provider == "serpapi":
            for item in data.get("organic_results", []):
                hits.append(WebSearchHit(
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    url=item.get("link", ""),
                ))
        return hits[:limit]

    def _should_retry(self, exc: Exception | None, status_code: int) -> bool:
        if exc is not None:
            return isinstance(
                exc,
                (requests.Timeout, requests.ConnectionError),
            )
        return status_code in (429, 500, 502, 503, 504)

    def search_query(self, query: str, limit: int = 10) -> WebSearchQueryResult:
        """Executa uma query com timeout, retry e backoff exponencial."""
        result = WebSearchQueryResult(query=query)
        if not self.is_configured():
            result.error = "web_search não configurado"
            return result

        start = time.monotonic()
        last_error = ""

        for attempt in range(self.config.max_retries + 1):
            if attempt > 0:
                result.retries = attempt
                backoff = self.config.delay_seconds * (2 ** (attempt - 1))
                time.sleep(backoff)

            try:
                status_code, data = self._provider_request(
                    query,
                    limit,
                    self.config.timeout_seconds,
                )
            except requests.Timeout:
                last_error = "timeout"
                result.timed_out = True
                if attempt < self.config.max_retries:
                    continue
                break
            except requests.RequestException as exc:
                last_error = str(exc)
                if self._should_retry(exc, 0) and attempt < self.config.max_retries:
                    continue
                break
            else:
                if status_code == 200:
                    result.hits = self._parse_hits(data, limit)
                    result.success = True
                    result.elapsed_seconds = time.monotonic() - start
                    return result

                last_error = f"HTTP {status_code}"
                logger.warning("%s Search HTTP %s for query: %s", self.provider, status_code, query)
                if self._should_retry(None, status_code) and attempt < self.config.max_retries:
                    continue
                break

        result.error = last_error or "falha desconhecida"
        result.elapsed_seconds = time.monotonic() - start
        return result

    def scan_cards(
        self,
        cards: list[str],
        limit_per_query: int = 5,
        mode: ScanMode = ScanMode.LIGHT,
        max_queries: int | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> WebSearchScanResult:
        """Busca oportunidades para cada carta usando templates de intenção."""
        scan = WebSearchScanResult()
        stats = scan.stats

        if not self.is_configured():
            return scan

        templates = self.templates_for_mode(mode)
        planned: list[tuple[str, str]] = []
        for card in cards:
            for template in templates:
                planned.append((card, template.format(card=card)))

        cap = max_queries if max_queries is not None else self.config.max_queries_per_run
        if cap > 0:
            planned = planned[:cap]
        stats.queries_planned = len(planned)

        seen_urls: dict[str, Opportunity] = {}
        scan_start = time.monotonic()

        for idx, (card, query) in enumerate(planned, start=1):
            if idx > 1 and self.config.delay_seconds > 0:
                time.sleep(self.config.delay_seconds)

            query_result = self.search_query(query, limit=limit_per_query)
            stats.queries_executed += 1
            if query_result.success:
                stats.queries_success += 1
            if query_result.timed_out:
                stats.queries_timeout += 1
            if query_result.retries > 0:
                stats.queries_retried += 1
            stats.hits_found += len(query_result.hits)

            if on_progress:
                on_progress(query_result, idx, len(planned))

            for hit in query_result.hits:
                if not hit.url:
                    continue
                if hit.url in seen_urls:
                    stats.urls_deduplicated += 1
                    existing = seen_urls[hit.url]
                    _append_related_card_evidence(existing, card, query, hit)
                    continue

                evidence = f"{hit.title} {hit.snippet}".strip()
                opp = score_opportunity(
                    evidence=evidence,
                    card_name=card,
                    source="web_search",
                    platform=self.provider,
                    url=hit.url,
                    urgency_hint=55,
                )
                opp.data_mode = DataMode.LIVE
                opp.set_raw_data({
                    "query": query,
                    "hit": hit.__dict__,
                    "related_cards": [card],
                })
                seen_urls[hit.url] = opp
                scan.opportunities.append(opp)
                stats.opportunities_built += 1

        stats.elapsed_seconds = time.monotonic() - scan_start
        return scan


def _append_related_card_evidence(
    opp: Opportunity,
    card: str,
    query: str,
    hit: WebSearchHit,
) -> None:
    import json

    try:
        raw = json.loads(opp.raw_data_json or "{}")
    except json.JSONDecodeError:
        raw = {}

    related = raw.setdefault("related_cards", [])
    if card not in related:
        related.append(card)

    extra = raw.setdefault("related_evidence", [])
    snippet = f"[{card}] {hit.title} — query: {query}"
    if snippet not in extra:
        extra.append(snippet)

    opp.set_raw_data(raw)
    if card.lower() not in opp.evidence_text.lower():
        opp.evidence_text = f"{opp.evidence_text}\n[{card}] {hit.title}".strip()[:2000]
