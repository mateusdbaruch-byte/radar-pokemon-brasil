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

from src.connectors.discord_placeholder import DiscordPlaceholderConnector
from src.connectors.mercado_livre import MercadoLivreConnector, diagnose_search, get_mock_results as ml_mock
from src.connectors.reddit import RedditConnector, diagnose_search as diagnose_reddit, get_mock_results as reddit_mock
from src.connectors.youtube import YouTubeConnector
from src.database import count_by_data_mode, fetch_all, reset_all_data, save_results
from src.exporters import export_to_csv
from src.models import DataMode
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


def _print_source_error(source_name: str, hint: str) -> None:
    """Mensagem amigável quando uma fonte falha em modo --no-mock."""
    console.print(
        Panel(
            f"[yellow]A fonte [bold]{source_name}[/bold] não retornou dados.[/yellow]\n\n"
            f"Possíveis causas:\n"
            f"  • Bloqueio temporário da API (HTTP 403/429)\n"
            f"  • Problema de conexão com a internet\n"
            f"  • Configuração incompleta\n\n"
            f"[dim]{hint}[/dim]",
            border_style="yellow",
            title=f"⚠ {source_name}",
        )
    )


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
        help="Usar apenas dados simulados (data_mode=mock).",
    ),
    no_mock: bool = typer.Option(
        False,
        "--no-mock",
        help="Apenas dados reais; sem fallback simulado se APIs falharem.",
    ),
) -> None:
    """Executa busca nas fontes públicas configuradas."""
    if mock and no_mock:
        console.print("[red]Use apenas --mock OU --no-mock, não ambos.[/red]")
        raise typer.Exit(1)

    mode_label = "mock" if mock else "live (sem fallback)" if no_mock else "live"
    console.print(
        f"[bold blue]🔍 Radar Pokémon Brasil — Iniciando busca ({mode_label})...[/bold blue]\n"
    )

    card_list = load_cards(cards)
    if not card_list:
        console.print(f"[red]Nenhuma carta encontrada em {cards}[/red]")
        raise typer.Exit(1)

    sources_cfg = load_sources_config(sources)
    all_results: list = []
    allow_fallback = not mock and not no_mock

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
            if results:
                all_results.extend(results)
            elif no_mock:
                _print_source_error(
                    "Reddit",
                    "Configure REDDIT_USER_AGENT no .env ou tente de outra rede.",
                )
            elif allow_fallback:
                console.print("[yellow]  Reddit vazio — usando fallback mock...[/yellow]")
                for card in card_list:
                    all_results.extend(reddit_mock(card))

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
            if results:
                all_results.extend(results)
            elif no_mock:
                _print_source_error(
                    "Mercado Livre",
                    "Tente de rede residencial; APIs podem bloquear IPs de datacenter.",
                )
            elif allow_fallback:
                console.print("[yellow]  Mercado Livre vazio — usando fallback mock...[/yellow]")
                for card in card_list:
                    all_results.extend(ml_mock(card))

    yt_cfg = sources_cfg.get("youtube", {})
    if yt_cfg.get("enabled", False) and not mock:
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

    if not all_results:
        console.print(
            Panel(
                "[red]Nenhum resultado coletado.[/red]\n\n"
                "Opções:\n"
                "  • [bold]python3 -m src.main search --mock[/bold] — testar com dados simulados\n"
                "  • Verifique internet e .env\n"
                "  • Rode sem --no-mock para permitir fallback automático",
                border_style="red",
                title="Busca sem resultados",
            )
        )
        raise typer.Exit(1)

    mode_counts = count_by_data_mode(all_results)
    saved = save_results(all_results, DEFAULT_DB)
    console.print(f"\n[green]✓ {saved} resultados salvos em {DEFAULT_DB}[/green]")
    console.print(
        f"[dim]  live: {mode_counts['live']} | "
        f"mock: {mode_counts['mock']} | "
        f"manual_import: {mode_counts['manual_import']}[/dim]"
    )

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
            "  python3 -m src.main search --mock --limit 5[/yellow]"
        )
        raise typer.Exit(0)

    results = fetch_all(DEFAULT_DB)
    if not results:
        console.print("[yellow]Banco vazio. Execute uma busca primeiro.[/yellow]")
        raise typer.Exit(0)

    card_list = load_cards(cards)
    console.print(
        "[bold blue]📊 Relatório de Inteligência de Mercado — Radar Pokémon Brasil[/bold blue]\n"
    )
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


@app.command("reset-db")
def reset_db(
    force: bool = typer.Option(
        False,
        "--force",
        "-y",
        help="Apaga sem pedir confirmação.",
    ),
) -> None:
    """Apaga todos os dados de data/radar.db e data/radar_results.csv."""
    if not force:
        console.print(
            "[yellow]Isso vai apagar TODOS os resultados salvos em:[/yellow]\n"
            f"  • {DEFAULT_DB}\n"
            f"  • {DEFAULT_CSV}\n"
        )
        confirmed = typer.confirm("Deseja continuar?")
        if not confirmed:
            console.print("[dim]Operação cancelada.[/dim]")
            raise typer.Exit(0)

    reset_all_data(DEFAULT_DB, DEFAULT_CSV)
    console.print("[green]✓ Banco e CSV resetados com sucesso.[/green]")


@app.command("test-mercadolivre")
def test_mercadolivre(
    query: str = typer.Option(
        "carta pokemon charizard",
        "--query",
        "-q",
        help="Termo de busca para testar na API do Mercado Livre.",
    ),
    site_id: str = typer.Option(
        "MLB",
        "--site-id",
        help="Site do Mercado Livre (MLB = Brasil).",
    ),
) -> None:
    """
    Diagnostica o conector do Mercado Livre sem salvar no banco.

    Útil para validar se a API está acessível neste ambiente/rede.
    """
    console.print(
        "[bold blue]🔧 Diagnóstico — Mercado Livre[/bold blue]\n"
        "[dim]Nenhum dado será salvo no banco.[/dim]\n"
    )

    result = diagnose_search(query=query, site_id=site_id)

    console.print(f"[bold]URL:[/bold]\n{result.url}\n")
    status = result.status_code if result.status_code is not None else "—"
    status_style = "green" if result.status_code == 200 else "red"
    console.print(f"[bold]Status HTTP:[/bold] [{status_style}]{status}[/{status_style}]\n")

    if result.error_message:
        console.print(f"[bold red]Erro de rede:[/bold red] {result.error_message}\n")

    preview = result.response_preview or "(resposta vazia)"
    console.print(f"[bold]Primeiros 500 caracteres da resposta:[/bold]\n[dim]{preview}[/dim]\n")

    json_label = "[green]sim[/green]" if result.is_valid_json else "[red]não[/red]"
    console.print(f"[bold]JSON válido?[/bold] {json_label}")

    if result.json_top_level_keys:
        console.print(f"[bold]Chaves do JSON:[/bold] {', '.join(result.json_top_level_keys)}")
    if result.results_count is not None:
        console.print(f"[bold]Anúncios na resposta:[/bold] {result.results_count}")

    if result.suggestions:
        console.print("\n[bold]Possíveis causas / próximos passos:[/bold]")
        for tip in result.suggestions:
            console.print(f"  • {tip}")

    console.print(
        Panel(
            "Diagnóstico concluído. Nada foi gravado em data/radar.db.",
            border_style="blue",
            title="ℹ️ Apenas teste",
        )
    )


@app.command("test-reddit")
def test_reddit(
    query: str = typer.Option(
        "pokemon tcg brasil charizard",
        "--query",
        "-q",
        help="Termo de busca para testar no Reddit.",
    ),
    subreddit: str = typer.Option(
        "",
        "--subreddit",
        "-r",
        help="Subreddit opcional (ex.: PokemonTCG). Vazio = busca global.",
    ),
) -> None:
    """
    Diagnostica o conector do Reddit sem salvar no banco.

    Testa o endpoint JSON público (GET) usado pelo MVP.
    """
    console.print(
        "[bold blue]🔧 Diagnóstico — Reddit[/bold blue]\n"
        "[dim]Nenhum dado será salvo no banco.[/dim]\n"
    )

    sub = subreddit.strip() or None
    result = diagnose_reddit(query=query, subreddit=sub)

    console.print(f"[bold]Método:[/bold] {result.method}")
    console.print(f"[bold]URL:[/bold]\n{result.url}\n")
    console.print(f"[bold]User-Agent:[/bold] [dim]{result.user_agent}[/dim]\n")

    status = result.status_code if result.status_code is not None else "—"
    status_style = "green" if result.status_code == 200 else "red"
    console.print(f"[bold]Status HTTP:[/bold] [{status_style}]{status}[/{status_style}]\n")

    if result.error_message:
        console.print(f"[bold red]Erro de rede:[/bold red] {result.error_message}\n")

    preview = result.response_preview or "(resposta vazia)"
    console.print(f"[bold]Primeiros 500 caracteres da resposta:[/bold]\n[dim]{preview}[/dim]\n")

    json_label = "[green]sim[/green]" if result.is_valid_json else "[red]não[/red]"
    console.print(f"[bold]JSON válido?[/bold] {json_label}")
    if result.posts_count is not None:
        console.print(f"[bold]Posts na resposta:[/bold] {result.posts_count}")

    oauth_label = "[yellow]sim[/yellow]" if result.needs_oauth else "[green]não[/green]"
    console.print(f"\n[bold]Precisa configurar API/OAuth?[/bold] {oauth_label}")
    console.print(f"[dim]{result.oauth_message}[/dim]")

    if result.suggestions:
        console.print("\n[bold]Possíveis causas / próximos passos:[/bold]")
        for tip in result.suggestions:
            console.print(f"  • {tip}")

    console.print(
        Panel(
            "Diagnóstico concluído. Nada foi gravado em data/radar.db.",
            border_style="blue",
            title="ℹ️ Apenas teste",
        )
    )


def main() -> None:
    """Ponto de entrada da CLI."""
    app()


if __name__ == "__main__":
    main()
