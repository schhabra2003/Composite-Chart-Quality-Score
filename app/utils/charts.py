"""Plotly charts. Minimalist line on a clean grid; no decoration.

All visual constants imported from app.utils.design_system.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.utils.design_system import (
    ADFM_BLUE,
    CHART_BACKGROUND,
    CHART_HEIGHT_SMALL,
    CHART_LINE_WIDTH,
    PASTEL_GREY,
)

GRID = "rgb(238,240,243)"
AXIS = "rgb(120,124,132)"

# Grade-band shading colors (low-alpha pastels). Ordered from D (lowest) to
# S (highest) so the trajectory line reads top-to-bottom by quality. Hex
# values match the dashboard's existing palette intent; alpha kept ≤ 0.12
# so the bands never compete with the ticker line for visual weight.
GRADE_BAND_COLORS = {
    "D": "rgba(232,93,93,0.10)",   # PASTEL_RED at low alpha
    "C": "rgba(234,179,8,0.09)",   # warm amber
    "B": "rgba(140,148,158,0.07)", # neutral grey (PASTEL_GREY family)
    "A": "rgba(76,120,168,0.09)",  # ADFM_BLUE at low alpha
    "S": "rgba(82,183,136,0.12)",  # PASTEL_GREEN at low alpha
}

# Band-edge tooltip labels in display order (low-to-high CCQS).
GRADE_BAND_LABELS = [
    ("D", "Bottom 30% (D)"),
    ("C", "30-55% (C)"),
    ("B", "55-80% (B)"),
    ("A", "80-92% (A)"),
    ("S", "Top 8% (S)"),
]


def _add_grade_bands(fig: go.Figure, thresholds: pd.DataFrame, x_values: list) -> None:
    """Render grade bands as 5 stacked filled-area traces under the ticker line.

    `thresholds` is the output of load_grade_thresholds_history(): a DataFrame
    indexed by date with columns q30 / q55 / q80 / q92. We align to the same
    x_values (ticker history dates) so the bands cover exactly the line's
    horizontal range — gaps where threshold data is missing show as no fill,
    not as a broken line.
    """
    if thresholds is None or thresholds.empty:
        return
    th = thresholds.reindex(pd.Index(x_values, name="date")).ffill().bfill()
    if th.empty or th.isna().all().any():
        return

    n = len(x_values)
    zeros = [0.0] * n
    hundreds = [100.0] * n
    q30 = th["q30"].astype(float).tolist()
    q55 = th["q55"].astype(float).tolist()
    q80 = th["q80"].astype(float).tolist()
    q92 = th["q92"].astype(float).tolist()

    # Base trace at y=0 — no fill itself; gives `tonexty` its anchor.
    fig.add_trace(go.Scatter(
        x=x_values, y=zeros, mode="lines",
        line=dict(width=0, color="rgba(0,0,0,0)"),
        hoverinfo="skip", showlegend=False,
    ))
    # D band: 0 → q30
    fig.add_trace(go.Scatter(
        x=x_values, y=q30, mode="lines",
        line=dict(width=0, color="rgba(0,0,0,0)"),
        fill="tonexty", fillcolor=GRADE_BAND_COLORS["D"],
        hoverinfo="skip", showlegend=False, name="D band",
    ))
    # C band: q30 → q55
    fig.add_trace(go.Scatter(
        x=x_values, y=q55, mode="lines",
        line=dict(width=0, color="rgba(0,0,0,0)"),
        fill="tonexty", fillcolor=GRADE_BAND_COLORS["C"],
        hoverinfo="skip", showlegend=False, name="C band",
    ))
    # B band: q55 → q80
    fig.add_trace(go.Scatter(
        x=x_values, y=q80, mode="lines",
        line=dict(width=0, color="rgba(0,0,0,0)"),
        fill="tonexty", fillcolor=GRADE_BAND_COLORS["B"],
        hoverinfo="skip", showlegend=False, name="B band",
    ))
    # A band: q80 → q92
    fig.add_trace(go.Scatter(
        x=x_values, y=q92, mode="lines",
        line=dict(width=0, color="rgba(0,0,0,0)"),
        fill="tonexty", fillcolor=GRADE_BAND_COLORS["A"],
        hoverinfo="skip", showlegend=False, name="A band",
    ))
    # S band: q92 → 100
    fig.add_trace(go.Scatter(
        x=x_values, y=hundreds, mode="lines",
        line=dict(width=0, color="rgba(0,0,0,0)"),
        fill="tonexty", fillcolor=GRADE_BAND_COLORS["S"],
        hoverinfo="skip", showlegend=False, name="S band",
    ))


def ccqs_trajectory_chart(
    history: pd.DataFrame,
    height: int = CHART_HEIGHT_SMALL,
    grade_thresholds: pd.DataFrame | None = None,
) -> go.Figure:
    """Single-line CCQS history with optional per-date grade-band shading.

    `history` is indexed by date (or has a `date` column) and contains a
    `ccqs` column; if `grade` is also present it appears in the hover.

    `grade_thresholds` is the optional output of
    `load_grade_thresholds_history()` — a DataFrame with columns
    q30/q55/q80/q92 indexed by date. When provided, the chart renders the
    five S/A/B/C/D grade bands as faint filled regions tracking the per-date
    cross-sectional quantile cuts (since grades are quantile-based, not
    fixed CCQS thresholds, the bands move with the universe distribution).
    """
    fig = go.Figure()
    if history.empty or "ccqs" not in history.columns:
        fig.update_layout(
            height=height,
            margin=dict(l=12, r=12, t=8, b=24),
            paper_bgcolor=CHART_BACKGROUND,
            plot_bgcolor=CHART_BACKGROUND,
            annotations=[dict(
                text="No history available",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False,
                font=dict(color=PASTEL_GREY, size=12),
            )],
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig

    # Support both index-as-date (legacy) and reset-index DataFrames
    # (new load_ticker_history).
    if "date" in history.columns:
        x = list(history["date"])
    else:
        x = list(history.index)
    y = history["ccqs"].astype(float).tolist()

    # Grade bands first (behind the line).
    _add_grade_bands(fig, grade_thresholds, x)

    # Hover includes the grade letter when available.
    if "grade" in history.columns:
        grades = history["grade"].astype(str).tolist()
        customdata = [[g] for g in grades]
        hovertemplate = (
            "%{x|%Y-%m-%d}<br>"
            "CCQS: %{y:.1f}<br>"
            "Grade: %{customdata[0]}"
            "<extra></extra>"
        )
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines",
            line=dict(color=ADFM_BLUE, width=CHART_LINE_WIDTH),
            customdata=customdata,
            hovertemplate=hovertemplate,
            showlegend=False,
            name="CCQS",
        ))
    else:
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines",
            line=dict(color=ADFM_BLUE, width=CHART_LINE_WIDTH),
            hovertemplate="%{x|%Y-%m-%d}<br>CCQS: %{y:.1f}<extra></extra>",
            showlegend=False,
            name="CCQS",
        ))

    fig.update_layout(
        height=height,
        margin=dict(l=40, r=12, t=8, b=28),
        paper_bgcolor=CHART_BACKGROUND,
        plot_bgcolor=CHART_BACKGROUND,
        hovermode="x unified",
        xaxis=dict(
            showgrid=False,
            showline=True,
            linecolor=GRID,
            linewidth=1,
            ticks="outside",
            tickcolor=GRID,
            ticklen=4,
            tickfont=dict(color=AXIS, size=10),
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=GRID,
            gridwidth=1,
            showline=False,
            ticks="outside",
            tickcolor=GRID,
            ticklen=4,
            tickfont=dict(color=AXIS, size=10),
            zeroline=False,
            range=[0, 100],
            dtick=25,
        ),
    )
    return fig
