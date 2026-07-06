"""Conector de busca web — APIs oficiais (Bing, Google, SerpAPI)."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import requests

from src.freshness import apply_freshness_to_opportunity, google_recency_param, serpapi_recency_param
from src.models import DataMode
from src.opportunity_db import save_query_run, save_rejected_result
from src.opportunity_models import Opportunity
from src.opportunity_quality import QualityFilterConfig, evaluate_hit, extract_domain
from src.opportunity_scoring import score_opportunity
from src.search_budget import (
    BudgetExceededError,
    SearchBudgetContext,
    assert_budget_available,
    record_search,
    store_cache,
    try_cache_hit,
)
from src.tcg_knowledge import enrich_opportunity, generate_enriched_queries

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
    cached: bool = False


@dataclass
class WebSearchScanStats:
    queries_planned: int = 0
    queries_executed: int = 0
    queries_success: int = 0
    queries_timeout: int = 0
    queries_retried: int = 0
    hits_found: int = 0
    opportunities_built: int = 0
    results_rejected: int = 0
    urls_deduplicated: int = 0
    elapsed_seconds: float = 0.0
    queries_cached: int = 0
    budget_stopped: bool = False
    budget_message: str = ""


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

    def templates_for_mode(
        self,
        mode: ScanMode,
        buyer_only: bool = False,
        seller_only: bool = False,
    ) -> list[str]:
        """Templates com placeholder {card} — use get_queries_for_card para expandir."""
        return generate_enriched_queries(
            "{card}",
            mode.value,
            buyer_only=buyer_only,
            seller_only=seller_only,
        )

    def get_queries_for_card(
        self,
        card: str,
        mode: ScanMode,
        buyer_only: bool = False,
        seller_only: bool = False,
    ) -> list[str]:
        return generate_enriched_queries(
            card, mode.value, buyer_only=buyer_only, seller_only=seller_only
        )

    def _provider_request(
        self,
        query: str,
        limit: int,
        timeout: float,
        recency_days: int | None = None,
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
            params: dict = {
                "key": os.getenv("GOOGLE_SEARCH_API_KEY", "").strip(),
                "cx": os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip(),
                "q": query,
                "num": min(limit, 10),
                "lr": "lang_pt",
                "hl": "pt",
                "cr": "countryBR",
            }
            date_restrict = google_recency_param(recency_days)
            if date_restrict:
                params["dateRestrict"] = date_restrict
            resp = self.session.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
                timeout=timeout,
            )
            return resp.status_code, resp.json() if resp.status_code == 200 else {}

        if self.provider == "serpapi":
            params = {
                "api_key": os.getenv("SERPAPI_KEY", "").strip(),
                "q": query,
                "engine": "google",
                "google_domain": "google.com.br",
                "hl": "pt",
                "gl": "br",
                "num": min(limit, 20),
            }
            tbs = serpapi_recency_param(recency_days)
            if tbs:
                params["tbs"] = tbs
            resp = self.session.get(
                "https://serpapi.com/search",
                params=params,
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

    def search_query(
        self,
        query: str,
        limit: int = 10,
        budget_ctx: SearchBudgetContext | None = None,
    ) -> WebSearchQueryResult:
        """Executa uma query com timeout, retry, cache e controle de orçamento."""
        result = WebSearchQueryResult(query=query)
        if not self.is_configured():
            result.error = "web_search não configurado"
            return result

        ctx = budget_ctx or SearchBudgetContext(provider=self.provider)
        ctx.provider = self.provider
        recency_days = ctx.recency_days

        if ctx.cache_enabled:
            cached_hits = try_cache_hit(ctx, query, limit)
            if cached_hits is not None:
                result.hits = [
                    WebSearchHit(
                        title=h.get("title", ""),
                        snippet=h.get("snippet", ""),
                        url=h.get("url", ""),
                    )
                    for h in cached_hits
                ]
                result.success = True
                result.cached = True
                record_search(
                    ctx, query,
                    success=True,
                    results_count=len(result.hits),
                    cached=True,
                    cost_unit=0,
                )
                return result

        try:
            assert_budget_available(ctx)
        except BudgetExceededError as exc:
            result.error = str(exc)
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
                    recency_days=recency_days,
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
                    record_search(
                        ctx, query,
                        success=True,
                        results_count=len(result.hits),
                        cached=False,
                        cost_unit=1,
                    )
                    if ctx.cache_enabled and result.hits:
                        store_cache(
                            ctx,
                            query,
                            limit,
                            [h.__dict__ for h in result.hits],
                        )
                    return result

                last_error = f"HTTP {status_code}"
                logger.warning("%s Search HTTP %s for query: %s", self.provider, status_code, query)
                if self._should_retry(None, status_code) and attempt < self.config.max_retries:
                    continue
                break

        result.error = last_error or "falha desconhecida"
        result.elapsed_seconds = time.monotonic() - start
        record_search(
            ctx, query,
            success=False,
            results_count=0,
            cached=False,
            cost_unit=1,
        )
        return result

    def scan_cards(
        self,
        cards: list[str],
        limit_per_query: int = 5,
        mode: ScanMode = ScanMode.LIGHT,
        max_queries: int | None = None,
        on_progress: ProgressCallback | None = None,
        quality_config: QualityFilterConfig | None = None,
        profile_name: str = "",
        query_templates: list[str] | None = None,
        budget_ctx: SearchBudgetContext | None = None,
        queries_per_card: int | None = None,
        planned_queries: list[tuple[str, str]] | None = None,
        recency_days: int | None = None,
    ) -> WebSearchScanResult:
        """Busca oportunidades para cada carta usando templates de intenção."""
        scan = WebSearchScanResult()
        stats = scan.stats
        qcfg = quality_config or QualityFilterConfig()
        profile = profile_name or qcfg.profile_name

        if not self.is_configured():
            return scan

        planned: list[tuple[str, str]] = []
        templates = query_templates
        if planned_queries:
            planned = list(planned_queries)
        else:
            for card in cards:
                if templates:
                    queries = [t.format(card=card) for t in templates]
                else:
                    queries = self.get_queries_for_card(
                        card,
                        mode,
                        buyer_only=qcfg.buyer_only,
                        seller_only=qcfg.seller_only,
                    )
                if queries_per_card and queries_per_card > 0:
                    queries = queries[:queries_per_card]
                for query in queries:
                    planned.append((card, query))

        cap = max_queries if max_queries is not None else self.config.max_queries_per_run
        if cap > 0:
            planned = planned[:cap]
        stats.queries_planned = len(planned)

        seen_urls: dict[str, Opportunity] = {}
        scan_start = time.monotonic()

        base_ctx = budget_ctx or SearchBudgetContext(provider=self.provider)
        base_ctx.provider = self.provider
        base_ctx.profile = profile

        for idx, (card, query) in enumerate(planned, start=1):
            if idx > 1 and self.config.delay_seconds > 0:
                time.sleep(self.config.delay_seconds)

            query_ctx = SearchBudgetContext(
                provider=base_ctx.provider,
                profile=base_ctx.profile,
                card=card,
                use_cache=base_ctx.use_cache,
                no_cache=base_ctx.no_cache,
                cache_ttl_hours=base_ctx.cache_ttl_hours,
                daily_budget=base_ctx.daily_budget,
                monthly_budget=base_ctx.monthly_budget,
                stop_when_reached=base_ctx.stop_when_reached,
                budget_mode=base_ctx.budget_mode,
                recency_days=recency_days or base_ctx.recency_days,
            )

            query_result = self.search_query(query, limit=limit_per_query, budget_ctx=query_ctx)
            if query_result.error and "Limite" in query_result.error:
                stats.budget_stopped = True
                stats.budget_message = query_result.error
                break

            stats.queries_executed += 1
            if query_result.cached:
                stats.queries_cached += 1
            if query_result.success:
                stats.queries_success += 1
            if query_result.timed_out:
                stats.queries_timeout += 1
            if query_result.retries > 0:
                stats.queries_retried += 1
            stats.hits_found += len(query_result.hits)

            if on_progress:
                on_progress(query_result, idx, len(planned))

            query_saved = 0
            query_rejected = 0
            query_domains: set[str] = set()

            for hit in query_result.hits:
                if not hit.url:
                    continue
                domain = extract_domain(hit.url)
                if domain:
                    query_domains.add(domain)
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
                opp = enrich_opportunity(opp, evidence)
                evaluation = evaluate_hit(
                    hit.title, hit.snippet, hit.url, card, opp, qcfg
                )
                if not evaluation.accepted:
                    save_rejected_result(
                        query,
                        hit.title,
                        hit.snippet,
                        hit.url,
                        evaluation.reason,
                        reason_category=evaluation.reason_category,
                        profile=profile,
                        card=card,
                    )
                    stats.results_rejected += 1
                    query_rejected += 1
                    continue

                opp.data_mode = DataMode.LIVE
                opp.why_saved = evaluation.why_saved
                opp.profile = profile
                opp = apply_freshness_to_opportunity(
                    opp,
                    title=hit.title,
                    snippet=hit.snippet,
                    recency_days=recency_days or base_ctx.recency_days,
                )
                enrich_opportunity(opp, evidence)
                if evaluation.refined_type:
                    opp.opportunity_type = evaluation.refined_type
                    from src.opportunity_scoring import recommended_action_for
                    opp.recommended_action = recommended_action_for(
                        opp.opportunity_type, opp.intent_score
                    )
                opp.set_raw_data({
                    "query": query,
                    "profile": profile,
                    "hit": hit.__dict__,
                    "related_cards": [card],
                })
                seen_urls[hit.url] = opp
                scan.opportunities.append(opp)
                stats.opportunities_built += 1
                query_saved += 1

            save_query_run(
                profile,
                card,
                query,
                total_results=len(query_result.hits),
                saved_count=query_saved,
                rejected_count=query_rejected,
                timeout_count=1 if query_result.timed_out else 0,
                duration_seconds=query_result.elapsed_seconds,
                domains_found=sorted(query_domains),
            )

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
