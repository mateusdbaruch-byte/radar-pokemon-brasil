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

from src.connector_health import (
    ConnectorDataMode,
    HealthCheckResult,
    HealthStatus,
    fetch_latest_by_source,
    save_health_check,
    save_search_run_log,
)
from src.connectors.mercado_livre import MercadoLivreConnector, diagnose_search as diagnose_ml
from src.connectors.mercado_livre import get_mock_results as ml_mock
from src.connectors.reddit import RedditConnector, diagnose_search as diagnose_reddit
from src.connectors.reddit import get_mock_results as reddit_mock
from src.connectors.reddit import test_reddit_auth_and_search
from src.connectors.youtube import YouTubeConnector
from src.database import count_by_data_mode, fetch_all, reset_all_data, save_results
from src.doctor import run_doctor
from src.exporters import export_to_csv
from src.health_adapters import mercado_livre_to_health, reddit_to_health
from src.manual_import import import_prices_from_csv, validate_import_file
from src.market_snapshot import display_market_snapshot
from src.models import DataMode, RadarResult, tag_results
from src.paths import (
    DEFAULT_CARDS,
    DEFAULT_CSV,
    DEFAULT_DB,
    DEFAULT_SOURCES,
    DEFAULT_WATCHLIST,
    PROJECT_ROOT,
)
from src.opportunity_db import save_opportunities
from src.opportunity_models import WishlistLead
from src.opportunity_reporting import display_opportunity_inbox, display_opportunity_report
from src.opportunity_scanner import scan_opportunities
from src.opportunity_db import save_wishlist_lead
from src.wishlist import import_wishlist_csv, validate_wishlist_csv
from src.reddit_auth import REDDIT_ENV_FIELDS, RedditAuthStatus, inspect_reddit_env
from src.reddit_policy import (
    REDDIT_PENDING_MESSAGE,
    get_reddit_policy_status,
    is_reddit_pending_approval,
)
from src.reporting import display_market_report
from src.search_modes import SearchMode, resolve_search_mode
from src.setup_env import run_setup_env

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

KNOWN_SOURCES = frozenset({"reddit", "mercado_livre", "youtube", "discord"})


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


def parse_source_filter(sources: str | None) -> set[str] | None:
    """Converte 'reddit,mercado_livre' em conjunto de nomes."""
    if not sources or not sources.strip():
        return None
    selected = {s.strip().lower() for s in sources.split(",") if s.strip()}
    unknown = selected - KNOWN_SOURCES
    if unknown:
        console.print(f"[red]Fontes desconhecidas: {', '.join(sorted(unknown))}[/red]")
        console.print(f"[dim]Válidas: {', '.join(sorted(KNOWN_SOURCES))}[/dim]")
        raise typer.Exit(1)
    return selected


def _source_enabled(selected: set[str] | None, name: str) -> bool:
    return selected is None or name in selected


def _print_source_error(source_name: str, hint: str) -> None:
    console.print(
        Panel(
            f"[yellow]A fonte [bold]{source_name}[/bold] não retornou dados reais.[/yellow]\n\n"
            f"[dim]{hint}[/dim]",
            border_style="yellow",
            title=f"⚠ {source_name}",
        )
    )


def _run_reddit_search(
    card_list: list[str],
    sources_cfg: dict,
    limit: int,
    mode: SearchMode,
) -> tuple[list[RadarResult], int]:
    """Executa busca Reddit. Retorna (resultados, erros)."""
    reddit_cfg = sources_cfg.get("reddit", {})
    if not reddit_cfg.get("enabled", True):
        return [], 0

    console.print("[cyan]→ Reddit[/cyan]")
    if mode == SearchMode.MOCK_ONLY:
        results: list[RadarResult] = []
        for card in card_list:
            results.extend(reddit_mock(card))
        return results, 0

    if is_reddit_pending_approval():
        console.print("[yellow]  Fonte desabilitada — PENDING_APPROVAL[/yellow]")
        console.print(f"[dim]  {REDDIT_PENDING_MESSAGE}[/dim]")
        console.print("[dim]  Use import-prices ou Mercado Livre.[/dim]")
        return [], 0

    connector = RedditConnector(
        subreddits=reddit_cfg.get("subreddits"),
        query_suffix=reddit_cfg.get("query_suffix", "pokemon card"),
        require_oauth=(mode == SearchMode.LIVE_ONLY),
    )
    mode_label = "OAuth" if connector.uses_oauth else connector.auth_mode
    console.print(f"[dim]  Modo Reddit: {mode_label}[/dim]")

    if mode == SearchMode.LIVE_ONLY and not connector.auth_ok:
        if connector.auth_result.status == RedditAuthStatus.MISSING_CREDENTIALS:
            console.print("[yellow]  Reddit REQUIRES_AUTH — configure .env[/yellow]")
        else:
            console.print(
                f"[yellow]  Auth: {connector.auth_result.status.value} — "
                f"{connector.auth_result.message}[/yellow]"
            )
        if connector.is_gated:
            console.print(f"[dim]  {REDDIT_PENDING_MESSAGE}[/dim]")
            return [], 0
        _print_source_error("Reddit", "Rode setup-env e reddit-policy-status")
        return [], 0

    results = tag_results(
        connector.search_cards(card_list, limit_per_card=limit),
        DataMode.LIVE,
    )
    if connector.is_gated:
        console.print("[yellow]  Reddit — PENDING_APPROVAL[/yellow]")
        console.print(f"[dim]  {REDDIT_PENDING_MESSAGE}[/dim]")
        return results, 0

    if results:
        return results, 0
    if mode == SearchMode.LIVE_ONLY:
        if is_reddit_pending_approval():
            return [], 0
        _print_source_error("Reddit", "Rode reddit-policy-status para próximos passos")
        return [], 0
    if mode == SearchMode.ALLOW_MOCK:
        console.print("[yellow]  Reddit vazio — fallback mock[/yellow]")
        mock_results: list[RadarResult] = []
        for card in card_list:
            mock_results.extend(reddit_mock(card))
        return mock_results, 0
    return [], 0


def _run_ml_search(
    card_list: list[str],
    sources_cfg: dict,
    limit: int,
    mode: SearchMode,
) -> tuple[list[RadarResult], int]:
    """Executa busca Mercado Livre. Retorna (resultados, erros)."""
    ml_cfg = sources_cfg.get("mercado_livre", {})
    if not ml_cfg.get("enabled", True):
        return [], 0

    console.print("[cyan]→ Mercado Livre[/cyan]")
    if mode == SearchMode.MOCK_ONLY:
        results: list[RadarResult] = []
        for card in card_list:
            results.extend(ml_mock(card))
        return results, 0

    connector = MercadoLivreConnector(
        site_id=ml_cfg.get("site_id", "MLB"),
        category=ml_cfg.get("category", ""),
    )
    results = tag_results(
        connector.search_cards(card_list, limit_per_card=limit),
        DataMode.LIVE,
    )
    if results:
        return results, 0
    if mode == SearchMode.LIVE_ONLY:
        _print_source_error(
            "Mercado Livre",
            "API em diagnóstico (403 comum). Use import-prices ou Reddit.",
        )
        return [], 1
    if mode == SearchMode.ALLOW_MOCK:
        console.print("[yellow]  Mercado Livre vazio — fallback mock[/yellow]")
        mock_results: list[RadarResult] = []
        for card in card_list:
            mock_results.extend(ml_mock(card))
        return mock_results, 0
    return [], 0


@app.command("reddit-policy-status")
def reddit_policy_status() -> None:
    """Status de política/aprovação da API Reddit (fonte gated)."""
    console.print("[bold blue]📋 Reddit — política e aprovação de API[/bold blue]\n")
    status = get_reddit_policy_status()

    table = Table(show_lines=True)
    table.add_column("Verificação")
    table.add_column("Resultado")
    table.add_row(".env existe", "[green]sim[/green]" if status.env_exists else "[red]não[/red]")
    table.add_row(
        "OAuth configurado",
        "[green]sim[/green]" if status.oauth_configured else "[yellow]não[/yellow]",
    )
    table.add_row(
        "REDDIT_USER_AGENT",
        "[green]sim[/green]" if status.user_agent_configured else "[yellow]não[/yellow]",
    )
    table.add_row(
        "Último HTTP",
        str(status.last_http_status) if status.last_http_status is not None else "—",
    )
    table.add_row(
        "Último status",
        status.last_health_status or "—",
    )
    table.add_row(
        "Pending approval",
        "[yellow]sim[/yellow]" if status.pending_approval else "[green]não[/green]",
    )
    table.add_row(
        "Requires auth",
        "[yellow]sim[/yellow]" if status.requires_auth else "[green]não[/green]",
    )
    console.print(table)

    if status.pending_approval:
        console.print()
        console.print(Panel(REDDIT_PENDING_MESSAGE, border_style="yellow", title="Fonte desabilitada"))

    console.print(f"\n[bold]Próxima ação:[/bold] {status.next_action}")
    console.print(
        "\n[dim]Reddit é fonte opcional. Use import-prices (Liga/MYP) e Mercado Livre "
        "para validar o MVP sem Reddit.[/dim]"
    )


def load_watchlist(path: Path) -> list[str]:
    return load_yaml(path).get("cards", [])


@app.command("scan-opportunities")
def scan_opportunities_cmd(
    cards: Path = typer.Option(DEFAULT_WATCHLIST, "--cards", "-c"),
    sources: str = typer.Option(
        "web_search,wishlist",
        "--sources",
        help="Fontes: web_search,wishlist,mercado_livre,...",
    ),
    limit: int = typer.Option(20, "--limit", "-l"),
) -> None:
    """Escaneia oportunidades automatizadas nas fontes disponíveis."""
    card_list = load_watchlist(cards)
    if not card_list:
        console.print(f"[red]Nenhuma carta em {cards}[/red]")
        raise typer.Exit(1)

    console.print(
        f"[bold blue]🎯 Opportunity Radar — scan[/bold blue]\n"
        f"[dim]Cartas: {len(card_list)} | Fontes: {sources}[/dim]\n"
    )

    result = scan_opportunities(card_list, sources, limit=limit)

    for msg in result.messages:
        console.print(f"[dim]  • {msg}[/dim]")
    if result.skipped_sources:
        console.print(
            f"[yellow]Fontes puladas (PENDING_ACCESS/gated): "
            f"{', '.join(result.skipped_sources)}[/yellow]"
        )

    if not result.opportunities:
        console.print(
            Panel(
                "[yellow]Nenhuma oportunidade coletada.[/yellow]\n\n"
                "  • Configure WEB_SEARCH_PROVIDER no .env\n"
                "  • import-wishlist para leads opt-in\n"
                "  • doctor para diagnóstico",
                border_style="yellow",
                title="Scan vazio",
            )
        )
        raise typer.Exit(1)

    saved = save_opportunities(result.opportunities)
    console.print(f"\n[green]✓ {saved} oportunidades salvas[/green]")
    console.print(f"[dim]Fontes live nesta execução: {', '.join(result.live_sources) or '—'}[/dim]\n")

    table = Table(title="Top oportunidades", show_lines=True)
    table.add_column("Carta", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Tipo")
    table.add_column("Fonte")
    table.add_column("Evidência", max_width=40)
    for opp in result.opportunities[:10]:
        table.add_row(
            opp.normalized_card_name,
            str(opp.opportunity_score),
            opp.opportunity_type.value,
            opp.source,
            opp.evidence_text[:40],
        )
    console.print(table)


@app.command("opportunity-inbox")
def opportunity_inbox(
    limit: int = typer.Option(15, "--limit", "-n"),
) -> None:
    """Caixa de entrada de oportunidades."""
    display_opportunity_inbox(console, limit=limit)


@app.command("opportunity-report")
def opportunity_report_cmd() -> None:
    """Relatório consolidado de oportunidades."""
    display_opportunity_report(console)


@app.command("add-wishlist-lead")
def add_wishlist_lead(
    name: str = typer.Option(..., "--name", "-n", prompt="Nome"),
    card_name: str = typer.Option(..., "--card", "-c", prompt="Carta"),
    contact: str = typer.Option("", "--contact"),
    collection: str = typer.Option("", "--collection"),
    language: str = typer.Option("pt-BR", "--language"),
    condition: str = typer.Option("", "--condition"),
    max_price: float = typer.Option(0.0, "--max-price"),
    urgency: str = typer.Option("media", "--urgency"),
    notes: str = typer.Option("", "--notes"),
    source: str = typer.Option("cli", "--source"),
) -> None:
    """Cadastra lead opt-in na lista de desejos."""
    lead = WishlistLead(
        name=name,
        contact=contact,
        card_name=card_name,
        collection=collection,
        language=language,
        condition=condition,
        max_price=max_price if max_price > 0 else None,
        urgency=urgency,
        notes=notes,
        source=source,
    )
    save_wishlist_lead(lead)
    console.print(f"[green]✓ Lead salvo: {name} → {card_name}[/green]")


@app.command("import-wishlist")
def import_wishlist(
    file: Path = typer.Argument(..., help="CSV de wishlist opt-in"),
) -> None:
    """Importa leads da lista de desejos (opt-in)."""
    ok, errors = validate_wishlist_csv(file)
    if not ok:
        console.print("[red]CSV inválido:[/red]")
        for e in errors:
            console.print(f"  • {e}")
        raise typer.Exit(1)
    leads = import_wishlist_csv(file)
    console.print(f"[green]✓ {len(leads)} lead(s) importados[/green]")


@app.command("setup-env")
def setup_env() -> None:
    """Prepara .env a partir de .env.example (edição manual)."""
    run_setup_env(console)


@app.command("test-reddit-auth")
def test_reddit_auth() -> None:
    """Testa OAuth Reddit e busca simples — não salva radar_results."""
    console.print("[bold blue]🔐 Teste de autenticação — Reddit[/bold blue]\n")

    env_status = inspect_reddit_env()
    if not env_status.env_path_exists:
        console.print("[yellow].env não encontrado — rode setup-env primeiro.[/yellow]")
        raise typer.Exit(1)

    table = Table(title="Campos do .env (valores ocultos)")
    table.add_column("Variável")
    table.add_column("Preenchido")
    for field in REDDIT_ENV_FIELDS:
        filled = env_status.fields.get(field, False)
        style = "green" if filled else "red"
        table.add_row(field, f"[{style}]{'sim' if filled else 'não'}[/{style}]")
    console.print(table)
    console.print()

    result = test_reddit_auth_and_search("pokemon tcg brasil", limit=5)
    auth = result.auth_result

    console.print(f"[bold]Modo:[/bold] {auth.auth_mode}")
    console.print(f"[bold]Status auth:[/bold] {auth.status.value}")
    console.print(f"[bold]Mensagem:[/bold] {auth.message}")

    if result.status_code is not None:
        console.print(f"[bold]HTTP busca:[/bold] {result.status_code}")
    console.print(f"[bold]Resultados:[/bold] {len(result.posts)}")

    if result.posts:
        console.print("\n[dim]Primeiros posts:[/dim]")
        for post in result.posts[:3]:
            console.print(f"  • r/{post.get('subreddit', '?')}: {post.get('title', '')[:60]}")

    if auth.status == RedditAuthStatus.LIVE and result.posts:
        console.print("\n[green]✓ Reddit OAuth funcionando — pronto para search-reddit[/green]")
    elif auth.status == RedditAuthStatus.PENDING_APPROVAL or result.status_code == 403:
        console.print(f"\n[yellow]{REDDIT_PENDING_MESSAGE}[/yellow]")
    elif auth.status == RedditAuthStatus.MISSING_CREDENTIALS:
        console.print("\n[yellow]Preencha .env e rode setup-env[/yellow]")
    else:
        console.print("\n[yellow]Autenticação ou busca falhou — verifique .env[/yellow]")

    console.print("\n[dim]Nenhum dado salvo em radar_results.[/dim]")


@app.command("search-reddit")
def search_reddit(
    query: str = typer.Option("pokemon tcg brasil", "--query", "-q"),
    limit: int = typer.Option(10, "--limit", "-l"),
) -> None:
    """Busca apenas no Reddit e salva resultados live."""
    console.print(f"[bold blue]🔍 Busca Reddit — live[/bold blue]\n")
    console.print(f"[dim]Query: {query}[/dim]\n")

    if is_reddit_pending_approval():
        console.print(f"[yellow]{REDDIT_PENDING_MESSAGE}[/yellow]")
        console.print("[dim]Rode reddit-policy-status para detalhes.[/dim]")
        raise typer.Exit(1)

    connector = RedditConnector(require_oauth=False)
    console.print(f"[dim]Modo: {connector.auth_mode}[/dim]")

    if not connector.auth_ok:
        console.print(f"[red]Auth falhou: {connector.auth_result.message}[/red]")
        console.print("[dim]Rode setup-env e reddit-policy-status[/dim]")
        raise typer.Exit(1)

    results = tag_results(connector.search_query(query, limit=limit), DataMode.LIVE)
    if not results:
        console.print("[yellow]Nenhum resultado live do Reddit.[/yellow]")
        if connector.is_gated:
            console.print(f"[dim]{REDDIT_PENDING_MESSAGE}[/dim]")
        raise typer.Exit(1)

    saved = save_results(results)
    export_to_csv(DEFAULT_CSV, DEFAULT_DB)
    console.print(f"[green]✓ {saved} resultados live salvos[/green]\n")

    table = Table(show_lines=True)
    table.add_column("Título", max_width=40)
    table.add_column("Subreddit")
    table.add_column("Intenção")
    table.add_column("Score", justify="right")
    table.add_column("Data")
    table.add_column("Link", max_width=30)

    for r in results:
        date_str = r.published_at.strftime("%Y-%m-%d") if r.published_at else "—"
        table.add_row(
            r.title[:40],
            r.location or "—",
            r.intent_type.value,
            str(r.intent_score),
            date_str,
            r.url[:30],
        )
    console.print(table)


@app.command("validate-import")
def validate_import(
    file: Path = typer.Argument(..., help="CSV de preços manuais"),
) -> None:
    """Valida CSV de importação LigaPokemon/MYP Cards."""
    console.print(f"[bold blue]📋 Validação de importação[/bold blue]\n{file}\n")
    result = validate_import_file(file)

    if result.valid:
        console.print(f"[green]✓ CSV válido — {result.row_count} linha(s)[/green]")
        raise typer.Exit(0)

    console.print(f"[red]✗ {len(result.errors)} erro(s) encontrado(s):[/red]\n")
    for err in result.errors:
        loc = f"Linha {err.row}" if err.row else "Arquivo"
        col = f" [{err.column}]" if err.column else ""
        console.print(f"  • {loc}{col}: {err.message}")
    raise typer.Exit(1)


@app.command("import-prices")
def import_prices(
    file: Path = typer.Argument(..., help="CSV de preços manuais"),
) -> None:
    """Importa preços manuais (data_mode=manual_import)."""
    console.print(f"[bold blue]📥 Importação de preços[/bold blue]\n{file}\n")

    validation = validate_import_file(file)
    if not validation.valid:
        console.print("[red]CSV inválido — rode validate-import primeiro.[/red]")
        raise typer.Exit(1)

    try:
        results = import_prices_from_csv(file)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if not results:
        console.print("[yellow]Nenhuma linha importada.[/yellow]")
        raise typer.Exit(1)

    saved = save_results(results)
    export_to_csv(DEFAULT_CSV, DEFAULT_DB)
    console.print(f"[green]✓ {saved} registro(s) manual_import salvos[/green]")
    console.print("[dim]Use market-snapshot para ver visão consolidada.[/dim]")


@app.command("market-snapshot")
def market_snapshot() -> None:
    """Snapshot de mercado com dados live + manual_import (sem mock)."""
    display_market_snapshot(console)


@app.command()
def search(
    cards: Path = typer.Option(DEFAULT_CARDS, "--cards", "-c"),
    sources_config: Path = typer.Option(DEFAULT_SOURCES, "--sources-config"),
    sources: str = typer.Option(
        "",
        "--sources",
        help="Fontes: reddit, mercado_livre, youtube (ex: reddit ou mercado_livre,reddit)",
    ),
    limit: int = typer.Option(20, "--limit", "-l"),
    live_only: bool = typer.Option(False, "--live-only"),
    allow_mock: bool = typer.Option(False, "--allow-mock"),
    mock_only: bool = typer.Option(False, "--mock-only"),
) -> None:
    """Executa busca nas fontes públicas configuradas."""
    try:
        mode = resolve_search_mode(live_only, allow_mock, mock_only)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    selected = parse_source_filter(sources)
    source_label = ", ".join(sorted(selected)) if selected else "todas"
    console.print(
        f"[bold blue]🔍 Radar Pokémon Brasil — busca ({mode.value})[/bold blue]\n"
        f"[dim]Fontes: {source_label}[/dim]\n"
    )

    card_list = load_cards(cards)
    if not card_list:
        console.print(f"[red]Nenhuma carta em {cards}[/red]")
        raise typer.Exit(1)

    sources_cfg = load_sources_config(sources_config)
    all_results: list[RadarResult] = []
    source_errors = 0

    if _source_enabled(selected, "reddit"):
        results, errors = _run_reddit_search(card_list, sources_cfg, limit, mode)
        all_results.extend(results)
        source_errors += errors

    if _source_enabled(selected, "mercado_livre"):
        results, errors = _run_ml_search(card_list, sources_cfg, limit, mode)
        all_results.extend(results)
        source_errors += errors

    yt_cfg = sources_cfg.get("youtube", {})
    if _source_enabled(selected, "youtube") and yt_cfg.get("enabled", False) and mode != SearchMode.MOCK_ONLY:
        console.print("[cyan]→ YouTube[/cyan]")
        connector = YouTubeConnector(
            max_comments_per_video=yt_cfg.get("max_comments_per_video", 20),
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
                "  • [bold]setup-env[/bold] + [bold]test-reddit-auth[/bold]\n"
                "  • [bold]import-prices[/bold] para dados manuais\n"
                "  • [bold]search --mock-only[/bold] — demonstração",
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
        console.print("[yellow]Sem dados. Rode search, search-reddit ou import-prices.[/yellow]")
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
    console.print("[green]✓ Banco, oportunidades, wishlist e CSV resetados.[/green]")


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
        style = {
            "OK": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "BLOCKED": "red",
            "PENDING_APPROVAL": "yellow",
            "PENDING_ACCESS": "yellow",
            "REQUIRES_AUTH": "yellow",
        }.get(st, "white")
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
    console.print("\n[dim]Salvo em connector_health (modo diagnóstico).[/dim]")


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
    console.print(f"[bold]Auth status:[/bold] {diag.auth_status}")
    console.print(f"[bold]URL:[/bold]\n{diag.url}\n")
    console.print(f"[bold]Status:[/bold] {diag.status_code}")
    console.print(f"[bold]OAuth necessário?[/bold] {'sim' if diag.needs_oauth else 'não'}")
    console.print(f"[dim]{diag.oauth_message}[/dim]")
    console.print(f"[dim]{diag.response_preview[:500]}[/dim]\n")
    for tip in diag.suggestions:
        console.print(f"  • {tip}")
    console.print("\n[dim]Salvo em connector_health.[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
