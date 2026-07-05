"""CLI principal do Radar Pokémon Brasil."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.connectors.discord_placeholder import DiscordPlaceholderConnector
from src.connectors.mercado_livre import MercadoLivreConnector, get_mock_results as ml_mock
from src.connectors.reddit import RedditConnector, get_mock_results as reddit_mock
from src.connectors.youtube import YouTubeConnector
from src.database import count_results, fetch_all, save_results
from src.exporters import export_to_csv

# Carrega variáveis de ambiente do .env se existir
load_dotenv()

app = typer.Typer(
    name="radar-pokemon-brasil",
    help="MVP de inteligência de demanda para cartas Pokémon TCG no Brasil.",
)
console = Console()

# Configura logging com rich
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_path=False)],
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CARDS = PROJECT_ROOT / "config" / "cards.yml"
DEFAULT_SOURCES = PROJECT_ROOT / "config" / "sources.yml"
DEFAULT_DB = PROJECT_ROOT / "data" / "radar.db"
DEFAULT_CSV = PROJECT_ROOT / "data" / "radar_results.csv"


def load_yaml(path: Path) -> dict:
    """Carrega arquivo YAML de configuração."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_cards(cards_path: Path) -> list[str]:
    """Carrega lista de cartas do YAML."""
    data = load_yaml(cards_path)
    return data.get("cards", [])


def load_sources_config(sources_path: Path) -> dict:
    """Carrega configuração de fontes."""
    return load_yaml(sources_path).get("sources", {})


def display_results_table(results: list, top_n: int = 15) -> None:
    """Exibe tabela rich com os melhores resultados por score."""
    if not results:
        console.print("[yellow]Nenhum resultado encontrado.[/yellow]")
        return

    sorted_results = sorted(results, key=lambda r: r.intent_score, reverse=True)[:top_n]

    table = Table(title="🎯 Radar Pokémon Brasil — Melhores Sinais", show_lines=True)
    table.add_column("Score", style="bold green", width=6)
    table.add_column("Intenção", width=16)
    table.add_column("Carta", width=12)
    table.add_column("Fonte", width=14)
    table.add_column("Título / Trecho", width=40)
    table.add_column("URL", width=30, overflow="fold")

    for r in sorted_results:
        score_style = "green" if r.intent_score >= 70 else "yellow" if r.intent_score >= 40 else "dim"
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
        console.print("[red]Nenhuma carta encontrada em {cards}[/red]")
        raise typer.Exit(1)

    sources_cfg = load_sources_config(sources)
    all_results = []

    # --- Reddit ---
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

    # --- Mercado Livre ---
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

    # --- YouTube (opcional) ---
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

    # --- Discord (placeholder) ---
    discord_cfg = sources_cfg.get("discord", {})
    if discord_cfg.get("enabled", False):
        console.print("[cyan]→ Discord (placeholder)[/cyan]")
        DiscordPlaceholderConnector().search_cards(card_list)

    # Fallback para mock quando APIs estão bloqueadas (ex.: IP de datacenter)
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

    # Salva no banco
    saved = save_results(all_results, DEFAULT_DB)
    console.print(f"\n[green]✓ {saved} resultados salvos em {DEFAULT_DB}[/green]")

    # Exporta CSV automaticamente
    csv_path = export_to_csv(DEFAULT_CSV, DEFAULT_DB)
    console.print(f"[green]✓ CSV exportado para {csv_path}[/green]\n")

    # Exibe tabela
    display_results_table(all_results)


@app.command()
def report(
    top: int = typer.Option(15, "--top", "-n", help="Quantidade de resultados no topo."),
) -> None:
    """Exibe relatório resumido dos resultados salvos."""
    stats = count_results(DEFAULT_DB)

    if stats["total"] == 0:
        console.print(
            "[yellow]Nenhum dado salvo. Execute primeiro: "
            "python -m src.main search[/yellow]"
        )
        raise typer.Exit(0)

    console.print("[bold blue]📊 Relatório Radar Pokémon Brasil[/bold blue]\n")
    console.print(f"Total de resultados: [bold]{stats['total']}[/bold]")
    console.print(f"Score médio: [bold]{stats['avg_score']}[/bold]\n")

    # Tabela por intenção
    intent_table = Table(title="Por tipo de intenção")
    intent_table.add_column("Tipo", style="cyan")
    intent_table.add_column("Quantidade", justify="right")
    for intent, count in sorted(stats["by_intent"].items()):
        intent_table.add_row(intent, str(count))
    console.print(intent_table)
    console.print()

    # Tabela por fonte
    source_table = Table(title="Por fonte")
    source_table.add_column("Fonte", style="cyan")
    source_table.add_column("Quantidade", justify="right")
    for source, count in sorted(stats["by_source"].items()):
        source_table.add_row(source, str(count))
    console.print(source_table)
    console.print()

    # Melhores resultados
    results = fetch_all(DEFAULT_DB, limit=top)
    display_results_table(results, top_n=top)


@app.command()
def export(
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
    """Ponto de entrada para python -m src.main."""
    app()


if __name__ == "__main__":
    main()
