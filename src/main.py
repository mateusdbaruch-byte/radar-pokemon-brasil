"""CLI principal do Radar Pokémon Brasil."""

from __future__ import annotations

import logging
from pathlib import Path

import time

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from src.connectors.web_search import ScanMode, WebSearchConnector, WebSearchQueryResult
from src.tcg_knowledge import (
    classify_text,
    generate_enriched_queries,
    vocab_summary_counts,
)
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
    DATA_DIR,
    PROJECT_ROOT,
)
from src.opportunity_db import (
    count_rejected_results,
    count_rejected_domains,
    count_saved_domains,
    export_review_csv,
    mark_opportunity_review,
    mark_rejected_review,
    resolve_opportunity_index,
    resolve_rejected_index,
    save_opportunities,
)
from src.opportunity_models import HumanReview, RejectedReview, WishlistLead
from src.opportunity_reporting import (
    display_card_radar,
    display_opportunity_inbox,
    display_opportunity_report,
    display_precision_report,
    display_profiles_summary,
    display_quality_report,
    display_query_performance_report,
    display_rejected_inbox,
    display_rejected_report,
    display_review_opportunities,
    display_unified_opportunity_report,
)
from src.search_profiles import get_search_profile, list_profile_names
from src.search_budget import (
    BudgetMode,
    SearchBudgetContext,
    display_search_budget_report,
    get_budget_status,
)
from src.watchlist_loader import load_watchlist_cards
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
    return load_watchlist_cards(path)


def _build_budget_ctx(
    *,
    profile: str = "",
    no_cache: bool = False,
    cache_ttl_hours: float = 24.0,
    daily_budget: int | None = None,
    monthly_budget: int | None = None,
    budget_mode: BudgetMode = BudgetMode.NORMAL,
) -> SearchBudgetContext:
    return SearchBudgetContext(
        profile=profile,
        no_cache=no_cache,
        cache_ttl_hours=cache_ttl_hours,
        daily_budget=daily_budget,
        monthly_budget=monthly_budget,
        budget_mode=budget_mode,
    )


def parse_card_list(cards_arg: str) -> list[str]:
    """Aceita lista separada por vírgula ou caminho YAML."""
    raw = cards_arg.strip()
    if not raw:
        return []
    if "," in raw and not raw.endswith(".yml") and not raw.endswith(".yaml"):
        return [c.strip() for c in raw.split(",") if c.strip()]
    path = Path(raw)
    if path.exists():
        return load_watchlist(path)
    return [raw]


def _print_quality_test_summary(
    card_list: list[str],
    result,
    *,
    saved: int,
    merged: int,
    elapsed: float,
) -> None:
    rejected = count_rejected_results()
    total_evaluated = saved + merged + rejected
    rate = ((saved + merged) / total_evaluated * 100) if total_evaluated else 0.0
    saved_domains = count_saved_domains()
    rejected_domains = count_rejected_domains()

    console.print("\n[bold]Resumo do teste de qualidade[/bold]")
    console.print(f"  Cartas testadas: {', '.join(card_list)}")
    ws = result.web_search_stats
    if ws:
        console.print(
            f"  Queries executadas: {ws.queries_executed}/{ws.queries_planned}"
        )
    console.print(f"  Oportunidades salvas: {saved + merged}")
    console.print(f"  Resultados rejeitados: {rejected}")
    if saved_domains:
        console.print(
            f"  Domínios salvos: {', '.join(f'{d}({c})' for d, c in list(saved_domains.items())[:6])}"
        )
    else:
        console.print("  Domínios salvos: —")
    if rejected_domains:
        console.print(
            f"  Domínios rejeitados: {', '.join(f'{d}({c})' for d, c in list(rejected_domains.items())[:6])}"
        )
    else:
        console.print("  Domínios rejeitados: —")
    console.print(f"  Taxa de aproveitamento: {rate:.1f}%")
    console.print(f"  Tempo total: {elapsed:.1f}s")


@app.command("search-budget-report")
def search_budget_report_cmd() -> None:
    """Relatório de consumo de buscas SerpAPI/web_search."""
    display_search_budget_report(console)


@app.command("profiles-summary")
def profiles_summary_cmd() -> None:
    """Lista perfis de busca disponíveis e seus filtros."""
    display_profiles_summary(console)


@app.command("profile-quality-test")
def profile_quality_test_cmd(
    profile: str = typer.Option(..., "--profile", "-p", help="Perfil: demand_leads, supply_deals, market_reference"),
    cards: str = typer.Option(
        "Charizard,Umbreon,Mew",
        "--cards",
        "-c",
        help="Cartas separadas por vírgula",
    ),
    limit: int = typer.Option(5, "--limit", "-l"),
    max_queries: int = typer.Option(0, "--max-queries"),
    budget_mode: BudgetMode = typer.Option(
        BudgetMode.NORMAL,
        "--budget-mode",
        help="normal ou economy (menos queries, cache obrigatório)",
    ),
    daily_budget: int = typer.Option(0, "--daily-budget", help="Limite diário (0 = .env)"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    cache_ttl_hours: float = typer.Option(24.0, "--cache-ttl-hours"),
) -> None:
    """Teste de qualidade por perfil — mede aproveitamento e recomenda ajustes."""
    if not get_search_profile(profile):
        console.print(f"[red]Perfil desconhecido: {profile}[/red]")
        console.print(f"[dim]Disponíveis: {', '.join(list_profile_names())}[/dim]")
        raise typer.Exit(1)

    card_list = parse_card_list(cards)
    if not card_list:
        console.print("[red]Informe cartas com --cards[/red]")
        raise typer.Exit(1)

    search_profile = get_search_profile(profile)
    query_cap = max_queries if max_queries > 0 else None
    scan_start = time.monotonic()

    console.print(
        f"[bold blue]🧪 Profile Quality Test — {profile}[/bold blue]\n"
        f"[dim]{search_profile.description}[/dim]\n"
        f"[dim]Cartas: {', '.join(card_list)} | limit={limit}[/dim]\n"
    )

    def _on_web_progress(
        query_result: WebSearchQueryResult,
        current: int,
        total: int,
    ) -> None:
        status = "[green]OK[/green]" if query_result.success else "[red]falha[/red]"
        if query_result.timed_out:
            status = "[yellow]timeout[/yellow]"
        console.print(
            f"[cyan]  [{current}/{total}][/cyan] {query_result.query[:70]}"
            f" → {len(query_result.hits)} hit(s) | {status}"
            f" | {query_result.elapsed_seconds:.1f}s"
        )

    result = scan_opportunities(
        card_list,
        "web_search",
        limit=limit,
        max_queries=query_cap,
        on_web_search_progress=_on_web_progress,
        profile=profile,
        budget_mode=budget_mode,
        budget_ctx=_build_budget_ctx(
            profile=profile,
            no_cache=no_cache,
            cache_ttl_hours=cache_ttl_hours,
            daily_budget=daily_budget if daily_budget > 0 else None,
            budget_mode=budget_mode,
        ),
        watchlist_path=DEFAULT_WATCHLIST,
    )

    elapsed = time.monotonic() - scan_start
    saved = merged = 0

    if result.opportunities:
        save_result = save_opportunities(result.opportunities)
        saved = save_result.saved
        merged = save_result.merged
        console.print(f"\n[green]✓ {saved + merged} oportunidades salvas[/green]")
    else:
        console.print("\n[yellow]Nenhuma oportunidade salva neste teste.[/yellow]")

    _print_quality_test_summary(
        card_list,
        result,
        saved=saved,
        merged=merged,
        elapsed=elapsed,
    )

    rejected = count_rejected_results()
    saved_total = saved + merged
    total_eval = saved_total + rejected
    rate = (saved_total / total_eval * 100) if total_eval else 0.0

    console.print("\n[bold]Recomendação do perfil[/bold]")
    if rate < 10 and rejected > 5:
        console.print(
            "  • [yellow]Perfil muito agressivo[/yellow] — recall baixo. "
            "Revise rejected-inbox para falsos negativos ou relaxe min_confidence."
        )
    elif rate > 50 and saved_total > 3:
        console.print(
            "  • [yellow]Perfil permissivo[/yellow] — revise opportunity-inbox "
            "e marque irrelevantes para medir precisão."
        )
    elif saved_total == 0:
        console.print(
            "  • [yellow]Zero salvos[/yellow] — verifique query-performance-report "
            "e rejected-inbox."
        )
    else:
        console.print(
            "  • [green]Perfil equilibrado[/green] — continue revisão manual "
            "(opportunity-inbox + rejected-inbox)."
        )
    console.print(
        "\n[dim]Próximo: rejected-inbox → query-performance-report → precision-report[/dim]"
    )


ALL_SEARCH_PROFILES = ("demand_leads", "supply_deals", "market_reference")


@app.command("run-all-profiles")
def run_all_profiles_cmd(
    cards: str = typer.Option(
        "Charizard,Umbreon,Mew",
        "--cards",
        "-c",
        help="Cartas separadas por vírgula",
    ),
    limit: int = typer.Option(5, "--limit", "-l"),
    max_queries: int = typer.Option(0, "--max-queries"),
    budget_mode: BudgetMode = typer.Option(
        BudgetMode.ECONOMY,
        "--budget-mode",
        help="normal ou economy (recomendado para rodar os 3 perfis)",
    ),
    daily_budget: int = typer.Option(0, "--daily-budget", help="Limite diário (0 = .env)"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    cache_ttl_hours: float = typer.Option(24.0, "--cache-ttl-hours"),
) -> None:
    """Executa demand_leads, supply_deals e market_reference com cache/orçamento."""
    card_list = parse_card_list(cards)
    if not card_list:
        console.print("[red]Informe cartas com --cards[/red]")
        raise typer.Exit(1)

    query_cap = max_queries if max_queries > 0 else None
    console.print(
        f"[bold blue]🛰️ Run All Profiles — radar híbrido[/bold blue]\n"
        f"[dim]Cartas: {', '.join(card_list)} | limit={limit} | "
        f"budget-mode={budget_mode.value}[/dim]\n"
    )

    total_saved = 0
    total_merged = 0

    for profile_name in ALL_SEARCH_PROFILES:
        console.print(f"\n[bold cyan]▶ Perfil: {profile_name}[/bold cyan]")
        search_profile = get_search_profile(profile_name)
        if not search_profile:
            console.print(f"[red]Perfil não encontrado: {profile_name}[/red]")
            continue

        result = scan_opportunities(
            card_list,
            "web_search",
            limit=limit,
            max_queries=query_cap,
            profile=profile_name,
            budget_mode=budget_mode,
            budget_ctx=_build_budget_ctx(
                profile=profile_name,
                no_cache=no_cache,
                cache_ttl_hours=cache_ttl_hours,
                daily_budget=daily_budget if daily_budget > 0 else None,
                budget_mode=budget_mode,
            ),
            watchlist_path=DEFAULT_WATCHLIST,
        )

        for msg in result.messages:
            console.print(f"[dim]  • {msg}[/dim]")

        if result.opportunities:
            save_result = save_opportunities(result.opportunities)
            total_saved += save_result.saved
            total_merged += save_result.merged
            console.print(
                f"[green]  ✓ {save_result.saved + save_result.merged} "
                f"oportunidades ({profile_name})[/green]"
            )
        else:
            console.print(f"[yellow]  Nenhuma oportunidade salva em {profile_name}[/yellow]")

        if result.web_search_stats and result.web_search_stats.budget_stopped:
            console.print(
                f"[yellow]Orçamento atingido — perfis restantes não executados.[/yellow]"
            )
            break

    console.print(
        f"\n[bold]Total salvo nesta execução:[/bold] "
        f"{total_saved + total_merged} ({total_saved} novas, {total_merged} mescladas)\n"
    )

    console.print("[bold]Relatórios gerados:[/bold]")
    display_opportunity_inbox(console, limit=15)
    console.print()
    display_query_performance_report(console, limit=30)
    console.print()
    display_unified_opportunity_report(console)


@app.command("unified-opportunity-report")
def unified_opportunity_report_cmd() -> None:
    """Relatório unificado cruzando demanda, oferta e referência por carta."""
    display_unified_opportunity_report(console)


@app.command("card-radar")
def card_radar_cmd(
    card: str = typer.Option(..., "--card", "-c", help="Nome da carta"),
) -> None:
    """Visão completa de uma carta no radar híbrido."""
    display_card_radar(console, card.strip())


@app.command("scan-quality-test")
def scan_quality_test_cmd(
    cards: str = typer.Option(
        "Charizard,Umbreon,Mew",
        "--cards",
        "-c",
        help="Cartas separadas por vírgula ou caminho YAML",
    ),
    mode: ScanMode = typer.Option(ScanMode.LIGHT, "--mode", "-m"),
    strict: bool = typer.Option(True, "--strict/--no-strict"),
    buyer_only: bool = typer.Option(True, "--buyer-only/--no-buyer-only"),
    limit: int = typer.Option(5, "--limit", "-l"),
    max_queries: int = typer.Option(0, "--max-queries"),
) -> None:
    """Teste de qualidade — scan web_search com strict e buyer-only para medir precisão."""
    card_list = parse_card_list(cards)
    if not card_list:
        console.print("[red]Informe cartas com --cards Charizard,Umbreon,Mew[/red]")
        raise typer.Exit(1)

    query_cap = max_queries if max_queries > 0 else None
    scan_start = time.monotonic()

    console.print(
        f"[bold blue]🧪 Scan Quality Test — validação de precisão[/bold blue]\n"
        f"[dim]Cartas: {', '.join(card_list)} | web_search only | "
        f"strict={strict} | buyer-only={buyer_only} | limit={limit}[/dim]\n"
    )

    def _on_web_progress(
        query_result: WebSearchQueryResult,
        current: int,
        total: int,
    ) -> None:
        status = "[green]OK[/green]" if query_result.success else "[red]falha[/red]"
        if query_result.timed_out:
            status = "[yellow]timeout[/yellow]"
        console.print(
            f"[cyan]  [{current}/{total}][/cyan] {query_result.query[:70]}"
            f" → {len(query_result.hits)} hit(s) | {status}"
            f" | {query_result.elapsed_seconds:.1f}s"
        )

    result = scan_opportunities(
        card_list,
        "web_search",
        limit=limit,
        mode=mode,
        max_queries=query_cap,
        on_web_search_progress=_on_web_progress,
        strict=strict,
        buyer_only=buyer_only,
        seller_only=False,
    )

    elapsed = time.monotonic() - scan_start
    saved = merged = 0

    if result.opportunities:
        save_result = save_opportunities(result.opportunities)
        saved = save_result.saved
        merged = save_result.merged
        console.print(f"\n[green]✓ {saved + merged} oportunidades salvas (live)[/green]")
    else:
        console.print("\n[yellow]Nenhuma oportunidade salva neste teste.[/yellow]")

    for msg in result.messages:
        console.print(f"[dim]  • {msg}[/dim]")

    _print_quality_test_summary(
        card_list,
        result,
        saved=saved,
        merged=merged,
        elapsed=elapsed,
    )
    console.print(
        "\n[dim]Próximo passo: opportunity-inbox → mark-opportunity → precision-report[/dim]"
    )


@app.command("scan-opportunities")
def scan_opportunities_cmd(
    cards: Path = typer.Option(DEFAULT_WATCHLIST, "--cards", "-c"),
    card: str = typer.Option("", "--card", help="Carta específica (sobrescreve --cards)"),
    sources: str = typer.Option(
        "web_search,wishlist",
        "--sources",
        help="Fontes: web_search,wishlist,mercado_livre,...",
    ),
    limit: int = typer.Option(20, "--limit", "-l"),
    mode: ScanMode = typer.Option(
        ScanMode.LIGHT,
        "--mode",
        "-m",
        help="light = menos queries; deep = mais templates e delay maior",
    ),
    max_queries: int = typer.Option(
        0,
        "--max-queries",
        help="Limite máximo de queries web_search (0 = usar .env)",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Filtro rigoroso: exige contexto Pokémon, intenção e confidence >= 65",
    ),
    buyer_only: bool = typer.Option(
        False,
        "--buyer-only",
        help="Salvar apenas demanda de compra (buyer_demand, high_intent_lead, discussion_signal)",
    ),
    seller_only: bool = typer.Option(
        False,
        "--seller-only",
        help="Salvar apenas ofertas de venda (seller_supply, urgent_sale, underpriced_listing)",
    ),
    profile: str = typer.Option(
        "",
        "--profile",
        "-p",
        help="Perfil de busca: demand_leads, supply_deals, market_reference",
    ),
    budget_mode: BudgetMode = typer.Option(
        BudgetMode.NORMAL,
        "--budget-mode",
        help="normal ou economy",
    ),
    daily_budget: int = typer.Option(0, "--daily-budget", help="Limite diário (0 = .env)"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    cache_ttl_hours: float = typer.Option(24.0, "--cache-ttl-hours"),
) -> None:
    """Escaneia oportunidades automatizadas nas fontes disponíveis."""
    if profile and not get_search_profile(profile):
        console.print(f"[red]Perfil desconhecido: {profile}[/red]")
        console.print(f"[dim]Disponíveis: {', '.join(list_profile_names())}[/dim]")
        raise typer.Exit(1)

    if card.strip():
        card_list = [card.strip()]
        cards_label = card.strip()
    else:
        card_list = load_watchlist(cards)
        cards_label = str(cards)
    if not card_list:
        console.print(f"[red]Nenhuma carta em {cards}[/red]")
        raise typer.Exit(1)

    if buyer_only and seller_only:
        console.print("[red]Use apenas um: --buyer-only ou --seller-only[/red]")
        raise typer.Exit(1)

    query_cap = max_queries if max_queries > 0 else None
    scan_start = time.monotonic()
    filter_notes = []
    if profile:
        filter_notes.append(f"profile={profile}")
    if strict:
        filter_notes.append("strict")
    if buyer_only:
        filter_notes.append("buyer-only")
    if seller_only:
        filter_notes.append("seller-only")
    if budget_mode == BudgetMode.ECONOMY:
        filter_notes.append("economy")
    filters_label = ", ".join(filter_notes) if filter_notes else "padrão"

    budget_status = get_budget_status()
    console.print(
        f"[bold blue]🎯 Opportunity Radar — scan ({mode.value})[/bold blue]\n"
        f"[dim]Cartas: {len(card_list)} ({cards_label}) | Fontes: {sources} | "
        f"max-queries: {query_cap or 'env'} | filtros: {filters_label} | "
        f"buscas hoje: {budget_status.daily_used}/{budget_status.daily_limit} "
        f"(restam {budget_status.remaining_daily})[/dim]\n"
    )

    def _on_web_progress(
        query_result: WebSearchQueryResult,
        current: int,
        total: int,
    ) -> None:
        status = "[green]OK[/green]" if query_result.success else "[red]falha[/red]"
        if query_result.timed_out:
            status = "[yellow]timeout[/yellow]"
        if query_result.cached:
            status = "[blue]cache[/blue]"
        retry_note = ""
        if query_result.retries > 0:
            retry_note = f" | [yellow]retry×{query_result.retries}[/yellow]"
        console.print(
            f"[cyan]  [{current}/{total}][/cyan] {query_result.query[:70]}"
            f" → {len(query_result.hits)} hit(s) | {status}"
            f" | {query_result.elapsed_seconds:.1f}s{retry_note}"
        )

    result = scan_opportunities(
        card_list,
        sources,
        limit=limit,
        mode=mode,
        max_queries=query_cap,
        on_web_search_progress=_on_web_progress if "web_search" in sources else None,
        strict=strict,
        buyer_only=buyer_only,
        seller_only=seller_only,
        profile=profile or None,
        budget_mode=budget_mode,
        budget_ctx=_build_budget_ctx(
            profile=profile,
            no_cache=no_cache,
            cache_ttl_hours=cache_ttl_hours,
            daily_budget=daily_budget if daily_budget > 0 else None,
            budget_mode=budget_mode,
        ),
        watchlist_path=cards if not card.strip() else None,
    )

    elapsed = time.monotonic() - scan_start

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
                "  • Rode rejected-report para ver o que foi filtrado\n"
                "  • doctor para diagnóstico",
                border_style="yellow",
                title="Scan vazio",
            )
        )
        if result.web_search_stats:
            _print_scan_summary(result, elapsed, saved=0, merged=0, dedup_db=0)
        raise typer.Exit(1)

    save_result = save_opportunities(result.opportunities)
    total_saved = save_result.saved + save_result.merged
    console.print(f"\n[green]✓ {total_saved} oportunidades salvas[/green]")
    console.print(
        f"[dim]Fontes live nesta execução: {', '.join(result.live_sources) or '—'}[/dim]\n"
    )

    _print_scan_summary(
        result,
        elapsed,
        saved=save_result.saved,
        merged=save_result.merged,
        dedup_db=save_result.urls_deduplicated,
    )

    table = Table(title="Top oportunidades", show_lines=True)
    table.add_column("Carta", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Tipo")
    table.add_column("Fonte")
    table.add_column("data_mode")
    table.add_column("Evidência", max_width=35)
    for opp in result.opportunities[:10]:
        table.add_row(
            opp.normalized_card_name,
            str(opp.opportunity_score),
            opp.opportunity_type.value,
            opp.source,
            opp.data_mode.value,
            opp.evidence_text[:35],
        )
    console.print(table)


def _print_scan_summary(
    result,
    elapsed: float,
    *,
    saved: int,
    merged: int,
    dedup_db: int,
) -> None:
    console.print("[bold]Resumo do scan[/bold]")
    ws = result.web_search_stats
    if ws:
        console.print(
            f"  Queries: {ws.queries_executed}/{ws.queries_planned} executadas | "
            f"{ws.queries_success} sucesso | {ws.queries_timeout} timeout | "
            f"{ws.queries_retried} com retry"
        )
        console.print(
            f"  Web hits: {ws.hits_found} | rejeitados: {ws.results_rejected} | "
            f"dedup no scan: {ws.urls_deduplicated}"
        )
    console.print(f"  Tempo total: {elapsed:.1f}s")
    console.print(f"  Oportunidades salvas: {saved} (+ {merged} mescladas por URL)")
    console.print(
        f"  Por data_mode — live: {result.live_opportunities} | "
        f"opt-in: {result.opt_in_opportunities}"
    )
    console.print(
        f"  URLs deduplicadas (DB): {dedup_db + result.urls_deduplicated_in_scan}"
    )


@app.command("vocab-summary")
def vocab_summary_cmd() -> None:
    """Resumo do vocabulário TCG carregado dos YAMLs."""
    counts = vocab_summary_counts()
    console.print("[bold blue]📚 TCG Knowledge Layer — vocabulário[/bold blue]\n")
    table = Table(show_lines=True)
    table.add_column("Categoria")
    table.add_column("Quantidade", justify="right")
    rows = [
        ("Coleções cadastradas", counts["collections"]),
        ("Aliases de coleção", counts["aliases"]),
        ("Termos core TCG", counts["core_terms"]),
        ("Termos de raridade", counts["rarity"]),
        ("Termos de condição", counts["condition"]),
        ("Termos de grading", counts["grading"]),
        ("Jargão de compra", counts["buyer_jargon"]),
        ("Jargão de venda", counts["seller_jargon"]),
        ("Jargão de colecionador", counts["collector_jargon"]),
        ("Termos negativos", counts["negative"]),
    ]
    for label, count in rows:
        table.add_row(label, str(count))
    console.print(table)
    console.print("\n[dim]Configs: config/tcg_vocabulary.yml, collection_aliases.yml, ...[/dim]")


@app.command("expand-queries")
def expand_queries_cmd(
    card: str = typer.Option(..., "--card", "-c"),
    mode: ScanMode = typer.Option(ScanMode.LIGHT, "--mode", "-m"),
    buyer_only: bool = typer.Option(False, "--buyer-only"),
    seller_only: bool = typer.Option(False, "--seller-only"),
) -> None:
    """Mostra queries enriquecidas que serão usadas no scan."""
    if buyer_only and seller_only:
        console.print("[red]Use apenas um: --buyer-only ou --seller-only[/red]")
        raise typer.Exit(1)
    queries = generate_enriched_queries(
        card.strip(),
        mode.value,
        buyer_only=buyer_only,
        seller_only=seller_only,
    )
    console.print(f"[bold blue]🔎 Queries enriquecidas — {card}[/bold blue]\n")
    console.print(f"[dim]Modo: {mode.value} | total: {len(queries)}[/dim]\n")
    for i, q in enumerate(queries, 1):
        console.print(f"  {i}. {q}")


@app.command("classify-text")
def classify_text_cmd(
    text: str = typer.Argument(..., help="Texto para classificar"),
    card: str = typer.Option("", "--card", help="Dica de carta (opcional)"),
) -> None:
    """Classifica texto livre com a TCG Knowledge Layer."""
    result = classify_text(text, card_hint=card.strip())
    s = result.signals
    console.print("[bold blue]🧠 Classificação TCG[/bold blue]\n")
    console.print(f"[bold]Texto:[/bold] {text}\n")
    table = Table(show_lines=True)
    table.add_column("Campo")
    table.add_column("Valor")
    table.add_row("Carta detectada", result.card_detected or "—")
    table.add_row("Alias detectado", result.card_alias or "—")
    table.add_row("Confiança carta", str(result.card_confidence) if result.card_confidence else "—")
    table.add_row("Motivo detecção", result.card_detection_reason or "—")
    table.add_row("Coleção", s.collection or "—")
    table.add_row("Idioma", ", ".join(s.language) or "—")
    table.add_row("Condição", ", ".join(s.condition) or "—")
    table.add_row("Raridade", ", ".join(s.rarity) or "—")
    table.add_row("Grading", ", ".join(s.grading) or "—")
    table.add_row("Intenção compra", ", ".join(s.buyer_jargon) or "—")
    table.add_row("Intenção venda", ", ".join(s.seller_jargon) or "—")
    table.add_row("Contexto negativo", ", ".join(s.negative_context) or "—")
    table.add_row("Tipo oportunidade", result.opportunity_type)
    table.add_row("Intent score", str(result.intent_score))
    table.add_row("Opportunity score", str(result.opportunity_score))
    table.add_row("Confidence", str(result.confidence_score))
    table.add_row("Oportunidade provável", result.probable_opportunity)
    console.print(table)


@app.command("rejected-report")
def rejected_report_cmd(
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Relatório de resultados rejeitados pelo filtro de qualidade."""
    display_rejected_report(console, limit=limit)


@app.command("rejected-inbox")
def rejected_inbox_cmd(
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Lista resultados rejeitados para revisão manual."""
    display_rejected_inbox(console, limit=limit)


@app.command("mark-rejected")
def mark_rejected_cmd(
    rej_id: int = typer.Option(..., "--id", help="ID 1-based (como em rejected-inbox)"),
    review: RejectedReview = typer.Option(
        ...,
        "--review",
        help="false_negative ou correct_rejection",
    ),
    notes: str = typer.Option("", "--notes"),
) -> None:
    """Marca resultado rejeitado com revisão humana."""
    row = resolve_rejected_index(rej_id)
    if not row:
        console.print(f"[red]Rejeitado #{rej_id} não encontrado.[/red]")
        raise typer.Exit(1)

    ok = mark_rejected_review(row.id, review.value, notes)
    if not ok:
        console.print("[red]Falha ao salvar revisão.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]✓ Rejeitado #{rej_id} marcado como {review.value}[/green]\n"
        f"[dim]Query: {row.query[:60]} | Motivo: {row.reason[:50]}[/dim]"
    )


@app.command("query-performance-report")
def query_performance_report_cmd(
    limit: int = typer.Option(30, "--limit", "-n"),
) -> None:
    """Relatório de performance por query executada."""
    display_query_performance_report(console, limit=limit)


@app.command("quality-report")
def quality_report_cmd() -> None:
    """Relatório de qualidade — aproveitamento e recomendações."""
    display_quality_report(console)


@app.command("review-opportunities")
def review_opportunities_cmd(
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """Lista oportunidades para revisão manual humana."""
    display_review_opportunities(console, limit=limit)


@app.command("mark-opportunity")
def mark_opportunity_cmd(
    opp_id: int = typer.Option(..., "--id", help="ID 1-based (como em opportunity-inbox)"),
    review: HumanReview = typer.Option(..., "--review", help="relevant, irrelevant ou maybe"),
    notes: str = typer.Option("", "--notes", help="Notas opcionais da revisão"),
) -> None:
    """Marca oportunidade com revisão humana."""
    opp = resolve_opportunity_index(opp_id)
    if not opp:
        console.print(f"[red]Oportunidade #{opp_id} não encontrada.[/red]")
        raise typer.Exit(1)

    ok = mark_opportunity_review(opp.id, review.value, notes)
    if not ok:
        console.print("[red]Falha ao salvar revisão.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]✓ Oportunidade #{opp_id} marcada como {review.value}[/green]\n"
        f"[dim]Carta: {opp.normalized_card_name} | "
        f"Tipo: {opp.opportunity_type.value} | "
        f"Domínio: {opp.domain or '—'}[/dim]"
    )
    if notes:
        console.print(f"[dim]Notas: {notes}[/dim]")


@app.command("precision-report")
def precision_report_cmd() -> None:
    """Relatório de precisão baseado em revisão humana."""
    display_precision_report(console)


@app.command("export-review-csv")
def export_review_csv_cmd(
    output: Path = typer.Option(
        DATA_DIR / "opportunity_review.csv",
        "--output",
        "-o",
        help="Caminho do CSV de exportação",
    ),
) -> None:
    """Exporta oportunidades com revisão para CSV."""
    count = export_review_csv(output)
    console.print(f"[green]✓ {count} oportunidade(s) exportadas para {output}[/green]")


@app.command("web-search-test")
def web_search_test(
    query: str = typer.Option(..., "--query", "-q", help="Query de teste"),
    limit: int = typer.Option(5, "--limit", "-l"),
) -> None:
    """Testa uma única query web_search e exibe diagnóstico."""
    connector = WebSearchConnector()
    console.print("[bold blue]🔍 Web Search — teste único[/bold blue]\n")

    if not connector.is_configured():
        console.print(
            Panel(
                "[yellow]web_search não configurado.[/yellow]\n\n"
                "Defina WEB_SEARCH_PROVIDER e a chave correspondente no .env",
                border_style="yellow",
                title="Não configurado",
            )
        )
        raise typer.Exit(1)

    console.print(f"[dim]Provider: {connector.provider} | data_mode: live[/dim]")
    console.print(f"[dim]Query: {query}[/dim]\n")

    result = connector.search_query(query, limit=limit)

    if result.success:
        status = "[green]sucesso[/green]"
    elif result.timed_out:
        status = "[yellow]timeout[/yellow]"
    else:
        status = f"[red]falha[/red] ({result.error})"

    console.print(f"[bold]Status:[/bold] {status}")
    console.print(f"[bold]Tempo:[/bold] {result.elapsed_seconds:.2f}s")
    console.print(f"[bold]Resultados:[/bold] {len(result.hits)}")
    console.print(f"[bold]data_mode:[/bold] live")
    if result.retries > 0:
        console.print(f"[bold]Retries:[/bold] {result.retries}")

    if result.hits:
        table = Table(title="Top resultados", show_lines=True)
        table.add_column("#", justify="right")
        table.add_column("Título", max_width=45)
        table.add_column("URL", max_width=40)
        for i, hit in enumerate(result.hits[:limit], start=1):
            table.add_row(str(i), hit.title[:45], hit.url[:40])
        console.print(table)
    else:
        console.print("[yellow]Nenhum resultado retornado.[/yellow]")


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
