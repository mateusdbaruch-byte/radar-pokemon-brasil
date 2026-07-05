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

from src.connector_health import fetch_latest_by_source, save_health_check, save_search_run_log
from src.connectors.discord_placeholder import DiscordPlaceholderConnector
from src.connectors.mercado_livre import MercadoLivreConnector, diagnose_search as diagnose_ml
from src.connectors.mercado_livre import get_mock_results as ml_mock
from src.connectors.reddit import RedditConnector, diagnose_search as diagnose_reddit
from src.connectors.reddit import get_mock_results as reddit_mock
from src.connectors.youtube import YouTubeConnector
from src.database import count_by_data_mode, fetch_all, reset_all_data, save_results
from src.doctor import run_doctor
from src.exporters import export_to_csv
from src.health_adapters import mercado_livre_to_health, reddit_to_health
from src.models import DataMode, tag_results
from src.paths import DEFAULT_CARDS, DEFAULT_CSV, DEFAULT_DB, DEFAULT_SOURCES, PROJECT_ROOT
from src.reporting import display_market_report
from src.search_modes import SearchMode, resolve_search_mode

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
    if not path.exists():
        console.print(f"[red]Arquivo não encontrado: {path}[/red]")
        raise typer.Exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_cards(cards_path: Path) -> list[str]:
    return load_yaml(cards_path).get("cards", [])


def load_sources_config(sources_path: Path) -> dict:
    return load_yaml(sources_path).get("sources", {})


def _print_source_error(source_name: str, hint: str) -> None:
    console.print(
        Panel(
            f"[yellow]A fonte [bold]{source_name}[/bold] não retornou dados reais.[/yellow]\n\n"
            f"[dim]{hint}[/dim]",
            border_style="yellow",
            title=f"⚠ {source_name}",
        )
    )


@app.command()
def search(
    cards: Path = typer.Option(DEFAULT_CARDS, "--cards", "-c"),
    sources: Path = typer.Option(DEFAULT_SOURCES, "--sources", "-s"),
    limit: int = typer.Option(20, "--limit", "-l"),
    live_only: bool = typer.Option(False, "--live-only", help="Apenas dados reais; sem mock."),
    allow_mock: bool = typer.Option(False, "--allow-mock", help="Permite fallback mock (padrão)."),
    mock_only: bool = typer.Option(False, "--mock-only", help="Apenas dados simulados."),
) -> None:
    """Executa busca nas fontes públicas configuradas."""
    try:
        mode = resolve_search_mode(live_only, allow_mock, mock_only)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(
        f"[bold blue]🔍 Radar Pokémon Brasil — busca ({mode.value})[/bold blue]\n"
    )

    card_list = load_cards(cards)
    if not card_list:
        console.print(f"[red]Nenhuma carta em {cards}[/red]")
        raise typer.Exit(1)

    sources_cfg = load_sources_config(sources)
    all_results: list = []
    source_errors = 0

    reddit_cfg = sources_cfg.get("reddit", {})
    if reddit_cfg.get("enabled", True):
        console.print("[cyan]→ Reddit[/cyan]")
        if mode == SearchMode.MOCK_ONLY:
            for card in card_list:
                all_results.extend(reddit_mock(card))
        else:
            connector = RedditConnector(
                subreddits=reddit_cfg.get("subreddits"),
                query_suffix=reddit_cfg.get("query_suffix", "pokemon card"),
            )
            mode_label = "OAuth" if connector.uses_oauth else "público"
            console.print(f"[dim]  Modo Reddit: {mode_label}[/dim]")
            results = tag_results(
                connector.search_cards(card_list, limit_per_card=limit),
                DataMode.LIVE,
            )
            if results:
                all_results.extend(results)
            elif mode == SearchMode.LIVE_ONLY:
                source_errors += 1
                _print_source_error("Reddit", "Configure REDDIT_USER_AGENT ou OAuth no .env")
            elif mode == SearchMode.ALLOW_MOCK:
                console.print("[yellow]  Reddit vazio — fallback mock[/yellow]")
                for card in card_list:
                    all_results.extend(reddit_mock(card))

    ml_cfg = sources_cfg.get("mercado_livre", {})
    if ml_cfg.get("enabled", True):
        console.print("[cyan]→ Mercado Livre[/cyan]")
        if mode == SearchMode.MOCK_ONLY:
            for card in card_list:
                all_results.extend(ml_mock(card))
        else:
            connector = MercadoLivreConnector(
                site_id=ml_cfg.get("site_id", "MLB"),
                category=ml_cfg.get("category", ""),
            )
            results = tag_results(
                connector.search_cards(card_list, limit_per_card=limit),
                DataMode.LIVE,
            )
            if results:
                all_results.extend(results)
            elif mode == SearchMode.LIVE_ONLY:
                source_errors += 1
                _print_source_error(
                    "Mercado Livre",
                    "Rode test-mercadolivre ou doctor; teste em rede residencial.",
                )
            elif mode == SearchMode.ALLOW_MOCK:
                console.print("[yellow]  Mercado Livre vazio — fallback mock[/yellow]")
                for card in card_list:
                    all_results.extend(ml_mock(card))

    if sources_cfg.get("youtube", {}).get("enabled", False) and mode != SearchMode.MOCK_ONLY:
        console.print("[cyan]→ YouTube[/cyan]")
        connector = YouTubeConnector(
            max_comments_per_video=sources_cfg["youtube"].get("max_comments_per_video", 20),
        )
        if connector.is_available():
            all_results.extend(
                tag_results(connector.search_cards(card_list, limit_per_card=limit), DataMode.LIVE)
            )
        else:
            console.print("[yellow]  YouTube: configure YOUTUBE_API_KEY[/yellow]")
            if mode == SearchMode.LIVE_ONLY:
                source_errors += 1

    if not all_results:
        console.print(
            Panel(
                "[red]Nenhum resultado coletado.[/red]\n\n"
                "  • [bold]doctor[/bold] — diagnóstico geral\n"
                "  • [bold]search --mock-only[/bold] — demonstração\n"
                "  • [bold]search --live-only[/bold] — validação real",
                border_style="red",
                title="Busca sem resultados",
            )
        )
        save_search_run_log(mode.value, 0, 0, 0, source_errors)
        raise typer.Exit(1)

    mode_counts = count_by_data_mode(all_results)
    saved = save_results(all_results, DEFAULT_DB)
    save_search_run_log(
        mode.value,
        mode_counts["live"],
        mode_counts["mock"],
        mode_counts["manual_import"],
        source_errors,
    )

    console.print(f"\n[green]✓ {saved} resultados salvos[/green]")
    console.print(
        f"[dim]  live: {mode_counts['live']} | mock: {mode_counts['mock']} | "
        f"manual: {mode_counts['manual_import']} | erros de fonte: {source_errors}[/dim]"
    )
    export_to_csv(DEFAULT_CSV, DEFAULT_DB)
    console.print(f"[green]✓ CSV atualizado: {DEFAULT_CSV}[/green]\n")
    display_market_report(console, all_results, monitored_cards=card_list, top_signals=5)


@app.command()
def report(
    cards: Path = typer.Option(DEFAULT_CARDS, "--cards", "-c"),
    top: int = typer.Option(5, "--top", "-n"),
) -> None:
    """Relatório de inteligência de mercado."""
    if not DEFAULT_DB.exists() or not fetch_all(DEFAULT_DB):
        console.print("[yellow]Sem dados. Rode search ou doctor primeiro.[/yellow]")
        raise typer.Exit(0)
    console.print("[bold blue]📊 Relatório — Radar Pokémon Brasil[/bold blue]\n")
    display_market_report(console, fetch_all(DEFAULT_DB), load_cards(cards), top_signals=top)


@app.command(name="export")
def export_cmd(output: Path = typer.Option(DEFAULT_CSV, "--output", "-o")) -> None:
    if not DEFAULT_DB.exists():
        console.print("[red]Execute search primeiro.[/red]")
        raise typer.Exit(1)
    path = export_to_csv(output, DEFAULT_DB)
    console.print(f"[green]✓ {len(fetch_all(DEFAULT_DB))} linhas → {path}[/green]")


@app.command("reset-db")
def reset_db(force: bool = typer.Option(False, "--force", "-y")) -> None:
    if not force:
        console.print(f"[yellow]Apagar {DEFAULT_DB} e {DEFAULT_CSV}?[/yellow]")
        if not typer.confirm("Continuar?"):
            raise typer.Exit(0)
    reset_all_data(DEFAULT_DB, DEFAULT_CSV)
    console.print("[green]✓ Banco e CSV resetados.[/green]")


@app.command()
def doctor() -> None:
    """Diagnóstico geral: conectores, banco, CSV, .env e configs."""
    run_doctor(console, persist=True)


@app.command("source-status")
def source_status() -> None:
    """Último status conhecido de cada conector (connector_health)."""
    rows = fetch_latest_by_source()
    if not rows:
        console.print("[yellow]Sem histórico. Rode [bold]doctor[/bold] primeiro.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="📡 Status dos conectores", show_lines=True)
    table.add_column("Fonte")
    table.add_column("Status")
    table.add_column("data_mode")
    table.add_column("HTTP")
    table.add_column("Testado em")
    table.add_column("Mensagem", max_width=30)
    table.add_column("Próxima ação", max_width=28)

    for row in rows:
        st = row["status"]
        style = {"OK": "green", "WARNING": "yellow", "ERROR": "red"}.get(st, "white")
        table.add_row(
            row["source"],
            f"[{style}]{st}[/{style}]",
            row["data_mode"],
            str(row["http_status"] or "—"),
            (row["tested_at"] or "")[:19],
            (row["message"] or "")[:60],
            (row.get("next_action") or "")[:60],
        )
    console.print(table)


@app.command("test-mercadolivre")
def test_mercadolivre(
    query: str = typer.Option("carta pokemon charizard", "--query", "-q"),
    site_id: str = typer.Option("MLB", "--site-id"),
) -> None:
    console.print("[bold blue]🔧 Diagnóstico — Mercado Livre[/bold blue]\n")
    diag = diagnose_ml(query=query, site_id=site_id)
    health = mercado_livre_to_health(diag)
    save_health_check(health)

    console.print(f"[bold]URL:[/bold]\n{diag.url}\n")
    console.print(f"[bold]Status:[/bold] {diag.status_code}")
    console.print(f"[bold]Forbidden:[/bold] {'sim' if diag.is_forbidden else 'não'}")
    console.print(f"[dim]{diag.response_preview[:500]}[/dim]\n")
    for tip in diag.suggestions:
        console.print(f"  • {tip}")
    console.print("\n[dim]Salvo em connector_health (não grava radar_results).[/dim]")


@app.command("test-reddit")
def test_reddit(
    query: str = typer.Option("pokemon tcg brasil charizard", "--query", "-q"),
    subreddit: str = typer.Option("", "--subreddit", "-r"),
) -> None:
    console.print("[bold blue]🔧 Diagnóstico — Reddit[/bold blue]\n")
    diag = diagnose_reddit(query=query, subreddit=subreddit.strip() or None)
    health = reddit_to_health(diag)
    save_health_check(health)

    console.print(f"[bold]Método:[/bold] {diag.method} | [bold]Modo:[/bold] {diag.auth_mode}")
    console.print(f"[bold]URL:[/bold]\n{diag.url}\n")
    console.print(f"[bold]Status:[/bold] {diag.status_code}")
    console.print(f"[bold]OAuth necessário?[/bold] {'sim' if diag.needs_oauth else 'não'}")
    console.print(f"[dim]{diag.oauth_message}[/dim]")
    console.print(f"[dim]{diag.response_preview[:500]}[/dim]\n")
    for tip in diag.suggestions:
        console.print(f"  • {tip}")
    console.print("\n[dim]Salvo em connector_health (não grava radar_results).[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
