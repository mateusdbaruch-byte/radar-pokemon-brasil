"""Gráficos Plotly — tema claro azul/cinza."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

CHART_COLORS = ["#2563EB", "#3B82F6", "#60A5FA", "#93C5FD", "#1D4ED8", "#64748B", "#94A3B8"]

LAYOUT_DEFAULTS = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color="#1E293B", size=12),
    margin=dict(l=20, r=20, t=40, b=20),
    colorway=CHART_COLORS,
)


def _apply_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(title=dict(text=title, font=dict(size=14, color="#1E40AF")), **LAYOUT_DEFAULTS)
    fig.update_xaxes(gridcolor="#F1F5F9", linecolor="#E2E8F0")
    fig.update_yaxes(gridcolor="#F1F5F9", linecolor="#E2E8F0")
    return fig


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str, orientation: str = "v") -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Sem dados", showarrow=False, font=dict(color="#64748B"))
        return _apply_layout(fig, title)
    if orientation == "h":
        fig = px.bar(df, x=y, y=x, orientation="h", color_discrete_sequence=CHART_COLORS)
    else:
        fig = px.bar(df, x=x, y=y, color_discrete_sequence=CHART_COLORS)
    return _apply_layout(fig, title)


def line_chart(df: pd.DataFrame, x: str, y: str, title: str) -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Sem dados suficientes para evolução diária", showarrow=False)
        return _apply_layout(fig, title)
    fig = px.line(df, x=x, y=y, markers=True, color_discrete_sequence=[CHART_COLORS[0]])
    fig.update_traces(line=dict(width=2))
    return _apply_layout(fig, title)


def pie_chart(df: pd.DataFrame, names: str, values: str, title: str) -> go.Figure:
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="Sem dados", showarrow=False)
        return _apply_layout(fig, title)
    fig = px.pie(df, names=names, values=values, color_discrete_sequence=CHART_COLORS, hole=0.35)
    return _apply_layout(fig, title)
