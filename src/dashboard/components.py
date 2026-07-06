"""Componentes visuais reutilizáveis da dashboard."""

from __future__ import annotations

import streamlit as st

COLORS = {
    "primary": "#2563EB",
    "primary_light": "#3B82F6",
    "bg": "#F8FAFC",
    "card": "#FFFFFF",
    "border": "#E2E8F0",
    "text": "#1E293B",
    "muted": "#64748B",
    "accent_bg": "#EFF6FF",
}

GLOBAL_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        color: #1E293B;
    }
    .block-container {
        padding-top: 1.5rem;
        max-width: 1200px;
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 0.75rem 1rem;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    div[data-testid="stMetric"] label {
        color: #64748B !important;
        font-size: 0.8rem !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #2563EB !important;
        font-weight: 600 !important;
    }
    .radar-header {
        background: linear-gradient(135deg, #EFF6FF 0%, #FFFFFF 100%);
        border: 1px solid #E2E8F0;
        border-radius: 16px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.5rem;
    }
    .radar-header h1 {
        margin: 0;
        font-size: 1.75rem;
        color: #1E40AF;
    }
    .radar-header p {
        margin: 0.25rem 0 0 0;
        color: #64748B;
        font-size: 0.95rem;
    }
    .empty-state {
        background: #EFF6FF;
        border: 1px dashed #93C5FD;
        border-radius: 12px;
        padding: 2rem;
        text-align: center;
        color: #1E40AF;
    }
    .empty-state code {
        background: #FFFFFF;
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.85rem;
    }
    section[data-testid="stSidebar"] {
        background-color: #F8FAFC;
        border-right: 1px solid #E2E8F0;
    }
    section[data-testid="stSidebar"] .stRadio label {
        font-weight: 500;
    }
</style>
"""


def apply_theme() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f'<div class="radar-header"><h1>{title}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )


def app_branding() -> None:
    st.sidebar.markdown("### 🇧🇷 Radar Pokémon Brasil")
    st.sidebar.caption("Inteligência de oportunidades para Pokémon TCG no Brasil")
    st.sidebar.divider()


def metric_row(items: list[tuple[str, str | int, str | None]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value, help_text) in zip(cols, items):
        col.metric(label, value, help=help_text)


def empty_state(message: str | None = None) -> None:
    msg = message or "Sem dados ainda. Rode o agente primeiro pelo terminal."
    st.markdown(
        f"""<div class="empty-state">
        <p><strong>{msg}</strong></p>
        <p style="margin-top:1rem;text-align:left;display:inline-block;">
        <code>python -m src.main next-run-plan --cards Charizard,Umbreon,Mew --daily-budget 20 --budget-mode economy</code><br><br>
        <code>python -m src.main run-daily-radar --cards Charizard,Umbreon,Mew --daily-budget 20 --budget-mode economy</code>
        </p></div>""",
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f"#### {text}")
