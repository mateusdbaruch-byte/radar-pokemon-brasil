"""Relatórios do Opportunity Radar — inbox, report, quality e rejected."""

from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.opportunity_db import (
    count_opportunities_by_source,
    count_rejected_by_reason,
    count_rejected_domains,
    count_rejected_results,
    count_saved_domains,
    fetch_opportunities,
    fetch_rejected_results,
    fetch_wishlist_leads,
)
from src.opportunity_models import Opportunity, OpportunityType
from src.opportunity_quality import extract_domain
from src.source_registry import SourceAccess, get_source_registry


def _action_style(score: int) -> str:
    if score >= 80:
        return "bold green"
    if score >= 60:
        return "yellow"
    return "dim"


def _domain_from_opp(opp: Opportunity) -> str:
    return extract_domain(opp.url) if opp.url else opp.platform


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
    table.add_column("Conf.", justify="right")
    table.add_column("Fonte/domínio", max_width=22)
    table.add_column("why_saved", max_width=30)
    table.add_column("Evidência", max_width=28)
    table.add_column("URL", max_width=24)

    for opp in opps:
        style = _action_style(opp.opportunity_score)
        table.add_row(
            opp.opportunity_type.value,
            opp.normalized_card_name,
            f"[{style}]{opp.opportunity_score}[/{style}]",
            str(opp.confidence_score),
            f"{opp.source}\n{_domain_from_opp(opp)}"[:22],
            (opp.why_saved or "—")[:30],
            opp.evidence_text[:28],
            (opp.url or "—")[:24],
        )
    console.print(table)


def display_opportunity_report(console: Console) -> None:
    """Relatório consolidado de oportunidades."""
    opps = fetch_opportunities()
    wishlist = fetch_wishlist_leads()
    registry = get_source_registry()
    by_source = count_opportunities_by_source()

    console.print("[bold blue]📊 Opportunity Report — Radar Pokémon Brasil[/bold blue]\n")

    live_sources = [n for n, i in registry.items() if i.access == SourceAccess.LIVE]
    pending = [n for n, i in registry.items() if i.access == SourceAccess.PENDING_ACCESS]
    gated = [
        n for n, i in registry.items()
        if i.access in (SourceAccess.PENDING_APPROVAL, SourceAccess.REQUIRES_AUTH)
    ]

    console.print(Panel(
        f"[bold]Oportunidades:[/bold] {len(opps)}\n"
        f"[bold]Wishlist leads (opt-in):[/bold] {len(wishlist)}\n"
        f"[bold]Rejeitados:[/bold] {count_rejected_results()}\n"
        f"[bold]Fontes live:[/bold] {', '.join(live_sources) or '—'}\n"
        f"[bold]Fontes PENDING_ACCESS:[/bold] {len(pending)}\n"
        f"[bold]Fontes gated/auth:[/bold] {len(gated)}",
        title="Resumo",
        border_style="blue",
    ))

    if opps:
        card_counts = Counter(
            o.normalized_card_name
            for o in opps
            if o.opportunity_type in (
                OpportunityType.BUYER_INTENT,
                OpportunityType.BUYER_DEMAND,
                OpportunityType.HIGH_INTENT_LEAD,
                OpportunityType.DISCUSSION_SIGNAL,
                OpportunityType.WISHLIST_LEAD,
            )
        )
        if card_counts:
            console.print("\n[bold]Cartas mais procuradas[/bold]")
            for card, cnt in card_counts.most_common(5):
                console.print(f"  • {card}: {cnt} sinal(is)")

    if opps:
        console.print("\n[bold]Top oportunidades (score)[/bold]\n")
        top_table = Table(show_lines=True)
        top_table.add_column("#", justify="right")
        top_table.add_column("Carta")
        top_table.add_column("Score", justify="right")
        top_table.add_column("Conf.", justify="right")
        top_table.add_column("Tipo")
        top_table.add_column("Fonte")
        for i, opp in enumerate(opps[:10], 1):
            top_table.add_row(
                str(i),
                opp.normalized_card_name,
                str(opp.opportunity_score),
                str(opp.confidence_score),
                opp.opportunity_type.value,
                opp.source,
            )
        console.print(top_table)

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

    web_opps = [o for o in opps if o.source == "web_search"]
    if web_opps:
        console.print(f"\n[bold]Sinais públicos na web:[/bold] {len(web_opps)}")
    elif any(s == "web_search" for s in live_sources):
        console.print("\n[dim]Busca web configurada mas sem resultados ainda.[/dim]")

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


def display_rejected_report(console: Console, limit: int = 10) -> None:
    """Relatório de resultados rejeitados pelo filtro de qualidade."""
    total = count_rejected_results()
    console.print("[bold blue]🚫 Rejected Results Report[/bold blue]\n")

    if total == 0:
        console.print(Panel("Nenhum resultado rejeitado ainda.", border_style="yellow"))
        return

    console.print(f"[bold]Total rejeitados:[/bold] {total}\n")

    by_reason = count_rejected_by_reason()
    console.print("[bold]Principais motivos[/bold]")
    for reason, cnt in list(by_reason.items())[:8]:
        console.print(f"  • {reason}: {cnt}")

    by_domain = count_rejected_domains()
    if by_domain:
        console.print("\n[bold]Domínios mais rejeitados[/bold]")
        for domain, cnt in list(by_domain.items())[:8]:
            console.print(f"  • {domain}: {cnt}")

    examples = fetch_rejected_results(limit=limit)
    if examples:
        console.print("\n[bold]Exemplos de rejeição[/bold]\n")
        table = Table(show_lines=True)
        table.add_column("Motivo", max_width=35)
        table.add_column("Título", max_width=30)
        table.add_column("URL", max_width=28)
        for row in examples:
            table.add_row(row.reason[:35], row.title[:30], (row.url or "—")[:28])
        console.print(table)


def display_quality_report(console: Console) -> None:
    """Relatório de qualidade — aproveitamento e recomendações."""
    opps = fetch_opportunities()
    rejected = count_rejected_results()
    saved = len(opps)
    total_evaluated = saved + rejected
    rate = (saved / total_evaluated * 100) if total_evaluated else 0.0

    console.print("[bold blue]✅ Quality Report — Opportunity Radar[/bold blue]\n")

    console.print(Panel(
        f"[bold]Oportunidades salvas:[/bold] {saved}\n"
        f"[bold]Resultados rejeitados:[/bold] {rejected}\n"
        f"[bold]Taxa de aproveitamento:[/bold] {rate:.1f}%",
        title="Resumo de qualidade",
        border_style="blue",
    ))

    saved_domains = count_saved_domains()
    if saved_domains:
        console.print("\n[bold]Top domínios salvos[/bold]")
        for domain, cnt in list(saved_domains.items())[:8]:
            console.print(f"  • {domain}: {cnt}")

    rejected_domains = count_rejected_domains()
    if rejected_domains:
        console.print("\n[bold]Top domínios rejeitados[/bold]")
        for domain, cnt in list(rejected_domains.items())[:8]:
            console.print(f"  • {domain}: {cnt}")

    low_conf = [o for o in opps if o.confidence_score < 70]
    if low_conf:
        console.print(f"\n[bold yellow]Oportunidades com confidence < 70:[/bold yellow] {len(low_conf)}")
        for opp in low_conf[:5]:
            console.print(
                f"  • {opp.normalized_card_name} ({opp.confidence_score}) — "
                f"{opp.opportunity_type.value}"
            )

    console.print("\n[bold]Recomendações[/bold]")
    recommendations: list[str] = []
    if rate < 30 and rejected > 0:
        recommendations.append("Use --strict --buyer-only para focar em demanda real de compra.")
    if rate > 60:
        recommendations.append("Taxa alta — considere ampliar watchlist com --max-queries.")
    if any("dicio" in d for d in rejected_domains):
        recommendations.append("Dicionários estão sendo bloqueados corretamente — mantenha blocked_domains.yml.")
    if low_conf:
        recommendations.append(
            f"{len(low_conf)} oportunidade(s) com confidence baixo — revise com quality-report após --strict."
        )
    if not recommendations:
        recommendations.append("Filtros operando — rode scan com --strict para máxima precisão.")

    for tip in recommendations:
        console.print(f"  • {tip}")
