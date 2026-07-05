"""Comando setup-env — preparação do arquivo .env."""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.paths import PROJECT_ROOT
from src.reddit_auth import REDDIT_ENV_FIELDS

OPTIONAL_ENV_FIELDS = (
    "MERCADOLIVRE_ACCESS_TOKEN",
    "MERCADOLIVRE_USER_AGENT",
    "YOUTUBE_API_KEY",
    "APP_ENV",
    "DEFAULT_DATA_MODE",
)

REQUIRED_HINTS = {
    "REDDIT_CLIENT_ID": "ID do app em reddit.com/prefs/apps",
    "REDDIT_CLIENT_SECRET": "Secret do app Reddit",
    "REDDIT_USER_AGENT": "python:radar-pokemon-brasil:v0.1.0 (by /u/SEU_USUARIO)",
    "REDDIT_USERNAME": "Opcional — apenas para grant password (app script)",
    "REDDIT_PASSWORD": "Opcional — não preencha aqui via terminal; edite .env manualmente",
    "MERCADOLIVRE_ACCESS_TOKEN": "Opcional — token oficial ML se disponível",
    "MERCADOLIVRE_USER_AGENT": "User-Agent transparente para API ML",
}


def run_setup_env(console: Console) -> Path:
    """
    Verifica/cria .env a partir de .env.example.

    Não solicita nem armazena senhas no terminal.
    """
    env_path = PROJECT_ROOT / ".env"
    example_path = PROJECT_ROOT / ".env.example"

    console.print("[bold blue]⚙️  Setup — configuração do .env[/bold blue]\n")

    if not example_path.exists():
        console.print(f"[red].env.example não encontrado em {example_path}[/red]")
        raise SystemExit(1)

    created = False
    if env_path.exists():
        console.print(f"[green]✓[/green] Arquivo .env já existe: {env_path}")
    else:
        shutil.copy(example_path, env_path)
        created = True
        console.print(f"[green]✓[/green] Criado {env_path} a partir de .env.example")

    table = Table(title="Variáveis a preencher manualmente", show_lines=True)
    table.add_column("Variável", style="bold")
    table.add_column("Prioridade")
    table.add_column("Instrução")

    for field in REDDIT_ENV_FIELDS:
        hint = REQUIRED_HINTS.get(field, "")
        priority = "obrigatória (OAuth)" if field in (
            "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"
        ) else "opcional"
        if field in ("REDDIT_USERNAME", "REDDIT_PASSWORD"):
            priority = "opcional (password grant)"
        table.add_row(field, priority, hint)

    for field in OPTIONAL_ENV_FIELDS:
        table.add_row(field, "opcional", REQUIRED_HINTS.get(field, ""))

    console.print(table)

    console.print(
        Panel(
            "[bold]Próximos passos[/bold]\n\n"
            "1. Abra o arquivo [cyan].env[/cyan] no seu editor de texto\n"
            "2. Preencha REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET e REDDIT_USER_AGENT\n"
            "3. [yellow]Não cole senhas no terminal[/yellow] — edite o .env diretamente\n"
            "4. Salve o arquivo e rode:\n"
            "   [dim]python -m src.main test-reddit-auth[/dim]\n\n"
            "Para Reddit OAuth: crie um app em https://www.reddit.com/prefs/apps\n"
            "Tipo *script* ou *installed* — use client_credentials se não tiver usuário/senha.",
            title="Edite manualmente",
            border_style="cyan",
        )
    )

    if created:
        console.print("\n[dim]O .env foi criado vazio (valores de exemplo). Substitua pelos seus dados reais.[/dim]")

    return env_path
