"""CLI principal do Radar Pokémon Brasil."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from src.connectors.discord_placeholder import DiscordPlaceholderConnector
from src.connectors.mercado_livre import MercadoLivreConnector, get_mock_results as ml_mock
from src.connectors.reddit import RedditConnector, get_mock_results as reddit_mock
from src.connectors.youtube import YouTubeConnector
from src.database import count_results, fetch_all, save_results
from src.exporters import export_to_csv
from src.market_intelligence import (
    analyze_all_cards,
    recommendation_style,
)
from src.paths import DEFAULT_CARDS, DEFAULT_CSV, DEFAULT_DB, DEFAULT_SOURCES, PROJECT_ROOT

# Carrega variáveis de ambiente do .env na raiz do projeto
load_dotenv(PROJECT_ROOT / ".env")

app = typer.Typer(
    name="radar-pokemon-brasil",
    help="MVP de inteligência de demanda para cartas Pokémon TCG no Brasil.",
    no_args_is_help=True,
)
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_path=False)],
)
logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    """Carrega arquivo YAML de configuração."""
    if not path.exists():
        console.print(f"[red]Arquivo não encontrado: {path}[/red]")
        raise typer.Exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_cards(cards_path: Path) -> list[str]:
    """Carrega lista de cartas do YAML."""
    data = load_yaml(cards_path)
    return data.get("cards", [])


def load_sources_config(sources_path: Path) -> dict:
    """Carrega configuração de fontes."""
    return load_yaml(sources_path).get("sources", {})


def _format_price(value: float | None) -> str:
    """Formata preço em reais ou retorna traço."""
    if value is None:
        return "—"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def display_market_intelligence(results: list) -> None:
    """Exibe visão de inteligência de mercado por carta."""
    insights = analyze_all_cards(results)

    if not insights:
        console.print("[yellow]Nenhum dado para análise de mercado.[/yellow]")
        return

    console.print(
        Panel(
            "[bold]Visão de inteligência de mercado[/bold]\n"
            "Resumo por carta com preços, sinais de demanda/oferta e recomendação.",
            border_style="blue",
        )
    )

    table = Table(show_lines=True, title="📈 Radar por Carta")
    table.add_column("Carta", style="bold", width=12)
    table.add_column("Preço mín.", justify="right", width=11)
    table.add_column("Preço máx.", justify="right", width=11)
    table.add_column("Preço méd.", justify="right", width=11)
    table.add_column("Anúncios", justify="center", width=8)
    table.add_column("Compra", justify="center", width=7)
    table.add_column("Venda", justify="center", width=6)
    table.add_column("Demanda", justify="center", width=8)
    table.add_column("Fonte", width=14)
    table.add_column("Recomendação", width=20)

    for insight in insights:
        demand_style = (
            "green" if insight.demand_score_avg >= 70
            else "yellow" if insight.demand_score_avg >= 40
            else "dim"
        )
        rec_style = recommendation_style(insight.recommendation)
        table.add_row(
            insight.card_name,
            _format_price(insight.min_price),
            _format_price(insight.max_price),
            _format_price(insight.avg_price),
            str(insight.listing_count),
            str(insight.buy_signals),
            str(insight.sell_signals),
            f"[{demand_style}]{insight.demand_score_avg:.0f}[/{demand_style}]",
            insight.main_source,
            f"[{rec_style}]{insight.recommendation}[/{rec_style}]",
        )

    console.print(table)
    console.print()


def display_top_signals(results: list, top_n: int = 10) -> None:
    """Exibe os melhores sinais individuais por score."""
    if not results:
        return

    sorted_results = sorted(results, key=lambda r: r.intent_score, reverse=True)[:top_n]

    table = Table(show_lines=True, title="🎯 Melhores Sinais Individuais")
    table.add_column("Score", width=6)
    table.add_column("Intenção", width=16)
    table.add_column("Carta", width=12)
    table.add_column("Fonte", width=14)
    table.add_column("Título / Trecho", width=42)
    table.add_column("URL", width=28, overflow="fold")

    for r in sorted_results:
        score_style = (
            "green" if r.intent_score >= 70
            else "yellow" if r.intent_score >= 40
            else "dim"
        )
        snippet = (r.title or r.text_snippet)[:60]
        table.add_row(
            f"[{score_style}]{r.intent_score}[/{score_style}]",
            r.intent_type.value,
            r.normalized_card_name,
            r.source,
            snippet,
            r.url[:80],
        )

    console.print(table)


@app.command()
def search(
    cards: Path = typer.Option(
        DEFAULT_CARDS,
        "--cards",
        "-c",
        help="Arquivo YAML com lista de cartas.",
    ),
    sources: Path = typer.Option(
        DEFAULT_SOURCES,
        "--sources",
        "-s",
        help="Arquivo YAML com fontes habilitadas.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Limite de resultados por carta por fonte.",
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Usar dados simulados (útil para testes offline).",
    ),
    fallback_mock: bool = typer.Option(
        True,
        "--fallback-mock/--no-fallback-mock",
        help="Se APIs falharem, usar dados simulados automaticamente.",
    ),
) -> None:
    """Executa busca nas fontes públicas configuradas."""
    console.print("[bold blue]🔍 Radar Pokémon Brasil — Iniciando busca...[/bold blue]\n")

    card_list = load_cards(cards)
    if not card_list:
        console.print(f"[red]Nenhuma carta encontrada em {cards}[/red]")
        raise typer.Exit(1)

    sources_cfg = load_sources_config(sources)
    all_results = []

    reddit_cfg = sources_cfg.get("reddit", {})
    if reddit_cfg.get("enabled", True):
        console.print("[cyan]→ Reddit[/cyan]")
        if mock:
            for card in card_list:
                all_results.extend(reddit_mock(card))
        else:
            connector = RedditConnector(
                subreddits=reddit_cfg.get("subreddits"),
                query_suffix=reddit_cfg.get("query_suffix", "pokemon card"),
            )
            results = connector.search_cards(card_list, limit_per_card=limit)
            if not results:
                console.print(
                    "[yellow]  Reddit sem resultados (possível bloqueio). "
                    "Tente --mock ou verifique REDDIT_USER_AGENT.[/yellow]"
                )
            all_results.extend(results)

    ml_cfg = sources_cfg.get("mercado_livre", {})
    if ml_cfg.get("enabled", True):
        console.print("[cyan]→ Mercado Livre[/cyan]")
        if mock:
            for card in card_list:
                all_results.extend(ml_mock(card))
        else:
            connector = MercadoLivreConnector(
                site_id=ml_cfg.get("site_id", "MLB"),
                category=ml_cfg.get("category", ""),
            )
            results = connector.search_cards(card_list, limit_per_card=limit)
            all_results.extend(results)

    yt_cfg = sources_cfg.get("youtube", {})
    if yt_cfg.get("enabled", False):
        console.print("[cyan]→ YouTube[/cyan]")
        connector = YouTubeConnector(
            max_comments_per_video=yt_cfg.get("max_comments_per_video", 20),
        )
        if connector.is_available():
            all_results.extend(connector.search_cards(card_list, limit_per_card=limit))
        else:
            console.print(
                "[yellow]  YouTube desabilitado: configure YOUTUBE_API_KEY no .env[/yellow]"
            )

    discord_cfg = sources_cfg.get("discord", {})
    if discord_cfg.get("enabled", False):
        console.print("[cyan]→ Discord (placeholder)[/cyan]")
        DiscordPlaceholderConnector().search_cards(card_list)

    if not all_results and fallback_mock and not mock:
        console.print(
            "[yellow]⚠ APIs retornaram vazio (possível bloqueio de IP). "
            "Usando dados simulados como fallback...[/yellow]"
        )
        for card in card_list:
            all_results.extend(reddit_mock(card))
            all_results.extend(ml_mock(card))

    if not all_results:
        console.print(
            "[red]Nenhum resultado coletado. Tente --mock ou verifique sua conexão.[/red]"
        )
        raise typer.Exit(1)

    saved = save_results(all_results, DEFAULT_DB)
    console.print(f"\n[green]✓ {saved} resultados salvos em {DEFAULT_DB}[/green]")

    csv_path = export_to_csv(DEFAULT_CSV, DEFAULT_DB)
    console.print(f"[green]✓ CSV exportado para {csv_path}[/green]\n")

    display_market_intelligence(all_results)
    console.print()
    display_top_signals(all_results, top_n=10)


@app.command()
def report(
    top: int = typer.Option(10, "--top", "-n", help="Melhores sinais individuais a exibir."),
) -> None:
    """Exibe relatório de inteligência de mercado dos resultados salvos."""
    if not DEFAULT_DB.exists():
        console.print(
            "[yellow]Nenhum dado salvo ainda.\n\n"
            "Execute primeiro:\n"
            "  python3 -m src search --mock --limit 5\n\n"
            "Ou, se preferir, use o atalho:\n"
            "  ./radar.sh search --mock --limit 5[/yellow]"
        )
        raise typer.Exit(0)

    stats = count_results(DEFAULT_DB)
    results = fetch_all(DEFAULT_DB)

    if stats["total"] == 0:
        console.print("[yellow]Banco vazio. Execute uma busca primeiro.[/yellow]")
        raise typer.Exit(0)

    console.print("[bold blue]📊 Relatório — Radar Pokémon Brasil[/bold blue]\n")
    console.print(f"Total de sinais coletados: [bold]{stats['total']}[/bold]")
    console.print(f"Score médio geral: [bold]{stats['avg_score']}[/bold]\n")

    summary = Table(show_header=False, box=None)
    summary.add_column("Métrica")
    summary.add_column("Valor", justify="right")
    for intent, count in sorted(stats["by_intent"].items()):
        summary.add_row(f"  {intent}", str(count))
    console.print("[dim]Distribuição por intenção:[/dim]")
    console.print(summary)
    console.print()

    display_market_intelligence(results)
    console.print()
    display_top_signals(results, top_n=top)


@app.command(name="export")
def export_cmd(
    output: Path = typer.Option(
        DEFAULT_CSV,
        "--output",
        "-o",
        help="Caminho do arquivo CSV de saída.",
    ),
) -> None:
    """Exporta resultados do SQLite para CSV."""
    if not DEFAULT_DB.exists():
        console.print("[red]Banco de dados não encontrado. Execute search primeiro.[/red]")
        raise typer.Exit(1)

    path = export_to_csv(output, DEFAULT_DB)
    count = len(fetch_all(DEFAULT_DB))
    console.print(f"[green]✓ {count} resultados exportados para {path}[/green]")


def main() -> None:
    """Ponto de entrada da CLI."""
    app()


if __name__ == "__main__":
    main()
