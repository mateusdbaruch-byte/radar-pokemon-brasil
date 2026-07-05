"""Análise de inteligência de mercado por carta Pokémon."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from src.models import IntentType, RadarResult

Recommendation = Literal[
    "observar",
    "boa demanda",
    "muita oferta",
    "possível oportunidade",
    "dados insuficientes",
]

SOURCE_LABELS = {
    "reddit": "Reddit",
    "mercado_livre": "Mercado Livre",
    "youtube": "YouTube",
    "discord": "Discord",
}


@dataclass
class CardMarketInsight:
    """Resumo de inteligência de mercado para uma carta."""

    card_name: str
    min_price: float | None
    max_price: float | None
    avg_price: float | None
    currency: str
    listing_count: int
    buy_signals: int
    sell_signals: int
    demand_score_avg: float
    main_source: str
    total_signals: int
    recommendation: Recommendation

    @property
    def price_range_label(self) -> str:
        """Formata faixa de preço para exibição."""
        if self.min_price is None:
            return "—"
        if self.max_price is None or self.min_price == self.max_price:
            return f"R$ {self.min_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        lo = f"{self.min_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        hi = f"{self.max_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {lo} – R$ {hi}"


def _format_brl(value: float) -> str:
    """Formata valor em reais (padrão brasileiro)."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _is_listing(result: RadarResult) -> bool:
    """Identifica anúncios/referências de preço."""
    if result.source == "mercado_livre":
        return True
    return result.intent_type in (IntentType.SELL_INTENT, IntentType.PRICE_REFERENCE)


def compute_recommendation(
    total_signals: int,
    buy_signals: int,
    sell_signals: int,
    listing_count: int,
    demand_score_avg: float,
) -> Recommendation:
    """
    Gera recomendação simples com base nos sinais coletados.

    Regras (em ordem de prioridade):
    - dados insuficientes: poucos sinais para concluir algo
    - boa demanda: compradores claros superam oferta
    - muita oferta: muitos anúncios/vendas vs pouca demanda
    - possível oportunidade: demanda e oferta coexistem
    - observar: há dados, mas cenário ainda incerto
    """
    if total_signals < 2:
        return "dados insuficientes"

    if buy_signals >= 2 and buy_signals > sell_signals and demand_score_avg >= 70:
        return "boa demanda"

    if listing_count >= 3 and sell_signals >= 2 and sell_signals > buy_signals:
        return "muita oferta"

    if buy_signals >= 1 and listing_count >= 1 and demand_score_avg >= 55:
        return "possível oportunidade"

    if total_signals >= 2:
        return "observar"

    return "dados insuficientes"


def analyze_card(card_name: str, results: list[RadarResult]) -> CardMarketInsight:
    """Calcula métricas de mercado para uma carta."""
    if not results:
        return CardMarketInsight(
            card_name=card_name,
            min_price=None,
            max_price=None,
            avg_price=None,
            currency="BRL",
            listing_count=0,
            buy_signals=0,
            sell_signals=0,
            demand_score_avg=0.0,
            main_source="—",
            total_signals=0,
            recommendation="dados insuficientes",
        )

    prices = [r.price for r in results if r.price is not None and r.price > 0]
    buy_results = [r for r in results if r.intent_type == IntentType.BUY_INTENT]
    sell_results = [r for r in results if r.intent_type == IntentType.SELL_INTENT]
    listings = [r for r in results if _is_listing(r)]

    source_counts = Counter(r.source for r in results)
    main_source_key = source_counts.most_common(1)[0][0] if source_counts else "—"
    main_source = SOURCE_LABELS.get(main_source_key, main_source_key)

    demand_scores = [r.intent_score for r in buy_results]
    demand_score_avg = round(sum(demand_scores) / len(demand_scores), 1) if demand_scores else 0.0

    currency = next((r.currency for r in results if r.currency), "BRL")

    buy_signals = len(buy_results)
    sell_signals = len(sell_results)
    listing_count = len(listings)
    total_signals = len(results)

    return CardMarketInsight(
        card_name=card_name,
        min_price=min(prices) if prices else None,
        max_price=max(prices) if prices else None,
        avg_price=round(sum(prices) / len(prices), 2) if prices else None,
        currency=currency,
        listing_count=listing_count,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        demand_score_avg=demand_score_avg,
        main_source=main_source,
        total_signals=total_signals,
        recommendation=compute_recommendation(
            total_signals, buy_signals, sell_signals, listing_count, demand_score_avg
        ),
    )


def analyze_all_cards(results: list[RadarResult]) -> list[CardMarketInsight]:
    """Agrupa resultados por carta e gera insights ordenados por demanda."""
    by_card: dict[str, list[RadarResult]] = {}
    for result in results:
        card = result.normalized_card_name
        by_card.setdefault(card, []).append(result)

    insights = [analyze_card(card, card_results) for card, card_results in by_card.items()]
    # Prioriza cartas com mais demanda e depois por score médio
    insights.sort(
        key=lambda i: (i.buy_signals, i.demand_score_avg, i.total_signals),
        reverse=True,
    )
    return insights


def recommendation_style(recommendation: Recommendation) -> str:
    """Retorna estilo Rich para colorir a recomendação."""
    styles = {
        "boa demanda": "bold green",
        "possível oportunidade": "bold cyan",
        "muita oferta": "bold yellow",
        "observar": "dim",
        "dados insuficientes": "dim italic",
    }
    return styles.get(recommendation, "white")
