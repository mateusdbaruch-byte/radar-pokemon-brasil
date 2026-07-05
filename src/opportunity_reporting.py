"""Relatórios do Opportunity Radar — inbox e report."""

from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.opportunity_db import count_opportunities_by_source, fetch_opportunities, fetch_wishlist_leads
from src.opportunity_models import Opportunity, OpportunityType
from src.source_registry import SourceAccess, get_source_registry


def _action_style(score: int) -> str:
    if score >= 80:
        return "bold green"
    if score >= 60:
        return "yellow"
    return "dim"


def display_opportunity_inbox(console: Console, limit: int = 15) -> None:
    """Exibe caixa de entrada de oportunidades."""
    opps = fetch_opportunities(limit=limit)
    console.print("[bold blue]📥 Opportunity Inbox[/bold blue]\n")

    if not opps:
        console.print(
            Panel(
                "Nenhuma oportunidade. Rode scan-opportunities primeiro.",
                border_style="yellow",
            )
        )
        return

    table = Table(show_lines=True)
    table.add_column("Tipo")
    table.add_column("Carta", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Fonte")
    table.add_column("Evidência", max_width=35)
    table.add_column("Ação", max_width=28)

    for opp in opps:
        style = _action_style(opp.opportunity_score)
        table.add_row(
            opp.opportunity_type.value,
            opp.normalized_card_name,
            f"[{style}]{opp.opportunity_score}[/{style}]",
            opp.source,
            opp.evidence_text[:35],
            opp.recommended_action[:28],
        )
    console.print(table)

    console.print("\n[dim]Links:[/dim]")
    for opp in opps[:5]:
        if opp.url:
            console.print(f"  • {opp.normalized_card_name}: {opp.url[:70]}")


def display_opportunity_report(console: Console) -> None:
    """Relatório consolidado de oportunidades."""
    opps = fetch_opportunities()
    wishlist = fetch_wishlist_leads()
    registry = get_source_registry()
    by_source = count_opportunities_by_source()

    console.print("[bold blue]📊 Opportunity Report — Radar Pokémon Brasil[/bold blue]\n")

    # Resumo
    live_sources = [n for n, i in registry.items() if i.access == SourceAccess.LIVE]
    pending = [n for n, i in registry.items() if i.access == SourceAccess.PENDING_ACCESS]
    gated = [
        n for n, i in registry.items()
        if i.access in (SourceAccess.PENDING_APPROVAL, SourceAccess.REQUIRES_AUTH)
    ]

    console.print(Panel(
        f"[bold]Oportunidades:[/bold] {len(opps)}\n"
        f"[bold]Wishlist leads (opt-in):[/bold] {len(wishlist)}\n"
        f"[bold]Fontes live:[/bold] {', '.join(live_sources) or '—'}\n"
        f"[bold]Fontes PENDING_ACCESS:[/bold] {len(pending)}\n"
        f"[bold]Fontes gated/auth:[/bold] {len(gated)}",
        title="Resumo",
        border_style="blue",
    ))

    # Cartas mais procuradas
    if opps:
        card_counts = Counter(
            o.normalized_card_name
            for o in opps
            if o.opportunity_type in (
                OpportunityType.BUYER_INTENT,
                OpportunityType.WISHLIST_LEAD,
            )
        )
        if card_counts:
            console.print("\n[bold]Cartas mais procuradas[/bold]")
            for card, cnt in card_counts.most_common(5):
                console.print(f"  • {card}: {cnt} sinal(is)")

    # Top oportunidades
    if opps:
        console.print("\n[bold]Top oportunidades (score)[/bold]\n")
        top_table = Table(show_lines=True)
        top_table.add_column("#", justify="right")
        top_table.add_column("Carta")
        top_table.add_column("Score", justify="right")
        top_table.add_column("Tipo")
        top_table.add_column("Fonte")
        for i, opp in enumerate(opps[:10], 1):
            top_table.add_row(
                str(i),
                opp.normalized_card_name,
                str(opp.opportunity_score),
                opp.opportunity_type.value,
                opp.source,
            )
        console.print(top_table)

    # Wishlist buyers
    if wishlist:
        console.print("\n[bold]Compradores potenciais (wishlist opt-in)[/bold]\n")
        wl_table = Table(show_lines=True)
        wl_table.add_column("Nome")
        wl_table.add_column("Carta")
        wl_table.add_column("Urgência")
        wl_table.add_column("Contato")
        for lead in wishlist[:10]:
            wl_table.add_row(
                lead.name,
                lead.card_name,
                lead.urgency,
                lead.contact[:30] if lead.contact else "—",
            )
        console.print(wl_table)

    # Web signals
    web_opps = [o for o in opps if o.source == "web_search"]
    if web_opps:
        console.print(f"\n[bold]Sinais públicos na web:[/bold] {len(web_opps)}")
    elif any(s == "web_search" for s in live_sources):
        console.print("\n[dim]Busca web configurada mas sem resultados ainda.[/dim]")

    # Fontes por status
    console.print("\n[bold]Status das fontes[/bold]\n")
    src_table = Table(show_lines=True)
    src_table.add_column("Fonte")
    src_table.add_column("Acesso")
    src_table.add_column("Coletados")
    src_table.add_column("Nota")
    for name, info in sorted(registry.items()):
        access_style = {
            SourceAccess.LIVE: "green",
            SourceAccess.PENDING_ACCESS: "yellow",
            SourceAccess.REQUIRES_AUTH: "yellow",
            SourceAccess.PENDING_APPROVAL: "yellow",
        }.get(info.access, "white")
        src_table.add_row(
            info.label,
            f"[{access_style}]{info.access.value}[/{access_style}]",
            str(by_source.get(name, 0)),
            info.message[:40],
        )
    console.print(src_table)
