"""Comando market-snapshot — visão de mercado com dados reais (live + manual_import)."""

from __future__ import annotations

from collections import defaultdict

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.database import fetch_all
from src.market_intelligence import analyze_all_cards
from src.reporting import format_price_brl
from src.models import DataMode, RadarResult
from src.paths import DEFAULT_DB


def _filter_real_data(results: list[RadarResult]) -> list[RadarResult]:
    """Exclui mock — usa apenas live e manual_import."""
    return [
        r
        for r in results
        if r.data_mode in (DataMode.LIVE, DataMode.MANUAL_IMPORT)
    ]


def display_market_snapshot(console: Console, db_path=DEFAULT_DB) -> None:
    """Exibe snapshot de mercado sem dados mock."""
    all_results = fetch_all(db_path)
    real_results = _filter_real_data(all_results)

    live_count = sum(1 for r in real_results if r.data_mode == DataMode.LIVE)
    manual_count = sum(1 for r in real_results if r.data_mode == DataMode.MANUAL_IMPORT)

    console.print("[bold blue]📸 Market Snapshot — dados reais[/bold blue]\n")

    if not real_results:
        console.print(
            Panel(
                "[yellow]Nenhum dado real no banco.[/yellow]\n\n"
                "Colete dados com:\n"
                "  • [bold]search-reddit[/bold] ou [bold]search --live-only[/bold]\n"
                "  • [bold]import-prices[/bold] para LigaPokemon/MYP Cards\n\n"
                "Mock não é incluído neste snapshot.",
                border_style="yellow",
                title="Sem dados",
            )
        )
        return

    sources = sorted({r.source for r in real_results})
    cards_with_data = sorted({r.normalized_card_name for r in real_results})

    prices_by_card: dict[str, list[float]] = defaultdict(list)
    for r in real_results:
        if r.price is not None:
            prices_by_card[r.normalized_card_name].append(r.price)

    summary_lines = [
        f"[bold]Registros live:[/bold] {live_count}",
        f"[bold]Registros manual_import:[/bold] {manual_count}",
        f"[bold]Fontes disponíveis:[/bold] {', '.join(sources)}",
        f"[bold]Cartas com dados:[/bold] {len(cards_with_data)}",
    ]
    console.print(Panel("\n".join(summary_lines), title="Resumo", border_style="blue"))

    if live_count == 0:
        console.print()
        console.print(
            Panel(
                "[yellow]Atenção: não há dados live — apenas importação manual.[/yellow]\n"
                "Configure Reddit OAuth e rode search-reddit para validar APIs.",
                border_style="yellow",
                title="Sem dados live",
            )
        )

    table = Table(title="Preços por carta (live + manual)", show_lines=True)
    table.add_column("Carta", style="bold")
    table.add_column("Registros", justify="center")
    table.add_column("Mín.", justify="right")
    table.add_column("Méd.", justify="right")
    table.add_column("Máx.", justify="right")
    table.add_column("Fontes")

    card_sources: dict[str, set[str]] = defaultdict(set)
    card_counts: dict[str, int] = defaultdict(int)
    for r in real_results:
        card_sources[r.normalized_card_name].add(r.source)
        card_counts[r.normalized_card_name] += 1

    for card in cards_with_data:
        prices = prices_by_card.get(card, [])
        if prices:
            table.add_row(
                card,
                str(card_counts[card]),
                format_price_brl(min(prices)),
                format_price_brl(sum(prices) / len(prices)),
                format_price_brl(max(prices)),
                ", ".join(sorted(card_sources[card])),
            )
        else:
            table.add_row(
                card,
                str(card_counts[card]),
                "—",
                "—",
                "—",
                ", ".join(sorted(card_sources[card])),
            )

    console.print()
    console.print(table)

    insights = analyze_all_cards(real_results, cards_with_data)
    with_signals = [i for i in insights if i.total_signals > 0]
    if with_signals:
        console.print(f"\n[dim]{len(with_signals)} carta(s) com sinais analisáveis. "
                      f"Use [bold]report[/bold] para relatório completo.[/dim]")
