"""Dashboard Streamlit — Radar Pokémon Brasil (webapp + leitura SQLite)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.dashboard import actions, charts, components, config_info, data

st.set_page_config(
    page_title="Radar Pokémon Brasil",
    page_icon="🇧🇷",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = [
    "Início",
    "Visão Geral",
    "Opportunity Inbox",
    "Card Radar",
    "Query Performance",
    "Rejeitados",
    "Orçamento",
    "Saúde das Fontes",
    "Execuções",
    "Configuração",
]

NAV_TARGETS = {
    "oportunidades": "Opportunity Inbox",
    "card_radar": "Card Radar",
    "orcamento": "Orçamento",
    "performance": "Query Performance",
}


def navigate_to(page: str) -> None:
    st.session_state.nav_page = page
    st.rerun()


def render_serpapi_banner() -> None:
    if not actions.serpapi_configured():
        st.warning(
            "⚠️ **SerpAPI não configurada.** O botão *Rodar Radar* não funcionará até você "
            "adicionar `SERPAPI_KEY` nos Secrets (Replit) ou no `.env` local. "
            "Abra **Configuração** para mais detalhes."
        )


def render_radar_result(result: dict) -> None:
    if not result.get("ok"):
        st.error(result.get("error", "Erro desconhecido ao rodar o radar."))
        return

    if result.get("budget_stopped"):
        st.warning(result.get("message", "Orçamento diário atingido."))
    else:
        st.success(result.get("message", "Scan concluído."))

    components.metric_row([
        ("Queries executadas", result.get("queries_executed", 0), None),
        ("Salvos", result.get("saved", 0), None),
        ("Mesclados", result.get("merged", 0), None),
        ("Rejeitados", result.get("rejected", 0), None),
    ])
    st.caption(f"Scan run: `{result.get('scan_run_id', '')[:8]}…`")


def render_home() -> None:
    components.page_header(
        "Início",
        "Painel simples — clique nos botões abaixo, sem precisar de terminal",
    )
    render_serpapi_banner()

    if data.has_any_data():
        m = data.overview_metrics()
        components.metric_row([
            ("Oportunidades", m["total"], None),
            ("Últimos 7 dias", m["last_7_days"], None),
            ("Live", m["live"], None),
        ])
    else:
        st.info(
            "Ainda não há dados no banco. Configure a SerpAPI (se necessário) e clique em "
            "**Rodar Radar Manualmente** abaixo."
        )

    components.section_title("Navegação rápida")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📥 Ver oportunidades", use_container_width=True, type="secondary"):
            navigate_to(NAV_TARGETS["oportunidades"])
        if st.button("📊 Ver Orçamento", use_container_width=True, type="secondary"):
            navigate_to(NAV_TARGETS["orcamento"])
    with c2:
        if st.button("🎯 Ver Card Radar", use_container_width=True, type="secondary"):
            navigate_to(NAV_TARGETS["card_radar"])
        if st.button("📈 Ver Performance das Queries", use_container_width=True, type="secondary"):
            navigate_to(NAV_TARGETS["performance"])

    components.section_title("Rodar Radar Manualmente")
    st.caption(
        "Equivalente a: "
        "`python -m src.main run-daily-radar --cards Charizard,Umbreon,Mew "
        "--daily-budget 20 --budget-mode economy`"
    )

    if st.button("🔄 Rodar Radar Manualmente", type="primary", use_container_width=True):
        if not actions.serpapi_configured():
            st.session_state.last_radar_result = {
                "ok": False,
                "error": (
                    "SerpAPI não configurada. Adicione SERPAPI_KEY nos Secrets "
                    "do Replit antes de rodar o radar."
                ),
            }
        else:
            with st.spinner("Executando radar… isso pode levar alguns minutos. Aguarde."):
                st.session_state.last_radar_result = actions.run_manual_daily_radar()
        st.rerun()

    if st.session_state.get("last_radar_result"):
        render_radar_result(st.session_state.last_radar_result)


def render_config() -> None:
    components.page_header("Configuração", "Status do ambiente e parâmetros do radar")
    cfg = config_info.app_config_summary()

    if cfg["serpapi_configured"]:
        st.success("✅ SerpAPI configurada (`SERPAPI_KEY` encontrada no ambiente).")
    else:
        st.error(
            "❌ SerpAPI **não** configurada. No Replit: aba **Secrets** → adicione "
            "`SERPAPI_KEY` com sua chave. Localmente: copie `.env.example` para `.env`."
        )

    components.metric_row([
        ("Orçamento diário", cfg["daily_budget"], "SERPAPI_DAILY_BUDGET"),
        ("Orçamento mensal", cfg["monthly_budget"], "SERPAPI_MONTHLY_BUDGET"),
        ("Provedor busca", cfg["web_search_provider"], "WEB_SEARCH_PROVIDER"),
    ])

    components.section_title("Cartas monitoradas")
    st.caption(f"Arquivo: `{cfg['watchlist_path']}`")
    if cfg["watched_cards"]:
        rows = pd.DataFrame(cfg["watched_cards"], columns=["carta", "prioridade"])
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma carta em `config/watchlist.yml`.")

    components.section_title("Perfis de busca")
    for profile in cfg["profiles"]:
        with st.expander(f"`{profile['id']}` — {profile['label']}", expanded=False):
            st.markdown(profile["description"])

    st.divider()
    st.markdown(
        "**Segurança:** nunca coloque a chave SerpAPI no código ou no GitHub. "
        "Use apenas Secrets / variáveis de ambiente."
    )


def render_overview() -> None:
    components.page_header("Visão Geral", "Resumo do Opportunity Radar")
    if not data.has_any_data():
        components.empty_state()
        return

    m = data.overview_metrics()
    components.metric_row([
        ("Oportunidades", m["total"], None),
        ("Novas (status)", m["new_status"], None),
        ("Últimos 7 dias", m["last_7_days"], None),
        ("Live", m["live"], None),
    ])
    components.metric_row([
        ("Buyer demand", m["buyer_demand"], None),
        ("Seller supply", m["seller_supply"], None),
        ("Price reference", m["price_reference"], None),
        ("Urgent sale", m["urgent_sale"], None),
    ])
    components.metric_row([
        ("Opt-in", m["opt_in"], None),
        ("SerpAPI hoje", f"{m['budget_today']}/{m['budget_daily_limit']}", "Buscas API hoje"),
        ("SerpAPI mês", f"{m['budget_month']}/{m['budget_monthly_limit']}", "Buscas API 30d"),
    ])

    opps = data.load_opportunities()
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            charts.pie_chart(
                data.count_series(opps, "profile"),
                "profile", "count", "Por perfil",
            ),
            use_container_width=True,
        )
    with col2:
        st.plotly_chart(
            charts.pie_chart(
                data.count_series(opps, "opportunity_type"),
                "opportunity_type", "count", "Por tipo",
            ),
            use_container_width=True,
        )

    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(
            charts.bar_chart(
                data.count_series(opps, "normalized_card_name"),
                "normalized_card_name", "count", "Por carta",
            ),
            use_container_width=True,
        )
    with col4:
        st.plotly_chart(
            charts.bar_chart(
                data.count_series(opps, "domain"),
                "domain", "count", "Por domínio",
                orientation="h",
            ),
            use_container_width=True,
        )

    daily = data.opportunities_by_day()
    if len(daily) >= 2:
        st.plotly_chart(
            charts.line_chart(daily, "date", "count", "Evolução diária de oportunidades"),
            use_container_width=True,
        )


def render_inbox() -> None:
    components.page_header("Opportunity Inbox", "Oportunidades salvas com filtros")
    df = data.load_opportunities()
    if df.empty:
        components.empty_state()
        return

    with st.expander("Filtros", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        cards = ["Todos"] + data.distinct_cards()
        card_f = c1.selectbox("Carta", cards, key="inbox_card")
        profiles = ["Todos"] + sorted(df["profile"].dropna().unique().tolist()) if "profile" in df.columns else ["Todos"]
        profile_f = c2.selectbox("Perfil", profiles, key="inbox_profile")
        types = ["Todos"] + sorted(df["opportunity_type"].dropna().unique().tolist())
        type_f = c3.selectbox("Tipo", types, key="inbox_type")
        min_score = c4.slider("Score mínimo", 0, 100, 0, key="inbox_score")

        c5, c6, c7, c8 = st.columns(4)
        domains = ["Todos"] + sorted(df["domain"].dropna().unique().tolist())
        domain_f = c5.selectbox("Domínio", domains, key="inbox_domain")
        statuses = ["Todos"] + sorted(df["status"].dropna().unique().tolist()) if "status" in df.columns else ["Todos"]
        status_f = c6.selectbox("Status", statuses, key="inbox_status")
        reviews = ["Todos"] + sorted(df["human_review"].dropna().unique().tolist()) if "human_review" in df.columns else ["Todos"]
        review_f = c7.selectbox("Revisão humana", reviews, key="inbox_review")
        modes = ["Todos"] + sorted(df["data_mode"].dropna().unique().tolist()) if "data_mode" in df.columns else ["Todos"]
        mode_f = c8.selectbox("data_mode", modes, key="inbox_mode")

    filtered = df.copy()
    if card_f != "Todos":
        filtered = filtered[
            (filtered["normalized_card_name"] == card_f)
            | (filtered["card_name_detected"] == card_f)
        ]
    if profile_f != "Todos" and "profile" in filtered.columns:
        filtered = filtered[filtered["profile"] == profile_f]
    if type_f != "Todos":
        filtered = filtered[filtered["opportunity_type"] == type_f]
    if domain_f != "Todos":
        filtered = filtered[filtered["domain"] == domain_f]
    if status_f != "Todos" and "status" in filtered.columns:
        filtered = filtered[filtered["status"] == status_f]
    if review_f != "Todos" and "human_review" in filtered.columns:
        filtered = filtered[filtered["human_review"] == review_f]
    if mode_f != "Todos" and "data_mode" in filtered.columns:
        filtered = filtered[filtered["data_mode"] == mode_f]
    filtered = filtered[filtered["opportunity_score"] >= min_score]

    display_cols = [
        c for c in [
            "display_id", "normalized_card_name", "profile", "opportunity_type",
            "opportunity_score", "confidence_score", "urgency_score", "domain",
            "source", "data_mode", "status", "human_review", "why_saved",
            "evidence_text", "url", "collected_at",
        ]
        if c in filtered.columns
    ]
    rename = {
        "display_id": "id",
        "normalized_card_name": "card",
    }
    show = filtered[display_cols].rename(columns=rename)
    st.caption(f"{len(show)} oportunidade(s)")
    st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        column_config={
            "url": st.column_config.LinkColumn("url", display_text="Abrir"),
            "opportunity_score": st.column_config.NumberColumn(format="%d"),
            "confidence_score": st.column_config.NumberColumn(format="%d"),
            "urgency_score": st.column_config.NumberColumn(format="%d"),
        },
    )


def render_card_radar() -> None:
    components.page_header("Card Radar", "Visão consolidada por carta")
    cards = data.distinct_cards()
    if not cards:
        components.empty_state()
        return

    card = st.selectbox("Carta", cards, key="radar_card")
    summary = data.card_radar_summary(card)
    if not summary.get("found"):
        st.info(f"Nenhuma oportunidade para {card}.")
        return

    components.metric_row([
        ("Demanda", summary["buyer_demand_count"], None),
        ("Oferta", summary["seller_supply_count"], None),
        ("Referência", summary["market_reference_count"], None),
        ("Urgente", summary["urgent_sale_count"], None),
        ("MOS", summary["market_opportunity_score"], "Market Opportunity Score"),
    ])

    if summary["strategic_reading"]:
        components.section_title("Leitura estratégica")
        for line in summary["strategic_reading"]:
            st.markdown(f"- {line}")

    if summary["top_domains"]:
        components.section_title("Domínios principais")
        for domain, cnt in summary["top_domains"]:
            st.markdown(f"- **{domain}**: {cnt}")

    components.section_title("Top oportunidades")
    top = summary["top_opportunities"]
    cols_show = [c for c in [
        "opportunity_type", "profile", "opportunity_score", "domain", "url", "evidence_text",
    ] if c in top.columns]
    st.dataframe(
        top[cols_show],
        use_container_width=True,
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("url", display_text="Abrir")},
    )


def render_query_performance() -> None:
    components.page_header("Query Performance", "Aproveitamento por query executada")
    df = data.load_query_runs()
    if df.empty:
        components.empty_state("Sem query_runs ainda. Rode run-daily-radar ou scan-opportunities.")
        return

    total_saved = int(df["saved_count"].sum())
    total_rej = int(df["rejected_count"].sum())
    total_to = int(df["timeout_count"].sum()) if "timeout_count" in df.columns else 0
    components.metric_row([
        ("Queries", len(df), None),
        ("Salvos", total_saved, None),
        ("Rejeitados", total_rej, None),
        ("Timeouts", total_to, None),
    ])

    best = df.nlargest(5, "success_rate")
    worst = df[df["success_rate"].notna()].nsmallest(5, "success_rate")
    high_rej = df.nlargest(5, "rejected_count")
    timeouts = df[df["timeout_count"] > 0] if "timeout_count" in df.columns else df.iloc[0:0]

    col1, col2 = st.columns(2)
    with col1:
        components.section_title("Melhores queries")
        st.dataframe(best[["profile", "card", "query", "success_rate", "saved_count"]], hide_index=True)
    with col2:
        components.section_title("Piores queries")
        st.dataframe(worst[["profile", "card", "query", "success_rate", "rejected_count"]], hide_index=True)

    col3, col4 = st.columns(2)
    with col3:
        components.section_title("Mais rejeitados")
        st.dataframe(high_rej[["profile", "query", "rejected_count", "saved_count"]], hide_index=True)
    with col4:
        components.section_title("Com timeout")
        if timeouts.empty:
            st.caption("Nenhum timeout registrado.")
        else:
            st.dataframe(timeouts[["profile", "query", "timeout_count"]], hide_index=True)

    show_cols = [c for c in [
        "profile", "card", "query", "total_results", "saved_count", "rejected_count",
        "timeout_count", "duration_seconds", "success_rate", "executed_at",
    ] if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)


def render_rejected() -> None:
    components.page_header("Rejeitados", "Resultados filtrados pelo agente")
    df = data.load_rejected()
    if df.empty:
        components.empty_state("Sem rejected_results ainda.")
        return

    c1, c2, c3 = st.columns(3)
    reasons = ["Todos"] + sorted(df["reason"].dropna().unique().tolist())
    reason_f = c1.selectbox("Motivo", reasons, key="rej_reason")
    domains = ["Todos"] + sorted(df["domain"].dropna().unique().tolist())
    domain_f = c2.selectbox("Domínio", domains, key="rej_domain")
    profiles = ["Todos"] + sorted(df["profile"].dropna().unique().tolist()) if "profile" in df.columns else ["Todos"]
    profile_f = c3.selectbox("Perfil", profiles, key="rej_profile")

    filtered = df.copy()
    if reason_f != "Todos":
        filtered = filtered[filtered["reason"].str.contains(reason_f[:40], case=False, na=False)]
    if domain_f != "Todos":
        filtered = filtered[filtered["domain"] == domain_f]
    if profile_f != "Todos" and "profile" in filtered.columns:
        filtered = filtered[filtered["profile"] == profile_f]

    cols = [c for c in [
        "query", "domain", "reason", "title", "snippet", "url",
        "profile", "human_review", "rejected_at",
    ] if c in filtered.columns]
    st.dataframe(
        filtered[cols],
        use_container_width=True,
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("url", display_text="Abrir")},
    )


def render_budget() -> None:
    components.page_header("Orçamento SerpAPI", "Consumo de buscas API")
    summary = data.budget_summary()

    components.metric_row([
        ("Hoje (API)", f"{summary['today']}/{summary['daily_limit']}", None),
        ("7 dias", summary["week"], None),
        ("Mês (30d)", f"{summary['month']}/{summary['monthly_limit']}", None),
        ("Cache hoje", summary["cached_today"], None),
        ("Estimativa/mês", summary["monthly_pace"], "Ritmo baseado em 7d"),
    ])

    col1, col2 = st.columns(2)
    with col1:
        prof = summary["by_profile"]
        if prof:
            pdf = pd.DataFrame(list(prof.items()), columns=["profile", "count"])
            st.plotly_chart(charts.bar_chart(pdf, "profile", "count", "Consumo por perfil (30d)"), use_container_width=True)
        else:
            st.caption("Sem consumo por perfil.")
    with col2:
        cards = summary["by_card"]
        if cards:
            cdf = pd.DataFrame(list(cards.items()), columns=["card", "count"]).head(10)
            st.plotly_chart(charts.bar_chart(cdf, "card", "count", "Consumo por carta (30d)"), use_container_width=True)
        else:
            st.caption("Sem consumo por carta.")

    queries = summary["by_query"]
    if queries:
        components.section_title("Top queries (30d)")
        qdf = pd.DataFrame(list(queries.items()), columns=["query", "count"]).head(15)
        st.dataframe(qdf, use_container_width=True, hide_index=True)


def render_health() -> None:
    components.page_header("Saúde das Fontes", "Último status de cada conector")
    df = data.load_connector_health()
    if df.empty:
        components.empty_state("Sem registros em connector_health. Rode: python -m src.main doctor")
        return

    cols = [c for c in [
        "source", "status", "data_mode", "http_status", "message", "tested_at", "next_action",
    ] if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


def render_scan_runs() -> None:
    components.page_header("Execuções", "Histórico de scan_runs (agente incremental)")
    df = data.load_scan_runs()
    if df.empty:
        components.empty_state("Sem scan_runs ainda. Rode run-daily-radar.")
        return

    cols = [c for c in [
        "started_at", "finished_at", "status", "profiles", "cards", "budget_mode",
        "query_budget", "queries_planned", "queries_executed",
        "opportunities_saved", "rejected_count", "timeout_count", "run_type",
    ] if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


def main() -> None:
    components.apply_theme()
    components.app_branding()

    if "nav_page" not in st.session_state:
        st.session_state.nav_page = PAGES[0]

    page = st.sidebar.radio(
        "Navegação",
        PAGES,
        index=PAGES.index(st.session_state.nav_page) if st.session_state.nav_page in PAGES else 0,
        label_visibility="collapsed",
    )
    st.session_state.nav_page = page
    st.sidebar.caption("SQLite local · radar manual sob demanda")
    if not actions.serpapi_configured():
        st.sidebar.warning("SerpAPI não configurada")

    if not data.database_exists() and page not in ("Início", "Configuração"):
        components.page_header("Radar Pokémon Brasil", "Inteligência de oportunidades para Pokémon TCG no Brasil")
        components.empty_state(
            "Banco SQLite não encontrado. Vá em **Início** e clique em **Rodar Radar Manualmente**."
        )
        return

    renderers = {
        "Início": render_home,
        "Visão Geral": render_overview,
        "Opportunity Inbox": render_inbox,
        "Card Radar": render_card_radar,
        "Query Performance": render_query_performance,
        "Rejeitados": render_rejected,
        "Orçamento": render_budget,
        "Saúde das Fontes": render_health,
        "Execuções": render_scan_runs,
        "Configuração": render_config,
    }
    renderers[page]()


if __name__ == "__main__":
    main()
