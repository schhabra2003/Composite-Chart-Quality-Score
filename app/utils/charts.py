"""Plotly charts. Minimalist line on a clean grid; no decoration.

All visual constants imported from app.utils.design_system.
"""
from __future__ import annotations

import math

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
GRID_SOFT = "rgb(247,248,250)"
AXIS = "rgb(120,124,132)"
ENDPOINT_FILL = "rgb(255,255,255)"

# Grade thresholds (descending). Drawn as faint horizontal references whenever
# they fall inside the visible Y window. Colours align with the grade band UI.
GRADE_LINES = [
    (92.0, "S", "rgba(70,120,200,0.55)"),
    (80.0, "A", "rgba(70,160,110,0.55)"),
    (55.0, "B", "rgba(200,170,70,0.55)"),
    (30.0, "C", "rgba(210,130,70,0.55)"),
]

# Period-specific axis configuration.
# - tickformat: strftime format applied to X ticks
# - nticks: target number of major ticks Plotly should aim for
# - hoverformat: format used in the hover crosshair label
_PERIOD_CFG: dict[str, dict] = {
    "1W":        dict(tickformat="%a %d",     nticks=7,  hoverformat="%a %b %d"),
    "1M":        dict(tickformat="%b %d",     nticks=6,  hoverformat="%b %d, %Y"),
    "3M":        dict(tickformat="%b %d",     nticks=7,  hoverformat="%b %d, %Y"),
    "6M":        dict(tickformat="%b %Y",     nticks=7,  hoverformat="%b %d, %Y"),
    "1Y":        dict(tickformat="%b %Y",     nticks=8,  hoverformat="%b %d, %Y"),
    "3Y":        dict(tickformat="%b %Y",     nticks=8,  hoverformat="%b %Y"),
    "5Y":        dict(tickformat="%Y",        nticks=6,  hoverformat="%b %Y"),
    "INCEPTION": dict(tickformat="%Y",        nticks=8,  hoverformat="%b %Y"),
}


def _ceil_to(value: float, step: float) -> float:
    """Round `value` up to the next multiple of `step`."""
    return step * (int(value / step) + (1 if value % step else 0))


def _floor_to(value: float, step: float) -> float:
    """Round `value` down to the nearest multiple of `step`."""
    return step * int(value / step)


def _fit_y_range(values: list[float]) -> tuple[float, float, float]:
    """Auto-fit Y range with axis-friendly rounding and gentle grade snapping.

    Returns (y_min, y_max, dtick). Pads by 8% on each side, rounds outward to
    the nearest 5, and only snaps to a grade threshold (0/30/55/80/92/100)
    when it's within 3 pts of the padded edge AND would expand the range.
    Prevents the "30→92 data clamped to [0,100]" failure mode by not snapping
    aggressively past wide gaps.
    """
    if not values:
        return 0.0, 100.0, 25.0
    vmin = min(values)
    vmax = max(values)
    if vmax - vmin < 1.0:        # near-flat history — give it a usable window
        mid = (vmin + vmax) / 2
        vmin, vmax = mid - 5, mid + 5

    span = vmax - vmin
    pad = max(3.0, span * 0.08)
    lo_raw = max(0.0, vmin - pad)
    hi_raw = min(100.0, vmax + pad)

    # Pick dtick first, targeting 5–9 visible gridlines.
    visible_rough = hi_raw - lo_raw
    if visible_rough <= 12:
        dtick = 2.0
    elif visible_rough <= 32:
        dtick = 5.0
    elif visible_rough <= 85:
        dtick = 10.0
    else:
        dtick = 20.0

    # Round outward to nearest 5 (axis-friendly).
    lo = max(0.0, 5.0 * math.floor(lo_raw / 5.0))
    hi = min(100.0, 5.0 * math.ceil(hi_raw / 5.0))

    # If a grade threshold sits within ~3 pts of the rounded edge and would
    # extend the range, prefer it — produces clean reference-line alignment.
    thresholds = [0.0, 30.0, 55.0, 80.0, 92.0, 100.0]
    for t in thresholds:
        if t < lo and lo - t <= 3:
            lo = t
        if t > hi and t - hi <= 3:
            hi = t

    if hi - lo < 15:             # guarantee a minimum visual height
        hi = min(100.0, lo + 15)
    return lo, hi, dtick


def ccqs_trajectory_chart(
    history: pd.DataFrame,
    period: str = "6M",
    height: int = CHART_HEIGHT_SMALL,
) -> go.Figure:
    """Institutional-grade single-line CCQS trajectory.

    Features:
      * Period-aware X-axis tick density and date format
      * Auto-fit Y range that snaps to grade boundaries (S/A/B/C/D)
      * Faint grade reference lines (only those inside the visible window)
      * Hover crosshair (spike lines on both axes)
      * Endpoint marker showing the latest CCQS value
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

    # Support both index-as-date (legacy) and reset-index DataFrames.
    if "date" in history.columns:
        x = list(history["date"])
    else:
        x = list(history.index)
    y = history["ccqs"].astype(float).tolist()

    cfg = _PERIOD_CFG.get(period, _PERIOD_CFG["6M"])
    y_lo, y_hi, dtick = _fit_y_range(y)

    # --- Grade reference lines (only those inside the visible Y window) -----
    shapes = []
    annotations = []
    for level, label, colour in GRADE_LINES:
        if y_lo < level < y_hi:
            shapes.append(dict(
                type="line",
                xref="paper", x0=0, x1=1,
                yref="y", y0=level, y1=level,
                line=dict(color=colour, width=1, dash="dot"),
                layer="below",
            ))
            annotations.append(dict(
                xref="paper", yref="y",
                x=1.0, y=level,
                xanchor="left", yanchor="middle",
                text=label,
                showarrow=False,
                font=dict(size=9, color=colour),
                xshift=4,
            ))

    # --- Main trajectory line -----------------------------------------------
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines",
        line=dict(color=ADFM_BLUE, width=CHART_LINE_WIDTH + 0.4, shape="linear"),
        hovertemplate="%{x|" + cfg["hoverformat"] + "}<br><b>CCQS %{y:.1f}</b><extra></extra>",
        showlegend=False,
        name="CCQS",
    ))

    # --- Endpoint marker with current-value annotation ----------------------
    if x and y:
        last_x = x[-1]
        last_y = y[-1]
        fig.add_trace(go.Scatter(
            x=[last_x], y=[last_y],
            mode="markers",
            marker=dict(
                size=8,
                color=ENDPOINT_FILL,
                line=dict(color=ADFM_BLUE, width=2),
            ),
            hovertemplate="%{x|" + cfg["hoverformat"] + "}<br><b>CCQS %{y:.1f}</b><extra></extra>",
            showlegend=False,
        ))
        annotations.append(dict(
            xref="x", yref="y",
            x=last_x, y=last_y,
            text=f"<b>{last_y:.1f}</b>",
            showarrow=False,
            xanchor="left", yanchor="middle",
            xshift=10,
            font=dict(size=11, color=ADFM_BLUE),
        ))

    # --- Layout --------------------------------------------------------------
    fig.update_layout(
        height=height,
        margin=dict(l=44, r=44, t=10, b=30),
        paper_bgcolor=CHART_BACKGROUND,
        plot_bgcolor=CHART_BACKGROUND,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="white",
            bordercolor=GRID,
            font=dict(size=11, color="rgb(40,44,52)"),
        ),
        shapes=shapes,
        annotations=annotations,
        xaxis=dict(
            type="date",
            showgrid=True,
            gridcolor=GRID_SOFT,
            gridwidth=1,
            showline=True,
            linecolor=GRID,
            linewidth=1,
            ticks="outside",
            tickcolor=GRID,
            ticklen=4,
            tickfont=dict(color=AXIS, size=10),
            tickformat=cfg["tickformat"],
            nticks=cfg["nticks"],
            zeroline=False,
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikecolor=PASTEL_GREY,
            spikethickness=1,
            spikedash="dot",
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
            tickformat=".0f",
            zeroline=False,
            range=[y_lo, y_hi],
            dtick=dtick,
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikecolor=PASTEL_GREY,
            spikethickness=1,
            spikedash="dot",
        ),
    )
    return fig
