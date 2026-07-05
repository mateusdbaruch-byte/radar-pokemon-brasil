"""Formatação e exibição do relatório de inteligência de mercado."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.market_intelligence import (
    CardMarketInsight,
    Recommendation,
    analyze_all_cards,
    recommendation_style,
)
from src.models import DataMode, RadarResult
from src.normalizer import normalize_card_name
from src.database import count_by_data_mode

RECOMMENDATION_PRIORITY: dict[Recommendation, int] = {
    "boa demanda": 4,
    "possível oportunidade": 3,
    "observar": 2,
    "muita oferta": 1,
    "dados insuficientes": 0,
}

RECOMMENDATION_HELP: dict[Recommendation, str] = {
    "boa demanda": "Compradores ativos superam a oferta — vale acompanhar de perto.",
    "possível oportunidade": "Há demanda e anúncios ao mesmo tempo — pode haver negócio.",
    "muita oferta": "Muitos anúncios e pouca procura — mercado saturado.",
    "observar": "Sinais mistos — colete mais dados antes de decidir.",
    "dados insuficientes": "Poucos sinais — rode outra busca ou amplie as fontes.",
}


@dataclass
class MarketSummary:
    """Resumo executivo do mercado monitorado."""

    cards_monitored: int
    cards_with_data: int
    total_signals: int
    total_buy_signals: int
    total_sell_signals: int
    total_listings: int
    top_demand_card: str | None
    top_demand_score: float
    highlight_cards: list[CardMarketInsight]


def format_price_brl(value: float | None) -> str:
    """Formata preço em reais (padrão brasileiro) ou traço."""
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_market_summary(
    insights: list[CardMarketInsight],
    monitored_cards: list[str] | None = None,
) -> MarketSummary:
    """Monta resumo executivo a partir dos insights por carta."""
    monitored = monitored_cards or [i.card_name for i in insights]
    with_data = [i for i in insights if i.total_signals > 0]

    top_demand = max(with_data, key=lambda i: (i.demand_score_avg, i.buy_signals), default=None)

    highlights = sorted(
        [i for i in with_data if i.recommendation != "dados insuficientes"],
        key=lambda i: (
            RECOMMENDATION_PRIORITY.get(i.recommendation, 0),
            i.demand_score_avg,
            i.buy_signals,
        ),
        reverse=True,
    )[:3]

    return MarketSummary(
        cards_monitored=len(monitored),
        cards_with_data=len(with_data),
        total_signals=sum(i.total_signals for i in insights),
        total_buy_signals=sum(i.buy_signals for i in insights),
        total_sell_signals=sum(i.sell_signals for i in insights),
        total_listings=sum(i.listing_count for i in insights),
        top_demand_card=top_demand.card_name if top_demand else None,
        top_demand_score=top_demand.demand_score_avg if top_demand else 0.0,
        highlight_cards=highlights,
    )


def build_card_narrative(insight: CardMarketInsight) -> str:
    """Gera frase interpretativa para uma carta."""
    parts: list[str] = []

    if insight.total_signals == 0:
        return "Nenhum sinal coletado para esta carta."

    if insight.buy_signals:
        parts.append(
            f"{insight.buy_signals} sinal(is) de compra"
            + (f" (demanda média {insight.demand_score_avg:.0f}/100)" if insight.demand_score_avg else "")
        )
    if insight.sell_signals:
        parts.append(f"{insight.sell_signals} sinal(is) de venda")
    if insight.listing_count:
        parts.append(f"{insight.listing_count} anúncio(s)")

    if insight.avg_price is not None:
        parts.append(
            f"preço médio {format_price_brl(insight.avg_price)}"
            f" (faixa {format_price_brl(insight.min_price)} – {format_price_brl(insight.max_price)})"
        )

    if insight.main_source != "—":
        parts.append(f"fonte principal: {insight.main_source}")

    narrative_body = "; ".join(parts)
    narrative = (narrative_body[0].upper() + narrative_body[1:] + ".") if narrative_body else ""
    help_text = RECOMMENDATION_HELP.get(insight.recommendation, "")
    return f"{narrative} {help_text}".strip()


def _insights_for_monitored_cards(
    results: list[RadarResult],
    monitored_cards: list[str] | None,
) -> list[CardMarketInsight]:
    """Garante uma linha por carta monitorada, mesmo sem dados."""
    insights = analyze_all_cards(results)
    if not monitored_cards:
        return insights

    by_name = {i.card_name: i for i in insights}
    ordered: list[CardMarketInsight] = []
    for card in monitored_cards:
        canonical = normalize_card_name(card)
        ordered.append(by_name.get(canonical, analyze_card_empty(canonical)))
    return ordered


def analyze_card_empty(card_name: str) -> CardMarketInsight:
    """Insight vazio para carta sem resultados."""
    from src.market_intelligence import analyze_card  # evita import circular no topo

    return analyze_card(card_name, [])


def display_data_mode_summary(console: Console, results: list[RadarResult]) -> None:
    """Exibe contagem por origem dos dados e aviso se houver mock."""
    counts = count_by_data_mode(results)
    live = counts.get(DataMode.LIVE.value, 0)
    mock = counts.get(DataMode.MOCK.value, 0)
    manual = counts.get(DataMode.MANUAL_IMPORT.value, 0)
    total = live + mock + manual

    lines = [
        f"[bold]Origem dos dados[/bold] ({total} resultados no relatório):",
        f"  • [green]live[/green] (APIs reais): [bold]{live}[/bold]",
        f"  • [yellow]mock[/yellow] (simulados): [bold]{mock}[/bold]",
        f"  • [cyan]manual_import[/cyan] (importação manual): [bold]{manual}[/bold]",
    ]

    if mock > 0:
        console.print()
        console.print(
            Panel(
                "[bold red]ATENÇÃO: este relatório contém dados simulados "
                "e não deve ser usado para decisão de mercado.[/bold red]\n\n"
                f"Dados simulados (mock): {mock} de {total} resultados.\n"
                "Para validação real, rode: [bold]python3 -m src.main search --no-mock[/bold] "
                "e verifique se [bold]live[/bold] > 0.",
                border_style="red",
                title="⚠️ DADOS SIMULADOS",
            )
        )
    elif total > 0 and live == total:
        lines.append("\n[green]✓ Todos os dados são reais (live).[/green]")

    console.print(Panel("\n".join(lines), title="🔖 Modo dos dados", border_style="blue"))


def display_executive_summary(console: Console, summary: MarketSummary) -> None:
    """Painel de resumo executivo do mercado."""
    lines = [
        f"[bold]Cartas monitoradas:[/bold] {summary.cards_monitored}  "
        f"([green]{summary.cards_with_data} com dados[/green])",
        f"[bold]Sinais coletados:[/bold] {summary.total_signals}  "
        f"|  Compra: [green]{summary.total_buy_signals}[/green]  "
        f"|  Venda: [yellow]{summary.total_sell_signals}[/yellow]  "
        f"|  Anúncios: {summary.total_listings}",
    ]
    if summary.top_demand_card:
        lines.append(
            f"[bold]Maior demanda:[/bold] {summary.top_demand_card} "
            f"(score {summary.top_demand_score:.0f}/100)"
        )

    console.print(Panel("\n".join(lines), title="📊 Resumo Executivo", border_style="blue"))


def display_highlights(console: Console, highlights: list[CardMarketInsight]) -> None:
    """Destaques interpretativos das cartas mais relevantes."""
    if not highlights:
        return

    console.print("\n[bold]🔎 Destaques de mercado[/bold]\n")
    for insight in highlights:
        style = recommendation_style(insight.recommendation)
        title = Text()
        title.append(insight.card_name, style="bold")
        title.append(" — ")
        title.append(insight.recommendation, style=style)
        console.print(Panel(build_card_narrative(insight), title=title, border_style="cyan"))


def display_market_table(console: Console, insights: list[CardMarketInsight]) -> None:
    """Tabela consolidada de inteligência por carta."""
    console.print("\n[bold]📈 Inteligência por carta[/bold]\n")

    table = Table(show_lines=True)
    table.add_column("Carta", style="bold", min_width=11)
    table.add_column("Preço mín.", justify="right", min_width=10)
    table.add_column("Preço máx.", justify="right", min_width=10)
    table.add_column("Preço méd.", justify="right", min_width=10)
    table.add_column("Anúncios", justify="center", min_width=8)
    table.add_column("Compra", justify="center", min_width=7)
    table.add_column("Venda", justify="center", min_width=6)
    table.add_column("Demanda", justify="center", min_width=8)
    table.add_column("Fonte", min_width=13)
    table.add_column("Recomendação", min_width=22)

    for insight in insights:
        demand_style = (
            "green" if insight.demand_score_avg >= 70
            else "yellow" if insight.demand_score_avg >= 40
            else "dim"
        )
        rec_style = recommendation_style(insight.recommendation)
        demand_label = (
            f"[{demand_style}]{insight.demand_score_avg:.0f}[/{demand_style}]"
            if insight.buy_signals
            else "—"
        )
        table.add_row(
            insight.card_name,
            format_price_brl(insight.min_price),
            format_price_brl(insight.max_price),
            format_price_brl(insight.avg_price),
            str(insight.listing_count),
            str(insight.buy_signals),
            str(insight.sell_signals),
            demand_label,
            insight.main_source,
            f"[{rec_style}]{insight.recommendation}[/{rec_style}]",
        )

    console.print(table)

    console.print(
        "\n[dim]Legenda — Recomendações: "
        "boa demanda = compradores ativos | possível oportunidade = demanda + oferta | "
        "muita oferta = mercado saturado | observar = sinais mistos | "
        "dados insuficientes = poucos sinais[/dim]\n"
    )


def display_top_signals(console: Console, results: list[RadarResult], top_n: int = 5) -> None:
    """Lista compacta dos melhores sinais individuais (detalhe complementar)."""
    if not results or top_n <= 0:
        return

    sorted_results = sorted(results, key=lambda r: r.intent_score, reverse=True)[:top_n]

    table = Table(show_lines=True, title="🎯 Top sinais individuais (detalhe)")
    table.add_column("Score", width=6)
    table.add_column("Intenção", width=16)
    table.add_column("Carta", width=12)
    table.add_column("Fonte", min_width=13)
    table.add_column("Modo", min_width=8)
    table.add_column("Trecho", width=36)

    for r in sorted_results:
        score_style = (
            "green" if r.intent_score >= 70
            else "yellow" if r.intent_score >= 40
            else "dim"
        )
        mode_style = {
            DataMode.LIVE.value: "green",
            DataMode.MOCK.value: "yellow",
            DataMode.MANUAL_IMPORT.value: "cyan",
        }.get(r.data_mode.value, "dim")
        table.add_row(
            f"[{score_style}]{r.intent_score}[/{score_style}]",
            r.intent_type.value,
            r.normalized_card_name,
            r.source,
            f"[{mode_style}]{r.data_mode.value}[/{mode_style}]",
            (r.title or r.text_snippet)[:60],
        )

    console.print(table)


def display_market_report(
    console: Console,
    results: list[RadarResult],
    monitored_cards: list[str] | None = None,
    top_signals: int = 5,
) -> None:
    """
    Relatório completo de inteligência de mercado.

    Ordem: resumo executivo → destaques → tabela por carta → top sinais.
    """
    insights = _insights_for_monitored_cards(results, monitored_cards)
    summary = build_market_summary(insights, monitored_cards)

    if summary.total_signals == 0:
        console.print("[yellow]Nenhum dado para análise de mercado.[/yellow]")
        return

    display_data_mode_summary(console, results)
    console.print()
    display_executive_summary(console, summary)
    display_highlights(console, summary.highlight_cards)
    display_market_table(console, insights)

    if top_signals > 0:
        console.print()
        display_top_signals(console, results, top_n=top_signals)
