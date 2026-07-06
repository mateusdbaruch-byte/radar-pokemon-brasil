"""Relatórios do Opportunity Radar — inbox, report, quality e rejected."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.opportunity_db import (
    count_domains_by_review,
    count_human_reviews,
    count_opportunities_by_profile,
    count_opportunities_by_source,
    count_rejected_by_profile,
    count_rejected_by_reason,
    count_rejected_by_reason_category,
    count_rejected_domains,
    count_rejected_human_reviews,
    count_rejected_results,
    count_saved_domains,
    count_types_by_review,
    count_unreviewed_opportunities,
    fetch_distinct_opportunity_cards,
    fetch_false_negative_rejections,
    fetch_false_positives,
    fetch_opportunities,
    fetch_opportunities_by_card,
    fetch_opportunities_since,
    fetch_queries_with_false_negatives,
    fetch_query_runs,
    fetch_rejected_by_profile,
    fetch_rejected_results,
    fetch_reviewed_opportunities,
    fetch_scan_runs,
    fetch_stale_opportunities,
    fetch_wishlist_leads,
)
from src.opportunity_quality import (
    categorize_rejection_reason,
    extract_domain,
    is_marketplace_domain,
    rejection_label,
    TCG_SPECIALIZED_DOMAINS,
)
from src.query_template_perf import build_template_report
from src.search_profiles import load_search_profiles, profiles_template_config
from src.opportunity_models import Opportunity, OpportunityType
from src.source_registry import SourceAccess, get_source_registry

BUYER_DEMAND_TYPES = frozenset({
    OpportunityType.BUYER_DEMAND,
    OpportunityType.HIGH_INTENT_LEAD,
    OpportunityType.DISCUSSION_SIGNAL,
})

SELLER_SUPPLY_TYPES = frozenset({
    OpportunityType.SELLER_SUPPLY,
    OpportunityType.UNDERPRICED_LISTING,
    OpportunityType.ARBITRAGE_SIGNAL,
})

MARKET_REFERENCE_TYPES = frozenset({
    OpportunityType.PRICE_REFERENCE,
    OpportunityType.SUPPLY_SIGNAL,
})

COUNT_THRESHOLD = 2


@dataclass
class CardUnifiedStats:
    card_name: str
    buyer_demand_count: int = 0
    seller_supply_count: int = 0
    market_reference_count: int = 0
    urgent_sale_count: int = 0
    average_opportunity_score: float = 0.0
    top_domains: list[tuple[str, int]] = field(default_factory=list)
    strategic_reading: list[str] = field(default_factory=list)
    market_opportunity_score: int = 0
    total_opportunities: int = 0
    profiles_seen: list[str] = field(default_factory=list)


def _domain_from_opp(opp: Opportunity) -> str:
    return opp.domain or (extract_domain(opp.url) if opp.url else opp.platform)


def build_card_unified_stats(
    card_name: str,
    opps: list[Opportunity] | None = None,
) -> CardUnifiedStats:
    rows = opps if opps is not None else fetch_opportunities_by_card(card_name)
    stats = CardUnifiedStats(card_name=card_name, total_opportunities=len(rows))
    if not rows:
        stats.strategic_reading = ["dados insuficientes"]
        return stats

    domain_counter: Counter[str] = Counter()
    profile_set: set[str] = set()
    score_sum = 0

    for opp in rows:
        domain = _domain_from_opp(opp)
        if domain:
            domain_counter[domain] += 1
        if opp.profile:
            profile_set.add(opp.profile)

        score_sum += opp.opportunity_score
        opp_type = opp.opportunity_type

        if opp_type in BUYER_DEMAND_TYPES:
            stats.buyer_demand_count += 1
        if opp_type in SELLER_SUPPLY_TYPES:
            stats.seller_supply_count += 1
        if opp_type in MARKET_REFERENCE_TYPES:
            stats.market_reference_count += 1
        if opp_type == OpportunityType.URGENT_SALE:
            stats.urgent_sale_count += 1

    stats.average_opportunity_score = score_sum / len(rows)
    stats.top_domains = domain_counter.most_common(5)
    stats.profiles_seen = sorted(profile_set)
    stats.strategic_reading = compute_strategic_reading(stats)
    stats.market_opportunity_score = compute_market_opportunity_score(stats)
    return stats


def compute_strategic_reading(stats: CardUnifiedStats) -> list[str]:
    readings: list[str] = []
    high = COUNT_THRESHOLD

    if stats.buyer_demand_count >= high and stats.market_reference_count < high:
        readings.append("possível escassez / demanda maior que oferta")
    if stats.buyer_demand_count >= high and stats.seller_supply_count >= high:
        readings.append("mercado ativo / boa liquidez")
    if stats.seller_supply_count >= high and stats.buyer_demand_count < high:
        readings.append("muita oferta / cuidado com preço")
    if stats.market_reference_count >= high:
        readings.append("boa base para precificação")
    if stats.urgent_sale_count >= high:
        readings.append("possível oportunidade de compra")

    if not readings:
        if stats.total_opportunities == 0:
            return ["dados insuficientes"]
        if all(
            c < high
            for c in (
                stats.buyer_demand_count,
                stats.seller_supply_count,
                stats.market_reference_count,
                stats.urgent_sale_count,
            )
        ):
            return ["dados insuficientes"]
    return readings


def compute_market_opportunity_score(stats: CardUnifiedStats) -> int:
    if stats.total_opportunities == 0:
        return 0

    score = 0.0
    score += stats.buyer_demand_count * 15
    score += stats.urgent_sale_count * 20
    score += stats.seller_supply_count * 5
    score += stats.market_reference_count * 8
    score += min(stats.average_opportunity_score, 100) * 0.3
    score += len(stats.top_domains) * 5

    domains = {d for d, _ in stats.top_domains}
    if domains & TCG_SPECIALIZED_DOMAINS:
        score += 15

    return min(int(score), 100)


def build_card_recommendation(stats: CardUnifiedStats) -> str:
    if stats.total_opportunities == 0:
        return "Sem dados — rode run-all-profiles para esta carta."

    if stats.urgent_sale_count >= COUNT_THRESHOLD:
        return "Priorize revisar ofertas urgentes — possível compra abaixo do mercado."
    if stats.buyer_demand_count >= COUNT_THRESHOLD and stats.market_reference_count < COUNT_THRESHOLD:
        return "Demanda detectada com pouca referência — monitore escassez e precifique com cautela."
    if stats.market_reference_count >= COUNT_THRESHOLD:
        return "Use referências de preço coletadas para calibrar compra/venda."
    if stats.seller_supply_count >= COUNT_THRESHOLD:
        return "Há oferta ativa — compare preços antes de comprar."
    return "Continue coletando dados com os três perfis para decisão mais segura."


def _opps_by_profile_and_type(
    opps: list[Opportunity],
    profile: str,
    types: frozenset[OpportunityType],
) -> list[Opportunity]:
    return [
        o for o in opps
        if o.opportunity_type in types
        and (o.profile == profile or (not o.profile and profile == ""))
    ]


def _best_links(opps: list[Opportunity], limit: int = 5) -> list[Opportunity]:
    return sorted(opps, key=lambda o: o.opportunity_score, reverse=True)[:limit]


def _action_style(score: int) -> str:
    if score >= 80:
        return "bold green"
    if score >= 60:
        return "yellow"
    return "dim"


def _review_label(review: str) -> str:
    if review == "relevant":
        return "[green]relevant[/green]"
    if review == "irrelevant":
        return "[red]irrelevant[/red]"
    if review == "maybe":
        return "[yellow]maybe[/yellow]"
    return "[dim]—[/dim]"


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
    table.add_column("ID", justify="right")
    table.add_column("Carta", style="bold")
    table.add_column("Tipo")
    table.add_column("Score", justify="right")
    table.add_column("Conf.", justify="right")
    table.add_column("Domínio", max_width=20)
    table.add_column("Perfil", max_width=14)
    table.add_column("why_saved", max_width=24)
    table.add_column("Revisão", max_width=12)
    table.add_column("Evidência", max_width=24)
    table.add_column("URL", max_width=22)

    for i, opp in enumerate(opps, 1):
        style = _action_style(opp.opportunity_score)
        table.add_row(
            str(i),
            opp.normalized_card_name,
            opp.opportunity_type.value,
            f"[{style}]{opp.opportunity_score}[/{style}]",
            str(opp.confidence_score),
            _domain_from_opp(opp)[:20],
            (opp.profile or "—")[:14],
            (opp.why_saved or "—")[:24],
            _review_label(opp.human_review),
            opp.evidence_text[:24],
            (opp.url or "—")[:22],
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


def display_profiles_summary(console: Console) -> None:
    """Resumo dos perfis de busca disponíveis."""
    profiles = load_search_profiles()
    console.print("[bold blue]📋 Search Profiles — perfis de busca[/bold blue]\n")

    if not profiles:
        console.print(Panel("Nenhum perfil em config/search_profiles.yml", border_style="yellow"))
        return

    for name, profile in profiles.items():
        intents = ", ".join(t.value for t in profile.intent_filter) or "—"
        groups = ", ".join(profile.domain_groups) or "—"
        filters = []
        if profile.strict:
            filters.append("strict")
        if profile.buyer_only:
            filters.append("buyer-only")
        if profile.seller_only:
            filters.append("seller-only")
        filter_label = ", ".join(filters) or "padrão"

        console.print(Panel(
            f"[bold]Descrição:[/bold] {profile.description}\n"
            f"[bold]Templates:[/bold] {len(profile.query_templates)}\n"
            f"[bold]Filtros:[/bold] {filter_label}\n"
            f"[bold]min_confidence:[/bold] {profile.min_confidence}\n"
            f"[bold]intent_filter:[/bold] {intents}\n"
            f"[bold]domain_groups:[/bold] {groups}",
            title=name,
            border_style="blue",
        ))
        console.print()


def display_query_performance_report(console: Console, limit: int = 30) -> None:
    """Relatório de performance por query."""
    runs = fetch_query_runs(limit=limit)
    console.print("[bold blue]📈 Query Performance Report[/bold blue]\n")

    if not runs:
        console.print(
            Panel(
                "Nenhuma query executada ainda. Rode scan com --profile ou profile-quality-test.",
                border_style="yellow",
            )
        )
        return

    table = Table(show_lines=True)
    table.add_column("Perfil", max_width=14)
    table.add_column("Carta")
    table.add_column("Query", max_width=28)
    table.add_column("Analis.", justify="right")
    table.add_column("Salvos", justify="right")
    table.add_column("Rej.", justify="right")
    table.add_column("TO", justify="right")
    table.add_column("Taxa", justify="right")
    table.add_column("Domínios", max_width=20)

    for run in runs:
        total = run.saved_count + run.rejected_count
        rate = (run.saved_count / total * 100) if total else 0.0
        table.add_row(
            run.profile or "—",
            run.card,
            run.query[:28],
            str(run.total_results),
            str(run.saved_count),
            str(run.rejected_count),
            str(run.timeout_count),
            f"{rate:.0f}%",
            (run.domains_found or "—")[:20],
        )
    console.print(table)


def display_rejected_inbox(console: Console, limit: int = 20) -> None:
    """Lista resultados rejeitados para revisão."""
    rows = fetch_rejected_results(limit=limit)
    console.print("[bold blue]🗑️ Rejected Inbox[/bold blue]\n")

    if not rows:
        console.print(Panel("Nenhum resultado rejeitado.", border_style="yellow"))
        return

    console.print(
        "[dim]Use mark-rejected --id N --review false_negative|correct_rejection[/dim]\n"
    )

    table = Table(show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Query", max_width=22)
    table.add_column("Domínio", max_width=16)
    table.add_column("Título", max_width=22)
    table.add_column("Motivo", max_width=24)
    table.add_column("Revisão", max_width=12)
    table.add_column("URL", max_width=18)

    for i, row in enumerate(rows, 1):
        domain = extract_domain(row.url) if row.url else "—"
        label = categorize_rejection_reason(row.reason, row.reason_category)
        table.add_row(
            str(i),
            row.query[:22],
            domain[:16],
            row.title[:22],
            label[:24],
            row.human_review or "—",
            (row.url or "—")[:18],
        )
    console.print(table)


def display_rejected_report(console: Console, limit: int = 10) -> None:
    """Relatório de resultados rejeitados pelo filtro de qualidade."""
    total = count_rejected_results()
    console.print("[bold blue]🚫 Rejected Results Report[/bold blue]\n")

    if total == 0:
        console.print(Panel("Nenhum resultado rejeitado ainda.", border_style="yellow"))
        return

    console.print(f"[bold]Total rejeitados:[/bold] {total}\n")

    by_profile = count_rejected_by_profile()
    if by_profile:
        console.print("[bold]Rejeições por perfil[/bold]")
        for profile, cnt in by_profile.items():
            console.print(f"  • {profile or '—'}: {cnt}")

    by_category = count_rejected_by_reason_category()
    if by_category:
        console.print("\n[bold]Motivos por categoria[/bold]")
        for category, cnt in list(by_category.items())[:10]:
            console.print(f"  • {rejection_label(category)}: {cnt}")
    else:
        by_reason = count_rejected_by_reason()
        console.print("\n[bold]Principais motivos[/bold]")
        for reason, cnt in list(by_reason.items())[:8]:
            label = categorize_rejection_reason(reason)
            console.print(f"  • {label}: {cnt}")

    by_domain = count_rejected_domains()
    if by_domain:
        console.print("\n[bold]Domínios mais rejeitados[/bold]")
        for domain, cnt in list(by_domain.items())[:8]:
            console.print(f"  • {domain}: {cnt}")

    market_ref_rejected = fetch_rejected_by_profile("market_reference", limit=limit)
    marketplace_rows = [
        r for r in market_ref_rejected
        if r.url and is_marketplace_domain(r.url)
    ]
    if marketplace_rows:
        console.print(
            "\n[bold yellow]Marketplaces rejeitados em market_reference[/bold yellow]"
        )
        mr_table = Table(show_lines=True)
        mr_table.add_column("Domínio", max_width=18)
        mr_table.add_column("Motivo", max_width=28)
        mr_table.add_column("Título", max_width=24)
        mr_table.add_column("Ajuste", max_width=28)
        for row in marketplace_rows[:limit]:
            domain = extract_domain(row.url)
            label = categorize_rejection_reason(row.reason, row.reason_category)
            tip = _rejection_adjustment_tip(row.reason_category, domain)
            mr_table.add_row(
                domain[:18],
                label[:28],
                row.title[:24],
                tip[:28],
            )
        console.print(mr_table)

    examples = fetch_rejected_results(limit=limit)
    if examples:
        console.print("\n[bold]Exemplos de rejeição[/bold]\n")
        table = Table(show_lines=True)
        table.add_column("Perfil", max_width=14)
        table.add_column("Categoria", max_width=22)
        table.add_column("Motivo", max_width=28)
        table.add_column("Título", max_width=24)
        table.add_column("URL", max_width=22)
        for row in examples:
            label = categorize_rejection_reason(row.reason, row.reason_category)
            table.add_row(
                (row.profile or "—")[:14],
                label[:22],
                row.reason[:28],
                row.title[:24],
                (row.url or "—")[:22],
            )
        console.print(table)


def _rejection_adjustment_tip(reason_category: str, domain: str) -> str:
    if reason_category == "no_intent":
        return "Listagem ML/OLX/Shopee pode ser referência sem verbo"
    if reason_category == "intent_not_allowed":
        return "Classificar como price_reference no perfil"
    if reason_category == "no_tcg_context":
        return "Incluir 'carta pokemon' na query ou snippet"
    if reason_category == "no_card":
        return "Verificar se título menciona a carta monitorada"
    if reason_category == "domain_outside_profile":
        return f"Adicionar {domain} ao domain_group do perfil"
    return "Revisar rejected-inbox para falso negativo"


def display_review_opportunities(console: Console, limit: int = 50) -> None:
    """Lista oportunidades para revisão manual humana."""
    opps = fetch_opportunities(limit=limit)
    console.print("[bold blue]🔍 Review Opportunities — revisão manual[/bold blue]\n")

    if not opps:
        console.print(
            Panel(
                "Nenhuma oportunidade. Rode scan-quality-test ou scan-opportunities primeiro.",
                border_style="yellow",
            )
        )
        return

    console.print(
        "[dim]Use mark-opportunity --id N --review relevant|irrelevant|maybe "
        "(N = ID da tabela abaixo)[/dim]\n"
    )

    table = Table(show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Carta", style="bold")
    table.add_column("Tipo")
    table.add_column("Score", justify="right")
    table.add_column("Conf.", justify="right")
    table.add_column("Domínio", max_width=18)
    table.add_column("Revisão")
    table.add_column("Evidência", max_width=30)
    table.add_column("URL", max_width=24)

    for i, opp in enumerate(opps, 1):
        table.add_row(
            str(i),
            opp.normalized_card_name,
            opp.opportunity_type.value,
            str(opp.opportunity_score),
            str(opp.confidence_score),
            _domain_from_opp(opp)[:18],
            opp.human_review or "—",
            opp.evidence_text[:30],
            (opp.url or "—")[:24],
        )
    console.print(table)

    unreviewed = count_unreviewed_opportunities()
    reviewed_count = len(fetch_reviewed_opportunities())
    console.print(
        f"\n[dim]Sem revisão: {unreviewed} | Revisadas: {reviewed_count}[/dim]"
    )


def display_precision_report(console: Console) -> None:
    """Relatório de precisão baseado em revisão humana."""
    reviews = count_human_reviews()
    rejected_reviews = count_rejected_human_reviews()
    total_reviewed = sum(reviews.values())
    total_rejected_reviewed = sum(rejected_reviews.values())
    relevant = reviews.get("relevant", 0)
    irrelevant = reviews.get("irrelevant", 0)
    maybe = reviews.get("maybe", 0)
    false_negatives = rejected_reviews.get("false_negative", 0)
    precision = (relevant / total_reviewed * 100) if total_reviewed else 0.0

    console.print("[bold blue]🎯 Precision Report — revisão humana[/bold blue]\n")

    if total_reviewed == 0 and total_rejected_reviewed == 0:
        console.print(
            Panel(
                "Nenhuma revisão humana ainda.\n\n"
                "  • mark-opportunity --id 1 --review relevant\n"
                "  • mark-rejected --id 1 --review false_negative",
                border_style="yellow",
                title="Sem dados de revisão",
            )
        )
        return

    panel_lines = []
    if total_reviewed:
        panel_lines.extend([
            f"[bold]Oportunidades revisadas:[/bold] {total_reviewed}",
            f"[bold]Relevantes:[/bold] {relevant}",
            f"[bold]Irrelevantes:[/bold] {irrelevant}",
            f"[bold]Talvez:[/bold] {maybe}",
            f"[bold]Precisão estimada:[/bold] {precision:.1f}% (relevantes / revisados)",
        ])
    if total_rejected_reviewed:
        panel_lines.extend([
            f"[bold]Rejeitados revisados:[/bold] {total_rejected_reviewed}",
            f"[bold]Possíveis falsos negativos:[/bold] {false_negatives}",
        ])
    console.print(Panel(
        "\n".join(panel_lines),
        title="Resumo de precisão",
        border_style="blue",
    ))

    if false_negatives:
        from src.opportunity_db import count_rejected_domains_by_review
        fn_domains = count_rejected_domains_by_review("false_negative")
        if fn_domains:
            console.print("\n[bold yellow]Domínios com falsos negativos[/bold yellow]")
            for domain, cnt in list(fn_domains.items())[:8]:
                console.print(f"  • {domain}: {cnt}")

        bad_queries = fetch_queries_with_false_negatives(limit=5)
        if bad_queries:
            console.print("\n[bold yellow]Queries rejeitando coisa boa[/bold yellow]")
            for q in bad_queries:
                console.print(f"  • {q[:70]}")

        fn_examples = fetch_false_negative_rejections(limit=5)
        if fn_examples:
            console.print("\n[bold]Exemplos de falsos negativos[/bold]\n")
            fn_table = Table(show_lines=True)
            fn_table.add_column("Query", max_width=24)
            fn_table.add_column("Domínio", max_width=16)
            fn_table.add_column("Motivo", max_width=28)
            for row in fn_examples:
                fn_table.add_row(
                    row.query[:24],
                    extract_domain(row.url)[:16],
                    categorize_rejection_reason(row.reason, row.reason_category)[:28],
                )
            console.print(fn_table)

    if total_reviewed == 0:
        return

    good_domains = count_domains_by_review("relevant")
    if good_domains:
        console.print("\n[bold green]Domínios com mais relevantes[/bold green]")
        for domain, cnt in list(good_domains.items())[:8]:
            console.print(f"  • {domain}: {cnt}")

    bad_domains = count_domains_by_review("irrelevant")
    if bad_domains:
        console.print("\n[bold red]Domínios com mais irrelevantes[/bold red]")
        for domain, cnt in list(bad_domains.items())[:8]:
            console.print(f"  • {domain}: {cnt}")

    irrelevant_types = count_types_by_review("irrelevant")
    if irrelevant_types:
        console.print("\n[bold]Tipos de oportunidade com mais erro[/bold]")
        for opp_type, cnt in list(irrelevant_types.items())[:8]:
            console.print(f"  • {opp_type}: {cnt}")

    false_positives = fetch_false_positives(limit=5)
    if false_positives:
        console.print("\n[bold]Exemplos de falsos positivos[/bold]\n")
        fp_table = Table(show_lines=True)
        fp_table.add_column("Carta")
        fp_table.add_column("Tipo")
        fp_table.add_column("Score", justify="right")
        fp_table.add_column("Domínio", max_width=18)
        fp_table.add_column("Evidência", max_width=30)
        for opp in false_positives:
            fp_table.add_row(
                opp.normalized_card_name,
                opp.opportunity_type.value,
                str(opp.opportunity_score),
                _domain_from_opp(opp)[:18],
                opp.evidence_text[:30],
            )
        console.print(fp_table)


def display_quality_report(console: Console) -> None:
    """Relatório de qualidade — aproveitamento e recomendações."""
    opps = fetch_opportunities()
    rejected = count_rejected_results()
    saved = len(opps)
    total_evaluated = saved + rejected
    rate = (saved / total_evaluated * 100) if total_evaluated else 0.0

    reviews = count_human_reviews()
    total_reviewed = sum(reviews.values())
    relevant = reviews.get("relevant", 0)
    unreviewed = count_unreviewed_opportunities()
    precision = (relevant / total_reviewed * 100) if total_reviewed else None

    console.print("[bold blue]✅ Quality Report — Opportunity Radar[/bold blue]\n")

    panel_lines = [
        f"[bold]Oportunidades salvas:[/bold] {saved}",
        f"[bold]Resultados rejeitados:[/bold] {rejected}",
        f"[bold]Taxa de aproveitamento:[/bold] {rate:.1f}%",
        f"[bold]Sem revisão humana:[/bold] {unreviewed}",
        f"[bold]Revisadas:[/bold] {total_reviewed}",
    ]
    if precision is not None:
        panel_lines.append(f"[bold]Precisão estimada (humana):[/bold] {precision:.1f}%")
    console.print(Panel(
        "\n".join(panel_lines),
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

    good_domains = count_domains_by_review("relevant")
    if good_domains:
        console.print("\n[bold green]Domínios bons (relevantes na revisão)[/bold green]")
        for domain, cnt in list(good_domains.items())[:5]:
            console.print(f"  • {domain}: {cnt}")

    bad_domains = count_domains_by_review("irrelevant")
    if bad_domains:
        console.print("\n[bold red]Domínios ruins (irrelevantes na revisão)[/bold red]")
        for domain, cnt in list(bad_domains.items())[:5]:
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
    if total_reviewed > 0 and precision is not None and precision < 50:
        recommendations.append(
            "Precisão humana baixa — revise falsos positivos com precision-report e ajuste filtros."
        )
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


def display_unified_opportunity_report(console: Console) -> None:
    """Relatório unificado cruzando os três perfis por carta."""
    cards = fetch_distinct_opportunity_cards()
    console.print("[bold blue]🛰️ Unified Opportunity Report — radar híbrido[/bold blue]\n")

    if not cards:
        console.print(
            Panel(
                "Nenhuma oportunidade salva. Rode run-daily-radar primeiro.",
                border_style="yellow",
            )
        )
        return

    last_24h = fetch_opportunities_since(1)
    last_7d = fetch_opportunities_since(7)
    by_profile = count_opportunities_by_profile()

    console.print(Panel(
        f"[bold]Novas (24h):[/bold] {len(last_24h)}\n"
        f"[bold]Últimos 7 dias:[/bold] {len(last_7d)}\n"
        f"[bold]Por perfil:[/bold] "
        + (", ".join(f"{k}={v}" for k, v in by_profile.items()) if by_profile else "—"),
        title="Recência",
        border_style="blue",
    ))

    card_activity: Counter[str] = Counter(o.normalized_card_name for o in last_7d)
    if card_activity:
        console.print("\n[bold]Cartas com mais movimentação (7d)[/bold]")
        for card, cnt in card_activity.most_common(5):
            console.print(f"  • {card}: {cnt}")

    incomplete = []
    for card in cards:
        opps = fetch_opportunities_by_card(card)
        has_ref = any(o.profile == "market_reference" for o in opps)
        if not has_ref:
            incomplete.append(card)
    if incomplete:
        console.print("\n[bold yellow]Cartas sem market_reference[/bold yellow]")
        for card in incomplete:
            console.print(f"  • {card} — priorize perfil market_reference no próximo run")

    all_stats = [build_card_unified_stats(card) for card in cards]
    all_stats.sort(key=lambda s: s.market_opportunity_score, reverse=True)

    table = Table(show_lines=True, title="Visão por carta")
    table.add_column("Carta", style="bold")
    table.add_column("Demanda", justify="right")
    table.add_column("Oferta", justify="right")
    table.add_column("Ref.", justify="right")
    table.add_column("Urgente", justify="right")
    table.add_column("Score méd.", justify="right")
    table.add_column("MOS", justify="right")
    table.add_column("Top domínios", max_width=22)
    table.add_column("Leitura", max_width=28)

    for stats in all_stats:
        domains_label = ", ".join(f"{d}({c})" for d, c in stats.top_domains[:3]) or "—"
        reading = "; ".join(stats.strategic_reading)[:28]
        table.add_row(
            stats.card_name,
            str(stats.buyer_demand_count),
            str(stats.seller_supply_count),
            str(stats.market_reference_count),
            str(stats.urgent_sale_count),
            f"{stats.average_opportunity_score:.0f}",
            str(stats.market_opportunity_score),
            domains_label[:22],
            reading,
        )
    console.print(table)

    console.print("\n[bold]Leitura estratégica detalhada[/bold]")
    for stats in all_stats:
        console.print(f"\n[cyan]{stats.card_name}[/cyan] (MOS={stats.market_opportunity_score})")
        if stats.profiles_seen:
            console.print(f"  Perfis: {', '.join(stats.profiles_seen)}")
        for line in stats.strategic_reading:
            console.print(f"  • {line}")
        console.print(f"  Recomendação: {build_card_recommendation(stats)}")


def display_card_radar(console: Console, card: str) -> None:
    """Visão completa de uma carta no radar híbrido."""
    opps = fetch_opportunities_by_card(card)
    stats = build_card_unified_stats(card, opps)

    console.print(f"[bold blue]📡 Card Radar — {card}[/bold blue]\n")

    if not opps:
        console.print(
            Panel(
                f"Nenhuma oportunidade para {card}. "
                "Rode run-all-profiles --cards {card}.",
                border_style="yellow",
            )
        )
        return

    console.print(Panel(
        f"[bold]Oportunidades:[/bold] {stats.total_opportunities}\n"
        f"[bold]Demanda (buyer):[/bold] {stats.buyer_demand_count}\n"
        f"[bold]Oferta (seller):[/bold] {stats.seller_supply_count}\n"
        f"[bold]Referência mercado:[/bold] {stats.market_reference_count}\n"
        f"[bold]Venda urgente:[/bold] {stats.urgent_sale_count}\n"
        f"[bold]Score médio:[/bold] {stats.average_opportunity_score:.1f}\n"
        f"[bold]Market Opportunity Score:[/bold] {stats.market_opportunity_score}\n"
        f"[bold]Perfis:[/bold] {', '.join(stats.profiles_seen) or '—'}",
        title="Resumo",
        border_style="blue",
    ))

    demand_opps = [o for o in opps if o.opportunity_type in BUYER_DEMAND_TYPES]
    supply_opps = [
        o for o in opps
        if o.opportunity_type in SELLER_SUPPLY_TYPES
        or o.opportunity_type == OpportunityType.URGENT_SALE
    ]
    ref_opps = [o for o in opps if o.opportunity_type in MARKET_REFERENCE_TYPES]

    sections = [
        ("Leads de compra", demand_opps),
        ("Ofertas / vendedores", supply_opps),
        ("Referências de preço", ref_opps),
    ]

    for title, rows in sections:
        console.print(f"\n[bold]{title}[/bold] ({len(rows)})")
        if not rows:
            console.print("  [dim]Nenhum[/dim]")
            continue
        section_table = Table(show_lines=True)
        section_table.add_column("Score", justify="right")
        section_table.add_column("Tipo")
        section_table.add_column("Perfil", max_width=14)
        section_table.add_column("Domínio", max_width=18)
        section_table.add_column("Evidência", max_width=30)
        section_table.add_column("URL", max_width=24)
        for opp in _best_links(rows, limit=5):
            section_table.add_row(
                str(opp.opportunity_score),
                opp.opportunity_type.value,
                (opp.profile or "—")[:14],
                _domain_from_opp(opp)[:18],
                opp.evidence_text[:30],
                (opp.url or "—")[:24],
            )
        console.print(section_table)

    if stats.top_domains:
        console.print("\n[bold]Domínios[/bold]")
        for domain, cnt in stats.top_domains:
            console.print(f"  • {domain}: {cnt}")

    console.print("\n[bold]Melhores links[/bold]")
    for opp in _best_links(opps, limit=5):
        console.print(
            f"  • [{opp.opportunity_score}] {_domain_from_opp(opp)} — "
            f"{opp.opportunity_type.value} — {(opp.url or '—')[:60]}"
        )

    console.print("\n[bold]Leitura estratégica[/bold]")
    for line in stats.strategic_reading:
        console.print(f"  • {line}")

    console.print(f"\n[bold]Recomendação:[/bold] {build_card_recommendation(stats)}")


def display_next_run_plan(
    console: Console,
    plan,
) -> None:
    """Exibe plano de execução antes do run-daily-radar."""
    console.print("[bold blue]📋 Next Run Plan — execução incremental[/bold blue]\n")
    console.print(Panel(
        f"[bold]Cartas:[/bold] {', '.join(plan.cards)}\n"
        f"[bold]Modo:[/bold] {plan.budget_mode.value}\n"
        f"[bold]Orçamento solicitado:[/bold] {plan.daily_budget}\n"
        f"[bold]Orçamento efetivo hoje:[/bold] {plan.effective_budget}\n"
        f"[bold]Queries planejadas:[/bold] {plan.total_planned}\n"
        f"[bold]Estimativa API:[/bold] {plan.api_calls_estimated}\n"
        f"[bold]Cache hits esperados:[/bold] {plan.cache_hits}",
        title="Resumo",
        border_style="blue",
    ))

    for profile_plan in plan.profiles:
        console.print(f"\n[bold cyan]{profile_plan.profile}[/bold cyan] "
                      f"({profile_plan.query_budget} queries)")
        if not profile_plan.queries:
            console.print("  [dim]Nenhuma query alocada[/dim]")
            continue
        table = Table(show_lines=True)
        table.add_column("Carta")
        table.add_column("Query", max_width=40)
        table.add_column("Cache", justify="center")
        for q in profile_plan.queries:
            table.add_row(
                q.card,
                q.query[:40],
                "sim" if q.from_cache else "não",
            )
        console.print(table)


def display_query_template_report(console: Console) -> None:
    """Relatório de performance por template de query."""
    rows = build_template_report(profiles_template_config())
    console.print("[bold blue]📊 Query Template Report[/bold blue]\n")

    if not rows:
        console.print(Panel("Nenhum template configurado.", border_style="yellow"))
        return

    best = [r for r in rows if r.saved > 0][:5]
    worst = sorted(
        [r for r in rows if r.rejected > 0],
        key=lambda r: r.rejected,
        reverse=True,
    )[:5]

    if best:
        console.print("[bold green]Melhores templates[/bold green]")
        for r in best:
            console.print(
                f"  • [{r.profile}] {r.template[:50]} — "
                f"taxa {r.success_rate:.0%} ({r.saved} salvos)"
            )

    if worst:
        console.print("\n[bold red]Templates com mais rejeições[/bold red]")
        for r in worst:
            tip = f" — {r.suggestion}" if r.suggestion else ""
            console.print(
                f"  • [{r.profile}] {r.template[:50]} — "
                f"{r.rejected} rejeitados{tip}"
            )

    console.print("\n[bold]Tabela completa[/bold]\n")
    table = Table(show_lines=True)
    table.add_column("Perfil", max_width=14)
    table.add_column("Template", max_width=32)
    table.add_column("Ativo", justify="center")
    table.add_column("Peso", justify="right")
    table.add_column("Taxa", justify="right")
    table.add_column("Salvos", justify="right")
    table.add_column("Rej.", justify="right")
    table.add_column("Sugestão", max_width=24)
    for r in rows:
        table.add_row(
            r.profile[:14],
            r.template[:32],
            "sim" if r.enabled else "não",
            str(r.priority_weight),
            f"{r.success_rate:.0%}",
            str(r.saved),
            str(r.rejected),
            r.suggestion[:24],
        )
    console.print(table)


def display_stale_opportunities_report(
    console: Console,
    *,
    min_age_days: int = 30,
) -> None:
    """Oportunidades antigas ou com freshness desconhecida."""
    stale = fetch_stale_opportunities(min_age_days=min_age_days)
    console.print("[bold blue]⏳ Stale Opportunities Report[/bold blue]\n")

    if not stale:
        console.print(Panel("Nenhuma oportunidade stale encontrada.", border_style="green"))
        return

    by_status: Counter[str] = Counter(o.freshness_status for o in stale)
    console.print(Panel(
        f"[bold]Total stale/unknown:[/bold] {len(stale)}\n"
        + "\n".join(f"  • {k}: {v}" for k, v in by_status.items()),
        title="Resumo",
        border_style="yellow",
    ))

    table = Table(show_lines=True)
    table.add_column("Carta")
    table.add_column("Perfil", max_width=14)
    table.add_column("Freshness")
    table.add_column("Idade", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Domínio", max_width=18)
    table.add_column("URL", max_width=24)
    for opp in stale[:25]:
        table.add_row(
            opp.normalized_card_name,
            (opp.profile or "—")[:14],
            opp.freshness_status,
            str(opp.age_days if opp.age_days is not None else "—"),
            str(opp.opportunity_score),
            _domain_from_opp(opp)[:18],
            (opp.url or "—")[:24],
        )
    console.print(table)

    runs = fetch_scan_runs(limit=3)
    if runs:
        console.print("\n[bold]Últimos scan_runs[/bold]")
        for run in runs:
            console.print(
                f"  • {run.started_at.date()} {run.status} — "
                f"{run.queries_executed}/{run.queries_planned} queries, "
                f"{run.opportunities_saved} salvos"
            )
