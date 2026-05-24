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


def ccqs_trajectory_chart(history: pd.DataFrame, height: int = CHART_HEIGHT_SMALL) -> go.Figure:
    """Single-line CCQS history. `history` indexed by date with a `ccqs` column."""
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

    # Support both index-as-date (legacy) and reset-index DataFrames (new load_ticker_history)
    if "date" in history.columns:
        x = list(history["date"])
    else:
        x = list(history.index)
    y = history["ccqs"].astype(float).tolist()

    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines",
        line=dict(color=ADFM_BLUE, width=CHART_LINE_WIDTH),
        hovertemplate="%{x|%Y-%m-%d}<br>CCQS: %{y:.1f}<extra></extra>",
        showlegend=False,
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
