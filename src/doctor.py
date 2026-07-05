"""Comando doctor — diagnóstico geral do projeto e conectores."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.connector_health import (
    ConnectorDataMode,
    HealthCheckResult,
    HealthStatus,
    save_health_checks,
)
from src.connectors.mercado_livre import diagnose_search as diagnose_ml
from src.connectors.reddit import diagnose_search as diagnose_reddit
from src.exporters import export_to_csv
from src.models import RadarResult
from src.paths import (
    DEFAULT_CARDS,
    DEFAULT_CSV,
    DEFAULT_DB,
    DEFAULT_KEYWORDS,
    DEFAULT_SOURCES,
    PROJECT_ROOT,
    ensure_data_dir,
)


def _check_mercado_livre() -> HealthCheckResult:
    diag = diagnose_ml("carta pokemon charizard")
    snippet = diag.response_preview[:500]

    if diag.status_code == 200 and diag.is_valid_json and (diag.results_count or 0) >= 0:
        if diag.results_count and diag.results_count > 0:
            return HealthCheckResult(
                source="mercado_livre",
                status=HealthStatus.OK,
                data_mode=ConnectorDataMode.LIVE,
                http_status=diag.status_code,
                message=f"API acessível — {diag.results_count} anúncio(s) na resposta de teste",
                next_action="Rode search --live-only para coletar dados reais",
                raw_response_snippet=snippet,
            )
        return HealthCheckResult(
            source="mercado_livre",
            status=HealthStatus.WARNING,
            data_mode=ConnectorDataMode.LIVE,
            http_status=diag.status_code,
            message="API respondeu 200, mas sem anúncios na query de teste",
            next_action="Ajuste a query ou teste outra carta",
            raw_response_snippet=snippet,
        )

    if diag.status_code == 403:
        return HealthCheckResult(
            source="mercado_livre",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=403,
            message="HTTP 403 forbidden — bloqueio da API (não é dado real)",
            next_action="Teste em rede residencial; não use resultados deste IP",
            raw_response_snippet=snippet,
        )

    if diag.status_code == 429:
        return HealthCheckResult(
            source="mercado_livre",
            status=HealthStatus.WARNING,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=429,
            message="HTTP 429 — rate limit",
            next_action="Aguarde alguns minutos e rode doctor novamente",
            raw_response_snippet=snippet,
        )

    return HealthCheckResult(
        source="mercado_livre",
        status=HealthStatus.ERROR,
        data_mode=ConnectorDataMode.UNAVAILABLE,
        http_status=diag.status_code,
        message=diag.error_message or f"Falha HTTP {diag.status_code}",
        next_action=(diag.suggestions[0] if diag.suggestions else "Rode test-mercadolivre"),
        raw_response_snippet=snippet,
    )


def _check_reddit() -> HealthCheckResult:
    diag = diagnose_reddit("pokemon tcg brasil charizard")
    snippet = diag.response_preview[:500]
    auth_note = f" [{diag.auth_mode}]" if hasattr(diag, "auth_mode") else ""

    if diag.status_code == 200 and diag.is_valid_json:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=diag.status_code,
            message=f"Endpoint público OK{auth_note} — {diag.posts_count or 0} post(s)",
            next_action="Rode search --live-only",
            raw_response_snippet=snippet,
        )

    if diag.status_code == 403:
        return HealthCheckResult(
            source="reddit",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=403,
            message=f"Bloqueado (403){auth_note} — configure REDDIT_USER_AGENT ou OAuth",
            next_action="Personalize .env e teste em rede residencial",
            raw_response_snippet=snippet,
        )

    return HealthCheckResult(
        source="reddit",
        status=HealthStatus.ERROR,
        data_mode=ConnectorDataMode.UNAVAILABLE,
        http_status=diag.status_code,
        message=(diag.error_message or f"Falha HTTP {diag.status_code}") + auth_note,
        next_action=(diag.suggestions[0] if diag.suggestions else "Rode test-reddit"),
        raw_response_snippet=snippet,
    )


def _check_sqlite() -> HealthCheckResult:
    try:
        ensure_data_dir()
        conn = sqlite3.connect(str(DEFAULT_DB))
        conn.execute("SELECT 1")
        conn.close()
        return HealthCheckResult(
            source="sqlite",
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=None,
            message=f"Banco acessível em {DEFAULT_DB}",
            next_action="Nenhuma ação necessária",
        )
    except sqlite3.Error as exc:
        return HealthCheckResult(
            source="sqlite",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=None,
            message=str(exc),
            next_action="Verifique permissões da pasta data/",
        )


def _check_csv_write() -> HealthCheckResult:
    try:
        ensure_data_dir()
        template = RadarResult(
            source="test",
            platform="test",
            card_name_detected="Test",
            normalized_card_name="Test",
            url="https://example.com",
        )
        import pandas as pd

        path = DEFAULT_CSV.parent / ".doctor_csv_test.csv"
        pd.DataFrame(columns=list(template.to_db_row().keys())).to_csv(
            path, index=False, encoding="utf-8-sig"
        )
        path.unlink(missing_ok=True)
        return HealthCheckResult(
            source="csv",
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=None,
            message=f"Escrita CSV OK em {DEFAULT_CSV.parent}",
            next_action="Nenhuma ação necessária",
        )
    except OSError as exc:
        return HealthCheckResult(
            source="csv",
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=None,
            message=str(exc),
            next_action="Verifique permissões da pasta data/",
        )


def _check_env() -> HealthCheckResult:
    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"
    if not env_path.exists():
        return HealthCheckResult(
            source=".env",
            status=HealthStatus.WARNING,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=None,
            message="Arquivo .env não encontrado",
            next_action=f"Copie: cp {example_path.name} .env",
        )
    has_ua = bool(os.getenv("REDDIT_USER_AGENT", "").strip())
    has_oauth = bool(os.getenv("REDDIT_CLIENT_ID", "").strip())
    msg = ".env carregado"
    if has_oauth:
        msg += " — Reddit OAuth configurado"
    elif has_ua:
        msg += " — REDDIT_USER_AGENT definido"
    else:
        return HealthCheckResult(
            source=".env",
            status=HealthStatus.WARNING,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=None,
            message=".env existe, mas REDDIT_USER_AGENT não configurado",
            next_action="Edite .env com User-Agent descritivo",
        )
    return HealthCheckResult(
        source=".env",
        status=HealthStatus.OK,
        data_mode=ConnectorDataMode.LIVE,
        http_status=None,
        message=msg,
        next_action="Nenhuma ação necessária",
    )


def _check_config_file(path: Path, name: str) -> HealthCheckResult:
    if not path.exists():
        return HealthCheckResult(
            source=name,
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=None,
            message=f"Arquivo ausente: {path}",
            next_action=f"Crie ou restaure {path.name}",
        )
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            raise ValueError("YAML vazio")
        return HealthCheckResult(
            source=name,
            status=HealthStatus.OK,
            data_mode=ConnectorDataMode.LIVE,
            http_status=None,
            message=f"{path.name} válido",
            next_action="Nenhuma ação necessária",
        )
    except (yaml.YAMLError, ValueError, OSError) as exc:
        return HealthCheckResult(
            source=name,
            status=HealthStatus.ERROR,
            data_mode=ConnectorDataMode.UNAVAILABLE,
            http_status=None,
            message=str(exc),
            next_action=f"Corrija sintaxe de {path.name}",
        )


def run_doctor_checks() -> list[HealthCheckResult]:
    """Executa todos os checks do doctor."""
    return [
        _check_mercado_livre(),
        _check_reddit(),
        _check_sqlite(),
        _check_csv_write(),
        _check_env(),
        _check_config_file(DEFAULT_CARDS, "config/cards.yml"),
        _check_config_file(DEFAULT_KEYWORDS, "config/keywords.yml"),
        _check_config_file(DEFAULT_SOURCES, "config/sources.yml"),
    ]


def display_doctor_table(console: Console, results: list[HealthCheckResult]) -> None:
    """Exibe tabela de saúde no terminal."""
    table = Table(title="🩺 Doctor — Saúde do Radar Pokémon Brasil", show_lines=True)
    table.add_column("Fonte", style="bold")
    table.add_column("Status")
    table.add_column("data_mode")
    table.add_column("HTTP")
    table.add_column("Mensagem", max_width=36)
    table.add_column("Próxima ação", max_width=32)

    status_style = {
        HealthStatus.OK: "green",
        HealthStatus.WARNING: "yellow",
        HealthStatus.ERROR: "red",
    }

    for r in results:
        st = status_style.get(r.status, "white")
        http = str(r.http_status) if r.http_status is not None else "—"
        table.add_row(
            r.source,
            f"[{st}]{r.status.value}[/{st}]",
            r.data_mode.value,
            http,
            r.message[:80],
            r.next_action[:80],
        )

    console.print(table)


def run_doctor(console: Console, persist: bool = True) -> list[HealthCheckResult]:
    """Executa doctor completo e opcionalmente persiste resultados."""
    console.print("[bold blue]🩺 Doctor — diagnóstico do ambiente[/bold blue]\n")
    results = run_doctor_checks()
    display_doctor_table(console, results)
    if persist:
        save_health_checks(results)
        console.print("\n[dim]Diagnóstico salvo em connector_health.[/dim]")
    return results
