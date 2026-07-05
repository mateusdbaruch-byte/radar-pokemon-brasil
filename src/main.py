"""CLI principal do Radar Pokémon Brasil."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler

from src.connectors.discord_placeholder import DiscordPlaceholderConnector
from src.connectors.mercado_livre import MercadoLivreConnector, get_mock_results as ml_mock
from src.connectors.reddit import RedditConnector, get_mock_results as reddit_mock
from src.connectors.youtube import YouTubeConnector
from src.database import count_results, fetch_all, save_results
from src.exporters import export_to_csv
from src.paths import DEFAULT_CARDS, DEFAULT_CSV, DEFAULT_DB, DEFAULT_SOURCES, PROJECT_ROOT
from src.reporting import display_market_report

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

    display_market_report(console, all_results, monitored_cards=card_list, top_signals=5)


@app.command()
def report(
    cards: Path = typer.Option(
        DEFAULT_CARDS,
        "--cards",
        "-c",
        help="Arquivo YAML com cartas monitoradas (para incluir cartas sem dados).",
    ),
    top: int = typer.Option(
        5,
        "--top",
        "-n",
        help="Quantidade de sinais individuais no detalhe final.",
    ),
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

    results = fetch_all(DEFAULT_DB)
    if not results:
        console.print("[yellow]Banco vazio. Execute uma busca primeiro.[/yellow]")
        raise typer.Exit(0)

    card_list = load_cards(cards)
    console.print("[bold blue]📊 Relatório de Inteligência de Mercado — Radar Pokémon Brasil[/bold blue]\n")
    display_market_report(console, results, monitored_cards=card_list, top_signals=top)


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
